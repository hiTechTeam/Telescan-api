#!/usr/bin/env bash
set -Eeuo pipefail

active_dir=/home/ubuntu/telescan/Telescan-api
release_prefix=/home/ubuntu/telescan/.releases/Telescan-api
snapshot_prefix=/home/ubuntu/telescan/.rollback/Telescan-api
transaction_root=/home/ubuntu/telescan/.transactions/Telescan-api
controller_root="$transaction_root/controller"
runtime_dir=/home/ubuntu/telescan/.runtime/Telescan-api
gate=/home/ubuntu/telescan/Telescan-nginx/current/ops/api-maintenance-gate.sh
intent_cli="$controller_root/deploy_intent.py"
recovery_service=telescan-api-release-recovery.service
recovery_path=telescan-api-release-recovery.path

usage() {
  echo "Usage: $0 --apply --confirm DEPLOY_TELESCAN_API_WITH_ROLLBACK --deploy-id RUN-ATTEMPT --release-dir PATH | --recover-only" >&2
  exit 2
}

intent_exists() {
  python3 "$intent_cli" exists
}

intent_read() {
  python3 "$intent_cli" read --field "$1"
}

intent_phase() {
  python3 "$intent_cli" phase --expected "$1" --set "$2"
}

intent_clear() {
  python3 "$intent_cli" clear --expected "$1"
}

close_gate() {
  test -x "$gate" || return
  bash "$gate" close --owner api-deploy \
    --apply --confirm CLOSE_TELESCAN_API_INGRESS || return
}

open_gate() {
  test -x "$gate" || return
  bash "$gate" open --owner api-deploy \
    --apply --confirm OPEN_TELESCAN_API_INGRESS || return
}

require_open_gate() {
  local status
  status="$(bash "$gate" status)"
  [[ "$status" == *"api_ingress=open owners=none"* ]]
}

require_approved_directory() {
  local path="$1"
  local prefix="$2"
  test -d "$path" || return
  test ! -L "$path" || return
  [[ "$(realpath "$path")" == "$path" ]] || return
  case "$path" in
    "$prefix"/*) ;;
    *) return 1 ;;
  esac
}

wait_healthy() {
  local container_id="$1"
  local health=""
  local attempt
  test -n "$container_id" || return
  for (( attempt=1; attempt<=30; attempt++ )); do
    health="$(docker inspect --format '{{.State.Health.Status}}' \
      "$container_id" 2>/dev/null || true)"
    if [[ "$health" == healthy ]]; then
      return 0
    fi
    sleep 5
  done
  echo "API container did not become healthy (last state: ${health:-unknown})." >&2
  return 1
}

compose_container_id() {
  (cd "$active_dir" && docker compose ps -q telescan-api </dev/null)
}

compose_image_ref() {
  local images
  images="$(cd "$active_dir" && docker compose config --images </dev/null)" \
    || return
  [[ "$(printf '%s\n' "$images" | sed '/^$/d' | wc -l | tr -d ' ')" == 1 ]] \
    || return
  printf '%s\n' "$images"
}

verify_topology() {
  local release_dir="$1"
  local container_id image_id
  local -a running_ids
  container_id="$(compose_container_id)"
  test -n "$container_id" || return
  image_id="$(docker inspect --format '{{.Image}}' "$container_id")" || return
  mapfile -t running_ids < <(docker ps -q)
  [[ "${#running_ids[@]}" -gt 0 ]] || return
  docker inspect "${running_ids[@]}" | python3 \
    "$release_dir/scripts/check_api_topology.py" \
    --expected-container-id "$container_id" \
    --expected-image-id "$image_id" \
    --check-host-processes || return
}

verify_no_pending_host_intents() {
  local intent_directory="$runtime_dir/operation-intents"
  local pending_intent=""
  sudo test -d "$runtime_dir" || return
  sudo test ! -L "$runtime_dir" || return
  if sudo test -e "$intent_directory"; then
    sudo test -d "$intent_directory" || return
    sudo test ! -L "$intent_directory" || return
  fi
  if sudo test -d "$intent_directory"; then
    pending_intent="$(sudo find "$intent_directory" -maxdepth 1 -type f \
      -name '*.json' -print -quit)" || return
    if [[ -n "$pending_intent" ]]; then
      echo "Account operation recovery intent remains pending; ingress stays closed." >&2
      return 1
    fi
  fi
}

set_evidence_worker() {
  local release_dir="$1"
  local action="$2"
  [[ "$action" == enable || "$action" == disable ]] || return
  test -f "$release_dir/scripts/evidence_worker_gate.py" || return
  sudo python3 "$release_dir/scripts/evidence_worker_gate.py" "$action" \
    --path "$runtime_dir/evidence-worker.enabled" \
    --expected-uid 10001 || return
}

verify_local_candidate() {
  local release_dir="$1"
  local container_id
  container_id="$(compose_container_id)"
  wait_healthy "$container_id" || return
  verify_topology "$release_dir" || return
  (cd "$active_dir" && docker compose exec -T telescan-api \
    /app/.venv/bin/python -m scripts.check_legal_deployment \
    --allow-http-loopback --base-url http://127.0.0.1:8000 </dev/null) || return
  (cd "$active_dir" && docker compose exec -T telescan-api \
    /app/.venv/bin/python -m scripts.audit_data_invariants --strict </dev/null) \
    || return
  verify_no_pending_host_intents || return
}

verify_public_candidate() {
  local release_dir="$1"
  local container_id
  container_id="$(compose_container_id)"
  wait_healthy "$container_id" || return
  verify_topology "$release_dir" || return
  (cd "$active_dir" && docker compose exec -T telescan-api \
    /app/.venv/bin/python -m scripts.check_legal_deployment \
    --base-url https://api.tgtelescan.ru \
    --base-url https://tgtelescan.ru </dev/null) || return
}

preprovision_runtime() {
  if sudo test -L "$runtime_dir"; then
    echo "API singleton runtime directory must not be a symlink." >&2
    return 1
  fi
  sudo install -d -o 10001 -g 10001 -m 0750 "$runtime_dir"
  if sudo test -L "$runtime_dir/production-instance.lock"; then
    echo "API singleton lock must not be a symlink." >&2
    return 1
  fi
  if ! sudo test -e "$runtime_dir/production-instance.lock"; then
    sudo touch "$runtime_dir/production-instance.lock"
  fi
  sudo test -f "$runtime_dir/production-instance.lock"
  sudo chown 10001:10001 "$runtime_dir/production-instance.lock"
  sudo chmod 0600 "$runtime_dir/production-instance.lock"
  [[ "$(sudo stat -c '%u:%g:%a' "$runtime_dir")" == 10001:10001:750 ]]
  [[ "$(sudo stat -c '%u:%g:%a' \
    "$runtime_dir/production-instance.lock")" == 10001:10001:600 ]]
}

install_recovery_controller() {
  local release_dir="$1"
  if [[ -L "$transaction_root" || -L "$controller_root" ]]; then
    echo "API deployment transaction paths must not be symlinks." >&2
    return 1
  fi
  install -d -m 0700 "$transaction_root"
  install -d -m 0700 "$controller_root"
  [[ "$(stat -c '%u:%g:%a' "$transaction_root")" == \
    "$(id -u):$(id -g):700" ]]
  [[ "$(stat -c '%u:%g:%a' "$controller_root")" == \
    "$(id -u):$(id -g):700" ]]
  install -m 0755 "$release_dir/ops/deploy-production.sh" \
    "$controller_root/deploy-production.sh"
  install -m 0755 "$release_dir/scripts/deploy_intent.py" \
    "$controller_root/deploy_intent.py"
  sync -f "$controller_root/deploy-production.sh"
  sync -f "$controller_root/deploy_intent.py"
  sync -f "$controller_root"
  sync -f "$transaction_root"
  sudo install -m 0644 \
    "$release_dir/ops/systemd/$recovery_service" "/etc/systemd/system/$recovery_service"
  sudo install -m 0644 \
    "$release_dir/ops/systemd/$recovery_path" "/etc/systemd/system/$recovery_path"
  sudo systemctl daemon-reload
  sudo systemctl enable "$recovery_service"
  sudo systemctl enable --now "$recovery_path"
  sudo sync -f "/etc/systemd/system/$recovery_service"
  sudo sync -f "/etc/systemd/system/$recovery_path"
  sudo sync -f /etc/systemd/system
  if sudo test -d /etc/systemd/system/multi-user.target.wants; then
    sudo sync -f /etc/systemd/system/multi-user.target.wants
  fi
  sudo systemctl is-enabled --quiet "$recovery_service"
  sudo systemctl is-enabled --quiet "$recovery_path"
  sudo systemctl is-active --quiet "$recovery_path"
}

run_backup_and_lock_database() {
  test -f /etc/systemd/system/telescan-mongodb-backup.service || return
  sudo systemctl start telescan-mongodb-backup.service || return
  [[ "$(systemctl show telescan-mongodb-backup.service \
    --property=Result --value)" == success ]] || return
  [[ "$(systemctl show telescan-mongodb-backup.service \
    --property=ExecMainStatus --value)" == 0 ]] || return
  exec 8>/tmp/telescan-mongodb-maintenance.lock || return
  flock --exclusive --timeout 1800 8 || return
}

validate_active_config() {
  test -d "$active_dir" || return
  test ! -L "$active_dir" || return
  [[ "$(realpath "$active_dir")" == "$active_dir" ]] || return
  test -s "$active_dir/.env" || return
  [[ "$(grep -Ec '^ENVIRONMENT=production$' "$active_dir/.env")" == 1 ]] \
    || return
  (cd "$active_dir" && docker compose config --quiet </dev/null) || return
}

run_migrations() {
  local release_dir="$1"
  local image_ref="$2"
  local mode="$3"
  local -a command
  local -a apply_args=()
  [[ "$mode" == dry-run || "$mode" == apply ]]
  while IFS= read -r command_line; do
    read -r -a command <<<"$command_line"
    apply_args=()
    if [[ "$mode" == apply ]]; then
      case "${command[1]}" in
        scripts.migrate_users)
          apply_args=(--apply)
          ;;
        scripts.migrate_apple_auth)
          apply_args=(--apply --confirm MIGRATE_APPLE_AUTH)
          ;;
        scripts.migrate_universal_reports)
          apply_args=(--apply --confirm MIGRATE_UNIVERSAL_REPORTS)
          ;;
        scripts.migrate_link_code_invariants)
          apply_args=(--apply --confirm MIGRATE_LINK_CODE_INVARIANTS)
          ;;
        scripts.migrate_moderation_integrity)
          apply_args=(--apply --confirm MIGRATE_MODERATION_INTEGRITY)
          ;;
        scripts.migrate_account_operation_journals)
          apply_args=(--apply --confirm MIGRATE_ACCOUNT_OPERATION_JOURNALS)
          ;;
      esac
    fi
    docker run --rm --network telescan_network \
      --env-file "$active_dir/.env" \
      --env ENABLE_TELEGRAM_FIRST_AUTH=true \
      "$image_ref" /app/.venv/bin/python "${command[@]}" "${apply_args[@]}" \
      </dev/null
  done <<'MIGRATIONS'
-m scripts.migrate_apple_auth
-m scripts.migrate_users
-m scripts.migrate_universal_reports
-m scripts.migrate_link_code_invariants
-m scripts.migrate_moderation_integrity
-m scripts.migrate_account_operation_journals
MIGRATIONS
  # Destructive users.code removal is intentionally absent. It is dispatched
  # only by the separately confirmed post-rollback-window workflow.
  ! grep -q -- '--remove-legacy-codes' "$release_dir/.github/workflows/deploy.yml"
}

restore_previous_release() {
  local release_dir snapshot_dir previous_image_ref rollback_image_ref
  local runtime_image_ref container_id current_container_id
  release_dir="$(intent_read release_dir)" || return
  snapshot_dir="$(intent_read snapshot_dir)" || return
  previous_image_ref="$(intent_read previous_image_ref)" || return
  rollback_image_ref="$(intent_read rollback_image_ref)" || return
  require_approved_directory "$release_dir" "$release_prefix" || return
  require_approved_directory "$snapshot_dir" "$snapshot_prefix" || return
  close_gate || return
  set_evidence_worker "$release_dir" disable || return
  current_container_id="$(docker ps -q --filter name='^/telescan_api$')" || return
  if [[ -n "$current_container_id" ]]; then
    docker stop --time 30 "$current_container_id" </dev/null || return
  fi
  test -d "$snapshot_dir" || return
  rsync -a --delete --exclude '.env' "$snapshot_dir/" "$active_dir/" || return
  validate_active_config || return
  runtime_image_ref="$(compose_image_ref)" || return
  [[ "$runtime_image_ref" == "$previous_image_ref" ]] || return
  docker image inspect "$rollback_image_ref" >/dev/null || return
  docker tag "$rollback_image_ref" "$runtime_image_ref" || return
  (cd "$active_dir" && docker compose up -d --no-deps --no-build \
    --force-recreate telescan-api </dev/null) || return
  container_id="$(compose_container_id)" || return
  wait_healthy "$container_id" || return
  verify_topology "$release_dir" || return
  verify_no_pending_host_intents || return
  (cd "$active_dir" && docker compose exec -T telescan-api \
    /app/.venv/bin/python -m scripts.check_legal_deployment \
    --allow-http-loopback --base-url http://127.0.0.1:8000 </dev/null) || return
  (cd "$active_dir" && docker compose exec -T telescan-api \
    /app/.venv/bin/python -m scripts.audit_data_invariants --strict </dev/null) \
    || return
  # Resume the prior marker-aware release. Legacy images ignore this marker.
  set_evidence_worker "$release_dir" enable || return
  open_gate || return
  if ! intent_clear rollback; then
    close_gate || true
    return 1
  fi
  echo "Previous API config and image recovered healthy; candidate was never exposed."
}

finish_committed_candidate() {
  local release_dir candidate_image_id runtime_image_ref
  release_dir="$(intent_read release_dir)" || return
  candidate_image_id="$(intent_read candidate_image_id)" || return
  require_approved_directory "$release_dir" "$release_prefix" || return
  close_gate || return
  validate_active_config || return
  runtime_image_ref="$(compose_image_ref)" || return
  docker image inspect "$candidate_image_id" >/dev/null || return
  docker tag "$candidate_image_id" "$runtime_image_ref" || return
  (cd "$active_dir" && docker compose up -d --no-deps --no-build \
    --force-recreate telescan-api </dev/null) || return
  verify_local_candidate "$release_dir" || return
  set_evidence_worker "$release_dir" enable || return
  if ! open_gate; then
    intent_phase candidate_commit manual || return
    echo "CRITICAL: candidate is retained with API ingress closed." >&2
    return 20
  fi
  if ! verify_public_candidate "$release_dir"; then
    close_gate || true
    intent_phase candidate_commit manual || return
    echo "CRITICAL: public candidate verification failed; no old-image rollback is permitted." >&2
    return 20
  fi
  if ! intent_clear candidate_commit; then
    close_gate || true
    return 1
  fi
  echo "Committed API candidate recovered and public verification passed."
}

recover_transaction() {
  local phase
  intent_exists || return 0
  phase="$(intent_read phase)" || return
  # The intent may represent a candidate that was opened immediately before a
  # crash. Re-close before backup waits or any other recovery work.
  close_gate || return
  run_backup_and_lock_database || return
  case "$phase" in
    rollback)
      restore_previous_release || return
      ;;
    candidate_commit)
      finish_committed_candidate || return
      ;;
    manual)
      close_gate || true
      echo "CRITICAL: API release is in manual-review phase; ingress remains closed." >&2
      return 20
      ;;
    *)
      echo "CRITICAL: unknown API deployment phase; ingress remains fail-closed." >&2
      close_gate || true
      return 20
      ;;
  esac
}

main() {
mode=deploy
if [[ $# -eq 7 && "$1" == --apply && "$2" == --confirm && \
      "$3" == DEPLOY_TELESCAN_API_WITH_ROLLBACK && "$4" == --deploy-id && \
      "$6" == --release-dir ]]; then
  deploy_id="$5"
  release_input="$7"
elif [[ $# -eq 1 && "$1" == --recover-only ]]; then
  mode=recover
  deploy_id=""
  release_input=""
else
  usage
fi

exec 9>/tmp/telescan-production-deploy.lock
if ! flock --exclusive --timeout 1800 9; then
  echo "Timed out waiting for the shared production deployment lock." >&2
  return 1
fi

if [[ "$mode" == recover ]]; then
  [[ "$(id -un)" == ubuntu ]]
  test ! -L "$transaction_root"
  test ! -L "$controller_root"
  [[ "$(realpath "$transaction_root")" == "$transaction_root" ]]
  test -x "$intent_cli"
  recover_transaction
  exit $?
fi

[[ "$deploy_id" =~ ^[0-9]+-[0-9]+$ ]] || usage
[[ "$(id -un)" == ubuntu ]]
release_dir="$(realpath "$release_input")"
[[ "$release_dir" == "$release_input" ]] || usage
case "$release_dir" in
  "$release_prefix"/*) ;;
  *) usage ;;
esac
require_approved_directory "$release_dir" "$release_prefix"

# If a prior controller left a durable transaction, recover it without mixing
# a second candidate into the same release. The operator reruns this workflow.
if [[ -e "$transaction_root/active.json" || \
      -L "$transaction_root/active.json" ]]; then
  if [[ ! -x "$intent_cli" ]]; then
    echo "CRITICAL: an API intent exists without its durable controller." >&2
    exit 1
  fi
  if recover_transaction; then
    echo "A prior API release was recovered; rerun this deployment." >&2
    exit 20
  else
    recovery_status=$?
    exit "$recovery_status"
  fi
fi

install_recovery_controller "$release_dir"
preprovision_runtime
require_open_gate
validate_active_config
verify_topology "$release_dir"
run_backup_and_lock_database

snapshot_dir="$snapshot_prefix/$deploy_id"
if [[ -e "$snapshot_dir" || -L "$snapshot_dir" ]]; then
  echo "Rollback snapshot already exists for this deploy id." >&2
  exit 1
fi
install -d -m 0700 "$snapshot_dir"
rsync -a --delete --exclude '.env' "$active_dir/" "$snapshot_dir/"
test ! -e "$snapshot_dir/.env"
sync -f "$snapshot_dir"
sync -f "$snapshot_prefix"

previous_container_id="$(compose_container_id)"
test -n "$previous_container_id"
previous_image_id="$(docker inspect --format '{{.Image}}' "$previous_container_id")"
previous_image_ref="$(docker inspect --format '{{.Config.Image}}' \
  "$previous_container_id")"
[[ "$previous_image_ref" != *@* ]]
rollback_image_ref="telescan-api:rollback-$deploy_id"
candidate_image_ref="telescan-api:candidate-$deploy_id"
docker tag "$previous_image_id" "$rollback_image_ref"
docker build --tag "$candidate_image_ref" "$release_dir"
candidate_image_id="$(docker image inspect --format '{{.Id}}' \
  "$candidate_image_ref")"
run_migrations "$release_dir" "$candidate_image_ref" dry-run

python3 "$intent_cli" publish \
  --deploy-id "$deploy_id" \
  --release-dir "$release_dir" \
  --snapshot-dir "$snapshot_dir" \
  --previous-image-ref "$previous_image_ref" \
  --rollback-image-ref "$rollback_image_ref" \
  --candidate-image-ref "$candidate_image_ref" \
  --candidate-image-id "$candidate_image_id"
sudo systemctl is-enabled --quiet "$recovery_service"
sudo systemctl is-active --quiet "$recovery_path"

if ! close_gate; then
  restore_previous_release
  exit 1
fi

set +e
(
  set -Eeuo pipefail
  rsync -a --delete --exclude '.env' "$release_dir/" "$active_dir/"
  set_evidence_worker "$release_dir" disable
  validate_active_config
  (cd "$active_dir" && docker compose stop --timeout 30 telescan-api </dev/null)
  test -z "$(compose_container_id)"
  run_migrations "$release_dir" "$candidate_image_ref" apply
  runtime_image_ref="$(compose_image_ref)"
  docker tag "$candidate_image_id" "$runtime_image_ref"
  (cd "$active_dir" && docker compose up -d --no-deps --no-build \
    --force-recreate telescan-api </dev/null)
  verify_local_candidate "$release_dir"
)
rollout_status=$?
set -e
if [[ "$rollout_status" -ne 0 ]]; then
  if ! restore_previous_release; then
    echo "CRITICAL: candidate failed and previous API did not recover; ingress stays closed." >&2
    exit 1
  fi
  exit "$rollout_status"
fi

# This fsynced phase is the point of no return. Once it is durable, the old
# image is never restored because the candidate may become publicly reachable.
intent_phase rollback candidate_commit
set_evidence_worker "$release_dir" enable
if ! open_gate; then
  intent_phase candidate_commit manual
  echo "CRITICAL: candidate is retained and API ingress remains closed." >&2
  exit 20
fi
if ! verify_public_candidate "$release_dir"; then
  close_gate || true
  intent_phase candidate_commit manual
  echo "CRITICAL: public legal/topology gate failed; candidate retained for review." >&2
  exit 20
fi
intent_clear candidate_commit
docker image rm "$rollback_image_ref" >/dev/null 2>&1 || true
echo "Telescan API release committed after closed-ingress and public verification."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
