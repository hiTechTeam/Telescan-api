# Telescan API

FastAPI service that owns all Telescan application data and profile-photo
storage. The iOS app uses the authenticated public API; the Telegram bot uses
the service-only `/internal/v1` API. Neither client connects directly to
MongoDB or S3.

## Requirements and local run

- Python 3.13 or newer;
- [uv](https://docs.astral.sh/uv/);
- MongoDB 8;
- an S3-compatible bucket;
- the external Docker network `telescan_network` when Compose is used.

```sh
cp .env.example .env
uv sync
uv run pytest
uv run main.py
```

The Compose service publishes port 8000 only on `127.0.0.1`. Create the shared
network once before starting the container:

```sh
docker network create telescan_network
make api-up
```

Compose injects runtime settings from the host `.env`; `.dockerignore` prevents
that file, Git metadata, local virtual environments, tests, and tool caches from
being copied into image layers. The container restarts unless explicitly stopped.
`GET /health/live` checks the process, while `GET /health/ready` additionally
requires a successful bounded MongoDB ping. Production deployment waits for the
Docker health state to become `healthy`.

The production process runs as the unprivileged `telescan` user. Compose mounts
the root filesystem read-only, provides only a bounded `/tmp` tmpfs, drops every
Linux capability, and enables `no-new-privileges`. Application state belongs in
MongoDB or S3-compatible storage rather than the container filesystem.

For a complete local quality check:

```sh
uvx --from ruff==0.16.3 ruff check .
uvx --from ruff==0.16.3 ruff format --check .
uvx --from pyright==1.1.411 pyright
uv run pytest
uv lock --check
docker compose config --quiet
```

## Authentication model

The iOS app authenticates the primary Telescan account with Sign in with Apple.
The API verifies the Apple identity token signature, issuer, audience, expiry,
and nonce against Apple's public keys, then creates a device session. The Apple
subject is stored separately from the public profile and is the only way to
create or resume a Telescan session.

After authentication, the bot requests a random eight-character linking code
for a Telegram account.
Only an HMAC-SHA-256 digest is stored in the `link_codes` collection. A new code
revokes any earlier unused code for that account; a code expires after the
configured 5–10 minute TTL (10 minutes by default), is consumed atomically, and
can be used only once. The partial unique `uniq_issued_user` index is the final
concurrency guard. A consumed digest and consuming device ID remain usable as
merge-recovery proof for no more than 30 days, including when MongoDB TTL
cleanup runs late.

The bot explicitly reports whether the Telegram photo is present, absent, or
temporarily unavailable. A present photo is copied to a new unique object URL,
an absent photo removes the obsolete stored copy, and a temporary download or
S3 failure preserves the previous photo without preventing code issuance.
The S3 client validates TLS with `AWS_CA_BUNDLE` when set, otherwise with the
operating system's trusted CA bundle.

The iOS app submits the clear code to an authenticated endpoint. Successful
linking attaches the verified Telegram profile to the existing Apple-authenticated
account and never creates a session by itself. Existing pre-migration Telegram
profiles are adopted without changing their public Telescan ID, BIO, or photo.
That Telegram profile is the canonical merge target. A durable account journal
moves or deduplicates placeholder sessions, blocks, reports, the Apple identity,
codes, and pending confirmations before the placeholder user and its S3 prefix
are removed. Interrupted database or storage steps are resumed by the
maintenance worker; a retry never removes the canonical target's photo.

Sign in with Apple creates or replaces that device's session and returns:

- a short-lived HS256 access JWT containing the user and session IDs;
- a random refresh token whose SHA-256 digest is stored server-side;
- the public random `telescan_id` and shared profile.

Refresh tokens rotate on every refresh. Reuse of an old refresh token revokes
the affected session. Every protected request validates both the access JWT and
the active `DeviceSession` and its Apple identity, so a legacy Telegram session
cannot become primary authentication and logout or revocation takes effect
immediately.

App Review credentials use the separate `review_codes` collection and a
dedicated HMAC secret. They remain scoped to one existing review profile, are
single-use, share the normal link endpoint rate limits, and retain lifecycle
metadata for 90 days after expiry while unused or revoked. After successful
use, the digest/device recovery proof is retained for at most 30 days. Issue
them only from the production host:

```sh
docker compose exec telescan-api /app/.venv/bin/python -m scripts.review_codes issue \
  --telescan-id REVIEW_PROFILE_ID \
  --count 10 \
  --valid-days 30 \
  --issued-by OPERATOR \
  --apply \
  --confirm ISSUE_REVIEW_CODES

docker compose exec telescan-api /app/.venv/bin/python -m scripts.review_codes status \
  --batch-id BATCH_ID
docker compose exec telescan-api /app/.venv/bin/python -m scripts.review_codes revoke \
  --batch-id BATCH_ID \
  --revoked-by OPERATOR \
  --apply
```

Clear codes are printed once and are never stored. Copy them directly into the
private App Store Connect review notes and revoke the unused batch after review.

## API surface

Public legal pages and authentication bootstrap:

| Method | Path | Authentication |
| --- | --- | --- |
| `GET` | `/privacy`, `/terms` | Public |
| `POST` | `/api/v1/auth/apple` | Sign in with Apple identity token and nonce |
| `POST` | `/api/v1/auth/refresh` | Refresh token |

Authenticated iOS API:

| Method | Path | Purpose |
| --- | --- | --- |
| `DELETE` | `/api/v1/auth/session` | Revoke the current device session |
| `POST` | `/api/v1/auth/logout-all/request` | Request Telegram confirmation for revoking all sessions |
| `GET` | `/api/v1/auth/logout-all/requests/{confirmation_id}` | Poll the authenticated Telegram confirmation status |
| `GET` | `/api/v1/users/me` | Read the current account |
| `POST` | `/api/v1/users/me/telegram/link` | Attach Telegram with a one-time bot code |
| `PATCH` | `/api/v1/users/me` | Set or clear the optional BIO (36 characters maximum) |
| `PUT` | `/api/v1/users/me/photo` | Replace the current account photo |
| `DELETE` | `/api/v1/users/me/photo` | Remove the current account photo |
| `DELETE` | `/api/v1/users/me` | Delete the account and owned data |
| `GET` | `/api/v1/profiles/{telescan_id}` | Read a nearby public profile |
| `POST` | `/api/v1/reports` | Submit an idempotent universal profile report |
| `GET` | `/api/v1/users/me/blocks` | List blocked profiles |
| `PUT` | `/api/v1/users/me/blocks/{telescan_id}` | Block a profile |
| `DELETE` | `/api/v1/users/me/blocks/{telescan_id}` | Unblock a profile |

Bot-only API, protected by `Authorization: Bearer $BOT_SERVICE_SECRET`:

Code issuance requires a non-empty public Telegram username. Requests without
one are rejected with `422` and `code=telegram_username_required`; no profile or
link code is created.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/internal/v1/link-codes` | Upsert Telegram profile data and issue a link code |
| `PUT` | `/internal/v1/confirmations/{id}/message` | Save the Telegram confirmation message IDs |
| `GET` | `/internal/v1/confirmations/pending` | Restore pending confirmation timers |
| `POST` | `/internal/v1/confirmations/{id}/decision` | Confirm, cancel, or expire a request |

The deployed allow-listed
[Telescan admin bot](https://github.com/hiTechTeam/Telescan-admin-bot) uses a
separate API credential and never receives MongoDB access. These endpoints are
protected by
`Authorization: Bearer $MODERATION_SERVICE_SECRET`:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/internal/v1/moderation/reports` | List reports, optionally filtered by status |
| `GET` | `/internal/v1/moderation/reports/{id}` | Read a report and its captured profile snapshot |
| `PATCH` | `/internal/v1/moderation/reports/{id}` | Record review state, moderator actor, and note |

Legacy `/v1` routes are hidden from OpenAPI. They may be enabled only in a
non-production development environment with `ENABLE_LEGACY_API=true` and a
future timezone-aware `LEGACY_API_EXPIRES_AT`; production rejects the flag
unconditionally and never publishes a legacy `users.code` hash.

The current iOS MVP does not expose logout-all; it offers current-device logout
and account deletion. The logout-all endpoints and Telegram confirmation flow
remain server-side for compatibility and a later push-based client flow.

All FastAPI route functions live in `src/api/routers`. Legal document data and
rendering live in `src/api/presentation`, while the HTML shell is kept in
`src/api/templates/legal.html`; route modules do not embed page markup.

## Data ownership and deletion

MongoDB contains eleven application collections: `users`, `apple_identities`,
`link_codes`, `review_codes`, `device_sessions`, `rate_limits`,
`confirmation_requests`, `reports`, `blocks`, `account_merges`, and
`account_deletions`. Reports capture the reporter and target Telescan IDs, the
universal report kind, optional context, target name, username, BIO, moderation
state, revision, event history, evidence state, actor, and timestamps.
Blocks are unique per blocker/target pair and profile reads return `404` when
either account has blocked the other. The API also owns the
`users/{telescan_id}/...` photo prefix in S3-compatible storage.

The iOS **Met** encounter history is not an API collection. It stores resolved
public profile snapshots and last-seen timestamps only on the current device,
prunes them after 24 hours, and never uploads BLE signal or distance history.
The iOS **Saved** list is also device-local, never synchronizes through the API,
and is cleared with the local account session.

Photo replacement writes the new object, commits its URL to MongoDB, and only
then removes the obsolete object. A failed database write compensates by
deleting the new unreferenced object, so the live profile never points to an
object that was removed before the database update.

Report creation attempts to copy the current live photo into the separate
`moderation/reports/{report_id}/...` prefix and records `available`, `absent`, or
`copy_failed`. Profile replacement and account deletion only clean the
`users/{telescan_id}/...` prefix. Closed reports are terminal, receive a
180-day `retention_until`, and are removed with their evidence by the retryable
maintenance worker.

Account deletion is also journaled. It revokes sessions first, then idempotently
removes codes, confirmations, block relationships, identities, device sessions,
and the user while anonymizing retained report relations. S3 cleanup is the
final retryable step. Completed merge/deletion journals expire after 30 days;
incomplete journals have no TTL and must be reconciled.

The production rate limiter uses atomic fixed-window counters in MongoDB, so
limits are shared by all API replicas. Counter keys are SHA-256 digests and old
buckets expire through a TTL index. Link and refresh attempts are constrained
independently by the trusted edge client address and by device or token digest;
profile lookup, photo replacement, report, block, and code-issuance flows are
scoped to the authenticated actor. Responses rejected with `429` include the
remaining window in `Retry-After`.

## Migration from the legacy model

`ENABLE_LEGACY_API=true` is a development-only escape hatch for Personal Team
Debug builds that cannot carry the Sign in with Apple entitlement. Production
startup always rejects it. Set `LEGACY_API_EXPIRES_AT` to a timezone-aware ISO
8601 timestamp even in development; after that instant the compatibility path
stops working without a restart.

Before the first Apple-auth deployment, rebuild the Telegram unique index as a
partial index so multiple authenticated accounts can exist before Telegram is
linked. The command is dry-run by default:

```sh
uv run python -m scripts.migrate_apple_auth
uv run python -m scripts.migrate_apple_auth \
  --apply \
  --confirm MIGRATE_APPLE_AUTH
```

Run this migration while the API is stopped and before starting the new image.
It also creates the unique Apple subject and user indexes and revokes active
sessions whose accounts do not yet have an Apple identity. It does not modify
profiles, Telegram IDs, photos, encounter history, or public Telescan IDs.
Affected users sign in with Apple and use a fresh bot code; linking adopts their
existing Telegram profile and preserves its data.

The migration is idempotent and dry-run by default:

```sh
uv run python -m scripts.migrate_users
uv run python -m scripts.migrate_users --apply
```

It fills missing `telescan_id`, `created_at`, and `updated_at` fields and reports
duplicate Telegram IDs without deleting users or profile data. Removing the old
`users.code` field is a separate destructive post-rollout operation. It must
not run in the normal image rollout. After the old-image rollback window is
explicitly closed, dispatch the protected `Remove legacy user codes` workflow
with confirmation `REMOVE_LEGACY_CODES`. The equivalent maintenance command is:

```sh
uv run python -m scripts.migrate_users \
  --apply \
  --remove-legacy-codes \
  --confirm REMOVE_LEGACY_CODES
```

Universal reports use `clientRequestId` as their idempotency key. Deployments
also remove the obsolete pending-report index that grouped submissions by
reporter, target, and reason; without this migration, a later universal report
could reuse an already-notified moderation item. The command is safe to repeat
and does not modify report documents:

```sh
uv run python -m scripts.migrate_universal_reports
uv run python -m scripts.migrate_universal_reports \
  --apply \
  --confirm MIGRATE_UNIVERSAL_REPORTS
```

Production already rejects `ENABLE_LEGACY_API=true`, so stale hashes cannot be
used during the compatibility window. The separately audited cleanup takes a
verified backup, stops the API, unsets the fields, restores readiness, and runs
`scripts.audit_data_invariants --strict`; the audit prints aggregate counts
only.

The additional P0 migrations are dry-run by default and idempotent. Apply them
while the API is stopped, after a verified backup:

```sh
uv run python -m scripts.migrate_link_code_invariants
uv run python -m scripts.migrate_link_code_invariants \
  --apply --confirm MIGRATE_LINK_CODE_INVARIANTS
uv run python -m scripts.migrate_moderation_integrity
uv run python -m scripts.migrate_moderation_integrity \
  --apply --confirm MIGRATE_MODERATION_INTEGRITY
uv run python -m scripts.migrate_account_operation_journals
uv run python -m scripts.migrate_account_operation_journals \
  --apply --confirm MIGRATE_ACCOUNT_OPERATION_JOURNALS
uv run python -m scripts.audit_data_invariants --strict
```

## Production boundary

Production startup rejects empty, built-in, placeholder, reused, or incorrectly
routed credentials. Native-only production may keep `CORS_ORIGINS=[]`; any
configured origin must be a credential-free HTTPS origin and `*` is forbidden.
MongoDB must be `mongo:27017` on the private network and use a non-system
database with a strong least-privilege application credential. S3 is fixed to
`https://s3.ru-7.storage.selcloud.ru`, bucket `profile-photos-telescan`, and the
host-style public base
`https://profile-photos-telescan.s3.ru-7.storage.selcloud.ru` with no path,
query, or fragment. Keep
`BOT_SERVICE_SECRET` and the separate `MODERATION_SERVICE_SECRET` private and
block `/internal/` at every public proxy.

Account merge/deletion correctness relies on an explicit single-active-process
topology. Docker starts `main.py`, which pins Uvicorn to one worker; Compose
pins the service to one replica and a fixed container name; deployment stops
the old container and verifies zero instances before starting exactly one new
healthy instance. Do not run `uvicorn --workers`, scale the Compose service, or
introduce rolling overlap without replacing the in-process account locks with
a distributed admission protocol. The host directory
`/home/ubuntu/telescan/.runtime/Telescan-api` is owned by UID/GID `10001`, mode
`0750`, and bind-mounted with `create_host_path: false`. Its
`production-instance.lock` is a stable, non-symlink, single-link inode owned by
`10001:10001` with mode `0600`; never replace or unlink it during deployment.
The FastAPI lifespan takes a non-blocking kernel lock there, so alternate ASGI
launchers cannot bypass the singleton.

Before writing a merge/deletion journal, the process atomically fsyncs a
short-lived operation intent under the same host runtime. The intent contains a
stable journal ID and the minimum recovery payload. On startup, FastAPI restores
admission poison, deterministically materializes any journal missing after a
crash, reinstalls all durable fences, and only then accepts traffic. Intent files
and their directory are owner-checked and mode-checked. A production deployment
must not open ingress while one of these host intents remains pending.

For a backward-compatible moderation rollout, first deploy the additive API
with `REQUIRE_MODERATION_REVISION=false` and a timezone-aware
`MODERATION_REVISION_COMPATIBILITY_EXPIRES_AT` no more than seven days ahead.
Then deploy the admin bot that sends `revision`, set
`REQUIRE_MODERATION_REVISION=true`, clear the deadline, and redeploy the API.
Missing revisions are then rejected with `409`. Never extend the compatibility
window as a permanent bypass.

Production requests to `api.tgtelescan.ru` terminate TLS on the Netherlands EU
relay, cross an encrypted WireGuard link to the Moscow nginx origin, and then
reach FastAPI on the private Docker network. The relay and origin both return
`404` for internal and documentation paths. `tgtelescan.ru` continues to serve
the public legal pages from the Moscow edge.

FastAPI Swagger remains enabled, but nginx returns `404` for `/docs`, `/docs/`,
`/redoc`, and `/openapi.json`. Administrators access Swagger through the API's
localhost binding and an SSH tunnel documented in
[Telescan-nginx](https://github.com/hiTechTeam/Telescan-nginx).

## Repository workflow

Pull requests and pushes to `main` run Ruff, Pyright, pytest, legal-source
equality, and a Docker build. A successful `main` deployment takes and verifies
an encrypted off-host database backup, holds the host-wide production and
MongoDB-maintenance locks, and uploads only to a new immutable release path. It
then installs and fsyncs a durable deployment controller/intent and enables its
systemd boot service plus online `.path` watcher before closing the nginx
maintenance owner `api-deploy`. While public ingress returns `503`, the
controller promotes the candidate config, runs only
additive/backward-compatible migrations, proves exactly one healthy API process,
checks both the strict data audit and loopback legal bytes, and verifies that no
host account intent remains.

Before the candidate can become public, a failed gate restores the complete
previous config snapshot and protected image, re-runs local health/topology,
audit, and legal checks, and only then reopens ingress. A fsynced
`candidate_commit` phase is written immediately before opening ingress; from
that point the old image is never restored. The moderation-evidence worker is
held behind an owner/mode-checked host marker while rollback remains armed and
is enabled only after this phase becomes durable; a legacy rollback therefore
cannot orphan newly copied evidence. The controller verifies both public legal
origins after opening. A public failure immediately re-closes the
`api-deploy` marker, retains the candidate and durable `manual` phase, and
requires operator review. A crash or SSH disconnect is recovered by the same
versioned controller under the shared host lock; the nginx release watcher owns
a different marker and cannot open an API-owned maintenance window.

The schema migrations are deliberately additive or old-image compatible, but
rollback is an emergency bridge, not a final state: the old API does not append
new moderation events or run the new cleanup workers. After rollback, freeze
moderation/account mutations, investigate the failed release, and either
re-deploy the corrected new image or restore the verified pre-deploy backup
under the database recovery runbook.

Cross-service architecture, production operations, and security boundaries are
maintained in the private
[`Telescan-internal-docs`](https://github.com/hiTechTeam/Telescan-internal-docs)
repository.

## License

Proprietary and confidential. See [LICENSE](LICENSE).
