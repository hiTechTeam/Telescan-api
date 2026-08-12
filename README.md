# Telescan API

FastAPI backend for [Telescan](https://github.com/hiTechTeam/Telescan-info). It resolves Telegram profiles by code or ID, manages profile photos in S3-compatible storage, and permanently deletes account data.

## API

Interactive documentation is available at `/docs` while the server is running.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/code/?hashed_code={sha256}` | Get a profile by hashed bot code |
| `GET` | `/v1/users/?tg_id={id}` | Get a profile by Telegram ID |
| `POST` | `/v1/users/upload-photo` | Upload a Base64-encoded profile photo |
| `POST` | `/v1/users/update-photo` | Replace a photo, or delete it when `img` is `null` |
| `DELETE` | `/v1/users/` | Delete the profile and all stored photos |

Photo requests use `{"tgId": 123, "img": "base64..."}`. Account deletion uses the Telegram ID and SHA-256 code hash:

```json
{
  "tgId": 123456789,
  "hashedCode": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

A successful deletion returns `204 No Content`. The main profile response fields are `tgId`, `tgName`, `tgUsername`, and `photoS3URL`.

## Run locally

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), MongoDB, and S3-compatible storage.

Create `.env`:

```dotenv
MONGO_USERNAME=
MONGO_PASSWORD=
MONGO_HOST=
MONGO_PORT=27017
MONGO_DBNAME=
TelescanS3AccessKey=
TelescanS3SecretKey=
```

Then start the API:

```sh
uv sync
make run
```

The server listens on `http://localhost:8000`. To use Docker, first create the shared network once, then run the service:

```sh
docker network create telescan_network
make api-up
```

## Links

[iOS app](https://github.com/hiTechTeam/Telescan-iOS) · [Project documentation](https://github.com/hiTechTeam/Telescan-info) · [Developer](https://github.com/r66cha)

Licensed under the [MIT License](LICENSE).
