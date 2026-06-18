"""FastAPI application entrypoint for the Hedwig backend."""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.chat_routes import chat_router
from app.routes.digest_routes import digest_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Hedwig")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(digest_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used to confirm the server runs end-to-end."""
    return {"status": "ok"}
