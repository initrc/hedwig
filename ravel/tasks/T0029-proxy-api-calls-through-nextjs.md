---
id: T0029
title: Proxy API calls through Next.js
status: done
dependencies: []
---

# Scope

- Route browser API calls through the Next.js dev server so the frontend and
  backend share a single origin from the browser's perspective.
- Eliminate the need for backend CORS configuration and LAN-specific
  `NEXT_PUBLIC_API_BASE_URL` / `CORS_ORIGINS` env vars to reach the app from
  another device on the same network.

# Acceptance

- A Next.js rewrite forwards `/api/:path*` from the frontend dev server to
  the FastAPI backend (`http://localhost:8000` by default).
- The frontend client fetcher (`frontend/lib/api.ts`) targets `/api` by
  default, so the browser only ever issues same-origin requests.
- The app loads on a laptop browser and on a phone on the same LAN with no
  per-device env vars.
- Backend CORS middleware is removed; no LAN host needs to be added to reach
  the backend from the phone.
- `NEXT_PUBLIC_API_BASE_URL` is no longer required in `frontend/.env.local`,
  and `CORS_ORIGINS` is no longer required in `backend/.env` for LAN access.
- The project builds, passes lint, and all tests pass.

# Implementation Notes

- `frontend/next.config.ts` adds a `rewrites()` entry mapping `/api/:path*`
  to the backend URL. The backend URL is read from `API_BASE_URL` (server-side
  only — not `NEXT_PUBLIC_`) so it can be overridden, defaulting to
  `http://localhost:8000`.
- `frontend/lib/api.ts:1` defaults `API_BASE_URL` to `/api` (same-origin).
  Without the `NEXT_PUBLIC_` prefix, the var is not inlined into the client
  bundle, so the browser always uses `/api` and the proxy handles the rest.
- `NEXT_PUBLIC_API_BASE_URL` was removed from `frontend/.env.local`.
- The backend CORS middleware was removed entirely from
  `backend/app/main.py`; the browser no longer reaches the backend directly.
  `CORS_ORIGINS` was removed from `backend/.env` and `backend/.env.example`.
- `allowedDevOrigins` and `ALLOWED_DEV_ORIGINS` were dropped from
  `frontend/next.config.ts` and `frontend/.env.local` deleted. Phone HMR is
  no longer allowed, so reload the phone manually to see code changes. Pages
  and proxied API calls still work from the phone without it.
- The backend must still be reachable from the Next.js process. When running
  the backend with `uv run fastapi dev`, bind it to `0.0.0.0`
  (`--host 0.0.0.0`) only if Next.js and FastAPI run on different hosts; on a
  single laptop the default `127.0.0.1` is fine because Next.js rewrites are
  made server-side from the same machine.
- Tradeoff: server-side proxying adds a hop per request in dev. For this app's
  low request volume that is negligible, and it removes all CORS/env
  per-device configuration. This pattern carries over to a same-origin prod
  deployment (e.g. a single Cloud Run service or a load balancer routing
  `/api/*` to the backend).
