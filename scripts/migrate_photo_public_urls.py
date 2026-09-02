"""Rewrite profile-photo URLs from the private S3 API host to its public host."""

import argparse

from pymongo import MongoClient

from src.core.config import Settings


OLD_BASE = "https://profile-photos-telescan.s3.ru-7.storage.selcloud.ru"
NEW_BASE = "https://b16a45ef-34c8-400e-8e9f-c71d081ad546.selstorage.ru"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def rewrite_photo_url(url: str | None) -> str | None:
    prefix = f"{OLD_BASE}/"
    if not url or not url.startswith(prefix):
        return url
    return f"{NEW_BASE}/{url.removeprefix(prefix)}"


def migrate(collection, *, apply: bool) -> dict[str, int]:
    scanned = changed = 0
    for user in collection.find(
        {"photo_s3_link": {"$type": "string"}}, {"photo_s3_link": 1}
    ):
        scanned += 1
        old_url = user["photo_s3_link"]
        new_url = rewrite_photo_url(old_url)
        if new_url == old_url:
            continue
        changed += 1
        if apply:
            collection.update_one(
                {"_id": user["_id"], "photo_s3_link": old_url},
                {"$set": {"photo_s3_link": new_url}},
            )
    return {"scanned": scanned, "would_change": changed}


def main() -> None:
    args = parse_args()
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        report = migrate(client[settings.mongo_dbname]["users"], apply=args.apply)
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
