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

The bot requests a random eight-character link code for a Telegram account.
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

The iOS app submits the clear code with a random installation `device_id`.
Successful linking creates or replaces that device's session and returns:

- a short-lived HS256 access JWT containing the user and session IDs;
- a random refresh token whose SHA-256 digest is stored server-side;
- the public random `telescan_id` and shared profile.

Refresh tokens rotate on every refresh. Reuse of an old refresh token revokes
the affected session. Every protected request validates both the access JWT and
the active `DeviceSession`, so logout and revocation take effect immediately.

## API surface

Public legal pages and authentication bootstrap:

| Method | Path | Authentication |
| --- | --- | --- |
| `GET` | `/privacy`, `/terms` | Public |
| `POST` | `/api/v1/auth/link` | One-time link code |
| `POST` | `/api/v1/auth/refresh` | Refresh token |

Authenticated iOS API:

| Method | Path | Purpose |
| --- | --- | --- |
| `DELETE` | `/api/v1/auth/session` | Revoke the current device session |
| `POST` | `/api/v1/auth/logout-all/request` | Request Telegram confirmation for revoking all sessions |
| `GET` | `/api/v1/auth/logout-all/requests/{confirmation_id}` | Poll the authenticated Telegram confirmation status |
| `GET` | `/api/v1/users/me` | Read the current account |
| `PUT` | `/api/v1/users/me/photo` | Replace the current account photo |
| `DELETE` | `/api/v1/users/me/photo` | Remove the current account photo |
| `DELETE` | `/api/v1/users/me` | Delete the account and owned data |
| `GET` | `/api/v1/profiles/{telescan_id}` | Read a nearby public profile |
| `POST` | `/api/v1/reports` | Submit an idempotent profile report |
| `GET` | `/api/v1/users/me/blocks` | List blocked profiles |
| `PUT` | `/api/v1/users/me/blocks/{telescan_id}` | Block a profile |
| `DELETE` | `/api/v1/users/me/blocks/{telescan_id}` | Unblock a profile |

Bot-only API, protected by `Authorization: Bearer $BOT_SERVICE_SECRET`:

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

Legacy `/v1` routes are hidden from OpenAPI and are registered only when
`ENABLE_LEGACY_API=true`. Keep this compatibility window short.

The current iOS MVP does not expose logout-all; it offers current-device logout
and account deletion. The logout-all endpoints and Telegram confirmation flow
remain server-side for compatibility and a later push-based client flow.

All FastAPI route functions live in `src/api/routers`. Legal document data and
rendering live in `src/api/presentation`, while the HTML shell is kept in
`src/api/templates/legal.html`; route modules do not embed page markup.

## Data ownership and deletion

MongoDB contains seven application collections: `users`, `link_codes`,
`device_sessions`, `rate_limits`, `confirmation_requests`, `reports`, and
`blocks`. Reports capture the reporter and target Telescan IDs, reason, optional
context, target profile snapshot, moderation status, actor, and timestamps.
Blocks are unique per blocker/target pair and profile reads return `404` when
either account has blocked the other. The API also owns the
`users/{telescan_id}/...` photo prefix in S3-compatible storage.

Account deletion first revokes all sessions, then removes photos, link codes,
confirmation requests, block relationships, device sessions, and finally the
user record. Abuse reports are retained for moderation, but direct account
relations are removed; resolved or dismissed reports expire through a 180-day
TTL. A storage failure therefore cannot leave a usable authenticated session.

The production rate limiter uses atomic fixed-window counters in MongoDB, so
limits are shared by all API replicas. Counter keys are SHA-256 digests and old
buckets expire through a TTL index. Link and refresh attempts are constrained
independently by the trusted edge client address and by device or token digest;
profile lookup, photo replacement, report, block, and code-issuance flows are
scoped to the authenticated actor. Responses rejected with `429` include the
remaining window in `Retry-After`.

## Migration from the legacy model

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

While `ENABLE_LEGACY_API=true`, newly issued codes are additionally published as
legacy SHA-256 hashes for already released old clients. Disable legacy routes
before removing those fields.

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
build. A successful push to `main` deploys through the production environment
and waits for the readiness health check. Concurrency serializes production
deployments so two API releases cannot update the host at the same time.

This implementation repository is private. The current GitHub plan does not
enforce branch protection/rulesets or provide secret scanning and push
protection for private repositories, so pull-request review and the green
`Validate and build` job are currently procedural merge gates. Dependabot
vulnerability alerts and security updates are enabled. Do not force-push or
delete `main`.

Cross-service architecture, production operations, and security boundaries are
maintained in the private
[`Telescan-internal-docs`](https://github.com/hiTechTeam/Telescan-internal-docs)
repository.

## License

Proprietary and confidential. See [LICENSE](LICENSE).
