---
id: T0023
title: Add GET /digests endpoint
status: done
dependencies: []
---

# Scope

- Add a `GET /digests` endpoint to `backend/app/routes/digest_routes.py` that returns the most recent digests as JSON.
- Reuse the existing `DigestStore.list_recent()` method.
- The endpoint should use the same `get_store()` dependency already used by `POST /digest/run`.

# Acceptance

- `GET /digests` returns a JSON array of `Digest` objects, newest date first.
- `GET /digests?limit=5` returns at most 5 digests.
- The endpoint is accessible from the frontend (CORS already handled by T0022).
- All existing tests pass.

# Implementation Notes

- The `DigestStore` already has `list_recent(limit=10)`. Wire it directly.
- Add a simple `limit` query parameter with a sensible default.
- Return the array as a Pydantic model dump — FastAPI handles the rest.
