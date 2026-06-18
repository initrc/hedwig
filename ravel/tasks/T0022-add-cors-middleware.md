---
id: T0022
title: Add CORS middleware to FastAPI
status: new
dependencies: []
---

# Scope

- Add `CORSMiddleware` to `backend/app/main.py` so the Next.js frontend (running on a different origin) can make cross-origin requests.
- Allow the Next.js dev server origin (`http://localhost:3000`) and allow all standard HTTP methods and headers.

# Acceptance

- `GET /health` from `curl` or a browser fetch at `http://localhost:3000` succeeds without a CORS preflight error.
- All existing endpoints remain accessible from the same origin.

# Implementation Notes

- Import `CORSMiddleware` from `fastapi.middleware.cors`.
- Configure `allow_origins=["http://localhost:3000"]` for dev; leave a note that production origins should be configured via env var.
- Add this early in the app setup so it wraps every route.
