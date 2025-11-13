"""FastAPI application instance."""

# -- Imports

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from beanie import init_beanie
from src.core.config import settings as s
from src.api.v1.server.routers import main_router
from src.core.log import conf_logging
from src.core.db import mongo_client
from src.core.db.models import User


# -- Exports

__all__ = ["app"]

# --


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_beanie(
        database=mongo_client[s.mongo_client_name],
        document_models=[User],
    )
    conf_logging(level=logging.INFO)

    yield

    await mongo_client.close()


app = FastAPI(
    title=s._description.title,
    description=s._description.description,
    version=s._description.version,
    default_response_class=ORJSONResponse,
    docs_url="/docs",
    lifespan=lifespan,
)

app.include_router(main_router)

app.add_middleware(
    middleware_class=CORSMiddleware,
    allow_origins=["*"],
)
