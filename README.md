# Telescan API

The API is the sole owner of Telescan MongoDB collections and S3 profile photos.
The Telegram bot uses authenticated `/internal/v1` endpoints; iOS uses short-lived
access tokens and rotating per-device refresh sessions.

## Local run

Python 3.13+, MongoDB 8, and an S3-compatible bucket are required.

```sh
cp .env.example .env
uv sync
uv run pytest
uv run main.py
```

`MONGO_DBNAME` is used as the real database name. Production startup rejects
development secrets and an empty CORS allow-list. Internal requests require
`Authorization: Bearer $BOT_SERVICE_SECRET`; the public nginx edge must deny
`/internal/`, and neither service may log the secret.

## API v1

- `POST /api/v1/auth/link`
- `POST /api/v1/auth/refresh`
- `DELETE /api/v1/auth/session`
- `POST /api/v1/auth/logout-all/request`
- `GET /api/v1/users/me`
- `PUT|DELETE /api/v1/users/me/photo`
- `DELETE /api/v1/users/me`
- `GET /api/v1/profiles/{telescan_id}`
- `POST /internal/v1/link-codes`
- internal confirmation message, restore, and decision endpoints

Except for link, refresh, and the legal pages, application endpoints require an
access JWT and an active `DeviceSession`; revocation therefore takes effect
immediately.

## Migration

The migration is dry-run unless `--apply` is supplied:

```sh
uv run python -m scripts.migrate_users
uv run python -m scripts.migrate_users --apply
```

It only fills missing UUID/timestamps and reports duplicate Telegram IDs. During
a short old-iOS transition, set `ENABLE_LEGACY_API=true`; it reads the legacy
hash directly without adding `code` back to the new model. While enabled, newly
issued bot codes are also SHA-256-hashed into that raw legacy field so an old
iOS installation can still re-link; this compatibility path is not one-time and
must be kept short. After the new iOS version is adopted, disable legacy routes
first, then review a cleanup dry-run.
Actual hash removal additionally requires both `--apply` and
`--confirm REMOVE_LEGACY_CODES`. No user documents are deleted by the migration.
