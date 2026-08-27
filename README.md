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
can be used only once.

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
metadata for 90 days after expiry. Issue them only from the production host:

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
| `POST` | `/api/v1/reports` | Submit an idempotent profile report |
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

Legacy `/v1` routes are hidden from OpenAPI and are available only when
`ENABLE_LEGACY_API=true` and the timezone-aware `LEGACY_API_EXPIRES_AT` is
still in the future. Production rejects a compatibility window longer than 14
days.

The current iOS MVP does not expose logout-all; it offers current-device logout
and account deletion. The logout-all endpoints and Telegram confirmation flow
remain server-side for compatibility and a later push-based client flow.

All FastAPI route functions live in `src/api/routers`. Legal document data and
rendering live in `src/api/presentation`, while the HTML shell is kept in
`src/api/templates/legal.html`; route modules do not embed page markup.

## Data ownership and deletion

MongoDB contains nine application collections: `users`, `apple_identities`, `link_codes`,
`review_codes`, `device_sessions`, `rate_limits`, `confirmation_requests`,
`reports`, and `blocks`. Reports capture the reporter and target Telescan IDs,
reason, optional context, target name, username, BIO and photo snapshot,
moderation status, actor, and
timestamps.
Blocks are unique per blocker/target pair and profile reads return `404` when
either account has blocked the other. The API also owns the
`users/{telescan_id}/...` photo prefix in S3-compatible storage.

The iOS **Met** encounter history is not an API collection. It stores resolved
public profile snapshots and last-seen timestamps only on the current device,
prunes them after 24 hours, and never uploads BLE signal or distance history.

Account deletion first revokes all sessions, then removes photos, regular and
review link codes, confirmation requests, block relationships, device sessions,
and finally the user record. Abuse reports are retained for moderation, but
direct account relations are removed; resolved or dismissed reports expire
through a 180-day TTL. A storage failure therefore cannot leave a usable
authenticated session.

The production rate limiter uses atomic fixed-window counters in MongoDB, so
limits are shared by all API replicas. Counter keys are SHA-256 digests and old
buckets expire through a TTL index. Link and refresh attempts are constrained
independently by the trusted edge client address and by device or token digest;
profile lookup, photo replacement, report, block, and code-issuance flows are
scoped to the authenticated actor. Responses rejected with `429` include the
remaining window in `Retry-After`.

## Migration from the legacy model

`ENABLE_LEGACY_API=true` temporarily restores Telegram-code session creation
for Personal Team Debug builds that cannot carry the Sign in with Apple
entitlement. Set `LEGACY_API_EXPIRES_AT` to a timezone-aware ISO 8601 timestamp;
after that instant the compatibility path and its sessions stop working without
a restart. While active, profile discovery includes legacy profiles and repeated
deployments do not revoke their sessions. Keep the flag disabled for the release
Apple-first flow.

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
`users.code` field is a separate post-rollout operation:

```sh
uv run python -m scripts.migrate_users \
  --apply \
  --remove-legacy-codes \
  --confirm REMOVE_LEGACY_CODES
```

While the time-limited legacy API is active, newly issued codes are additionally
published as legacy SHA-256 hashes for already released old clients. Disable
legacy routes before removing those fields.

## Production boundary

Production startup rejects built-in development secrets and requires an
explicit, non-wildcard CORS allow-list. It connects to MongoDB through the
least-privilege application account, not the MongoDB root account. Keep
`BOT_SERVICE_SECRET` and the separate `MODERATION_SERVICE_SECRET` private and
block `/internal/` at every public proxy.

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

Pull requests and pushes to `main` run Ruff, Pyright, pytest, and a Docker
build. A successful push to `main` creates and verifies an encrypted off-host
database backup, builds the new image while the current API remains available,
runs the idempotent Apple-auth migration during a short API stop, deploys
through the production environment, and waits for the readiness health check.
Concurrency serializes production deployments so two API releases cannot
update the host at the same time.

Cross-service architecture, production operations, and security boundaries are
maintained in the private
[`Telescan-internal-docs`](https://github.com/hiTechTeam/Telescan-internal-docs)
repository.

## License

Proprietary and confidential. See [LICENSE](LICENSE).
