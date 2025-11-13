from pymongo import AsyncMongoClient
from .conf import mongo_db_url


__all__ = ["mongo_client"]


class MongoClient:
    def __init__(self, url: str):
        self.url = url
        self.client = AsyncMongoClient(self.url)

    @property
    def get_mongo_client(self) -> AsyncMongoClient:
        return self.client


mongo_client = MongoClient(url=mongo_db_url.get_MongoDB_URL).get_mongo_client
