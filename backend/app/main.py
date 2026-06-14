"""FastAPI application entrypoint for the Hedwig backend."""

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI(title="Hedwig")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used to confirm the server runs end-to-end."""
    return {"status": "ok"}
