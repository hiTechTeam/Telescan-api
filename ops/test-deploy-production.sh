#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=deploy-production.sh
source "$repository_root/ops/deploy-production.sh"

test_root="$(realpath "$(mktemp -d /tmp/telescan-api-deploy-test.XXXXXX)")"
cleanup() {
  if [[ -d "${runtime_dir:-}" ]]; then
    chmod 700 "$runtime_dir" || true
  fi
  case "$test_root" in
    /tmp/telescan-api-deploy-test.*|/private/tmp/telescan-api-deploy-test.*)
      rm -rf "$test_root"
      ;;
    *) return 1 ;;
  esac
}
trap cleanup EXIT

active_dir="$test_root/active"
release_prefix="$test_root/releases"
snapshot_prefix="$test_root/snapshots"
fixture_release_dir="$release_prefix/release"
fixture_snapshot_dir="$snapshot_prefix/snapshot"
mkdir -p "$active_dir" "$fixture_release_dir" "$fixture_snapshot_dir"
events="$test_root/events"

intent_read() {
  case "$1" in
    release_dir) printf '%s\n' "$fixture_release_dir" ;;
    snapshot_dir) printf '%s\n' "$fixture_snapshot_dir" ;;
    previous_image_ref) printf '%s\n' telescan-api:previous ;;
    rollback_image_ref) printf '%s\n' telescan-api:rollback ;;
    candidate_image_id) printf '%s\n' sha256:candidate ;;
    phase) printf '%s\n' candidate_commit ;;
    *) return 2 ;;
  esac
}
close_gate() { printf 'close\n' >>"$events"; }
open_gate() { printf 'open\n' >>"$events"; }
set_evidence_worker() { printf 'evidence:%s\n' "$2" >>"$events"; }
intent_clear() { printf 'clear\n' >>"$events"; }
validate_active_config() { return 0; }
compose_image_ref() { printf '%s\n' telescan-api:previous; }
compose_container_id() { printf '%s\n' candidate-container; }
verify_topology() { printf 'topology\n' >>"$events"; }
docker() {
  if [[ "$1" == ps ]]; then
    return 0
  fi
  return 0
}

# A config restore failure must never reach image start, health, ingress open,
# or intent deletion—even though the function is invoked from an `if` context.
rsync() { return 42; }
if restore_previous_release; then
  echo "rollback unexpectedly ignored an rsync failure" >&2
  exit 1
fi
grep -qx close "$events"
! grep -qE 'open|clear|topology' "$events"

# A restored-container health failure is equally fail-closed.
: >"$events"
rsync() { return 0; }
wait_healthy() { return 43; }
if restore_previous_release; then
  echo "rollback unexpectedly ignored a health failure" >&2
  exit 1
fi
grep -qx close "$events"
! grep -qE 'open|clear|topology' "$events"

# Recovery must close ingress before it can block on backup/maintenance work.
: >"$events"
intent_exists() { return 0; }
run_backup_and_lock_database() {
  printf 'backup\n' >>"$events"
  return 44
}
if recover_transaction; then
  echo "recovery unexpectedly ignored a backup failure" >&2
  exit 1
fi
[[ "$(sed -n '1p' "$events")" == close ]]
[[ "$(sed -n '2p' "$events")" == backup ]]

# The controller user cannot traverse the production 10001:10001/0750 runtime.
# Inventory must therefore use a privileged, fail-closed read and still detect
# a pending account-operation intent.
runtime_dir="$test_root/runtime"
mkdir -p "$runtime_dir/operation-intents"
touch "$runtime_dir/operation-intents/pending.json"
chmod 000 "$runtime_dir"
sudo() {
  chmod 700 "$runtime_dir"
  "$@"
  local status=$?
  chmod 000 "$runtime_dir"
  return "$status"
}
if verify_no_pending_host_intents; then
  echo "privileged pending-intent inventory unexpectedly passed" >&2
  exit 1
fi
chmod 700 "$runtime_dir"

echo "API deployment fail-closed injection fixtures passed"
