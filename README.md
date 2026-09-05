# Telescan API

FastAPI service that owns Telescan accounts, sessions, profiles, photos,
reports, blocks and shared rate limits. iOS uses the authenticated public API;
the Telegram bots use separate internal credentials. Clients never connect
directly to MongoDB or S3.

## Local run

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), MongoDB 8 and
S3-compatible storage.

```sh
cp .env.example .env
uv sync
uv run pytest
uv run main.py
```

With Docker:

```sh
docker network create telescan_network  # once
make api-up
```

The API binds to `127.0.0.1:8000`. `/health/live` checks the process and
`/health/ready` also checks MongoDB.

## Core contracts

- Sign in with Apple is the production primary identity. Personal Team builds
  may use the explicitly enabled Telegram-first compatibility flow.
- Telegram linking uses short-lived, one-time codes stored only as keyed
  digests. A code never creates a session by itself.
- Access tokens are short-lived; refresh tokens rotate and are stored as
  server-side hashes. Reuse revokes the affected session.
- Account merge and deletion are durable, resumable operations. Completed
  journals expire; unfinished operations remain recoverable.
- Photos are replaced safely: the database never points to an object removed
  before the update succeeds.
- Reports are idempotent and may retain separate moderation evidence for 180
  days after closure. Blocks hide profiles in both directions.

Public routes include `/privacy`, `/terms`, Apple authentication and token
refresh. Authenticated routes live under `/api/v1`; bot and moderation routes
live under `/internal/v1` and use different service secrets. Public nginx
returns `404` for internal routes and Swagger/OpenAPI paths.

Issue App Review codes only on production:

```sh
docker compose exec telescan-api /app/.venv/bin/python -m scripts.review_codes issue \
  --telescan-id REVIEW_PROFILE_ID --count 10 --valid-days 90 \
  --issued-by OPERATOR --apply --confirm ISSUE_REVIEW_CODES
```

Clear codes are printed once. Store them only in private App Store Connect
notes and revoke unused codes after review.

## Checks and migrations

```sh
uvx --from ruff==0.16.3 ruff check .
uvx --from pyright==1.1.411 pyright
uv run pytest
uv lock --check
docker compose config --quiet
```

Migration commands under `scripts/` are dry-run and idempotent by default.
Apply them only after a verified backup and, when documented, with the API
stopped. Legacy authentication is forbidden in production.

## Production

Normal traffic terminates TLS on the EU relay, crosses WireGuard to Moscow
nginx, then reaches the API on the private Docker network. Production requires
one API process; do not add Uvicorn workers or overlapping replicas without a
distributed account-operation lock.

Pushes to protected `main` run lint, type checks, tests, legal-source equality
and a Docker build. Deployment takes a verified database backup, closes API
ingress, applies compatible migrations and checks health, data invariants and
legal pages. Failed pre-publication checks restore the previous release; a
failure after exposure closes ingress for operator review.

## License

Proprietary and confidential. See [LICENSE](LICENSE).
