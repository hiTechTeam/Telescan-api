# Telescan API

Backend REST API for the application [Telescan-iOS](https://github.com/hiTechTeam/Telescan-iOS)

The API is responsible for:

- Validation and binding of authentication codes from the Telegram bot
- Storage and release of Telegram profile data
- Update user avatars
- Safe work with hashed codes

## Base URL

The development uses a tunnel (for example, Pinggy).

## Endpoints

### GET /v1/code

Get profile data using hashed code.

**Query parameters**

- `hashed_code` — SHA-256 hash of the 8-character code from the bot (required)

**Response (200 OK)**

```json
{
  "tgId": 123456789,
  "tgName": "Ivan Ivanov",
  "tgUsername": "ivan_rockets",
  "photoS3URL": "https://s3.amazonaws.com/.../photo.jpg"
}
```

**Response (404 Not Found)**

```json
{
  "detail": "Not Found"
}
```

### GET /v1/users

Get profile data by Telegram ID.

**Query parameters**

- `tg_id` — Telegram user ID (required)

**Response (200 OK)**

```json
{
  "tgName": "Ivan Ivanov",
  "tgUsername": "ivan_rockets",
  "photoS3URL": "https://s3.amazonaws.com/.../photo.jpg"
}
```

**Response (404 Not Found)**

```json
{
  "detail": "Not Found"
}
```

### POST /v1/users/upload-photo

Upload the user's photo to S3 and update the user's record.

**Request body**

```json
{
  "tgId": 123456789,
  "img": "base64-encoded-image-data"
}
```

**Response (200 OK)**

```json
{
  "tgId": 123456789,
  "photoS3URL": "https://b16a45ef-34c8-400e-8e9f-c71d081ad546.selstorage.ru/123456789.jpg"
}
```

**Response (404 Not Found)**

```json
{
  "detail": "Not Found"
}
```

**Response (500 Internal Server Error)**

```json
{
  "detail": "Failed to download or upload photo"
}
```

### POST /v1/users/update-photo

Update user photo. If `img` is `null`, the photo will be deleted.

**Request body**

```json
{
  "tgId": 123456789,
  "img": "base64-encoded-image-data"
}
```

Or to delete a photo:

```json
{
  "tgId": 123456789,
  "img": null
}
```

**Response (200 OK)**

```json
{
  "tgId": 123456789,
  "photoS3URL": "https://b16a45ef-34c8-400e-8e9f-c71d081ad546.selstorage.ru/123456789.jpg"
}
```

Or when deleting:

```json
{
  "tgId": 123456789,
  "photoS3URL": null
}
```

**Response (404 Not Found)**

```json
{
  "detail": "User not found"
}
```

**Response (400 Bad Request)**

```json
{
  "detail": "Invalid base64 image"
}
```

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/hiTechTeam/Telescan-api.git
   cd Telescan-api
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

The server will be available at `http://localhost:8000`.

### Running with Docker

```bash
make api-up
```

Or:

```bash
docker compose up --build -d
```

## Environment variables

Create a `.env` file in the project root with the following variables:

- `TelescanS3AccessKey` - S3 access key
- `TelescanS3SecretKey` - Secret key for S3
- MongoDB connection data

## Development and contributions

The project is open for contributions. If you want to help:

- Fork the repository
- Create a thread describing the change
- Open Pull Request

Especially useful:

- Improved bot interface
- Adding localizations
- Testing and searching for bugs

## Contacts

- Developer: [r66cha](https://github.com/r66cha)
- Documentation and roadmap: https://github.com/hiTechTeam/Telescan-info
