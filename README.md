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

For a complete local quality check:

```sh
ruff check .
ruff format --check .
pyright
uv run pytest
uv lock --check
docker compose config --quiet
```

## Authentication model

The bot requests a random eight-character link code for a Telegram account.
Only an HMAC-SHA-256 digest is stored in the `link_codes` collection. A new code
revokes any earlier unused code for that account; a code expires after 5–10
minutes, is consumed atomically, and can be used only once.

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

Bot-only API, protected by `Authorization: Bearer $BOT_SERVICE_SECRET`:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/internal/v1/link-codes` | Upsert Telegram profile data and issue a link code |
| `PUT` | `/internal/v1/confirmations/{id}/message` | Save the Telegram confirmation message IDs |
| `GET` | `/internal/v1/confirmations/pending` | Restore pending confirmation timers |
| `POST` | `/internal/v1/confirmations/{id}/decision` | Confirm, cancel, or expire a request |

Legacy `/v1` routes are hidden from OpenAPI and are registered only when
`ENABLE_LEGACY_API=true`. Keep this compatibility window short.

The current iOS MVP does not expose logout-all; it offers current-device logout
and account deletion. The logout-all endpoints and Telegram confirmation flow
remain server-side for compatibility and a later push-based client flow.

All FastAPI route functions live in `src/api/routers`. Legal document data and
rendering live in `src/api/presentation`, while the HTML shell is kept in
`src/api/templates/legal.html`; route modules do not embed page markup.

## Data ownership and deletion

MongoDB contains four application collections: `users`, `link_codes`,
`device_sessions`, and `confirmation_requests`. The API also owns the
`users/{telescan_id}/...` photo prefix in S3-compatible storage.

Account deletion first revokes all sessions, then removes photos, link codes,
confirmation requests, device sessions, and finally the user record. A storage
failure therefore cannot leave a usable authenticated session.

The built-in rate limiter currently protects link, refresh, profile lookup, and
code-issuance flows in one API process. It is memory-backed and is not shared
between replicas; a distributed adapter is still required before horizontal
scaling.

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
explicit, non-wildcard CORS allow-list. Keep `BOT_SERVICE_SECRET` private and
block `/internal/` at every public proxy.

FastAPI Swagger remains enabled, but nginx returns `404` for `/docs`, `/docs/`,
`/redoc`, and `/openapi.json`. Administrators access Swagger through the API's
localhost binding and an SSH tunnel documented in
[Telescan-nginx](https://github.com/hiTechTeam/Telescan-nginx).
