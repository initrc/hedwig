---
id: T0018
title: Initialize Next.js frontend with shadcn (Lyra preset)
status: new
dependencies:
  - T0022
  - T0023
---

# Scope

- Create a `frontend/` directory at the repo root.
- Initialize a Next.js app inside it using `pnpm` with the shadcn Lyra preset.
- Add the necessary shadcn/ui components for Day 4 (Card, Sheet, Button, Input, Badge, etc.).
- Wire the frontend to the FastAPI backend with a simple `fetch` wrapper pointing to `http://localhost:8000`.
- Add a `GET /digests` endpoint to the backend (the store already has `list_recent`) so the frontend can list persisted digests.
- Add CORS middleware to the backend so the frontend (port 3000) can reach the backend (port 8000).

# Acceptance

- `pnpm dev` starts the Next.js dev server on a free port.
- `pnpm build` completes without errors.
- The backend exposes `GET /digests` and returns recent digests as JSON.
- The backend has CORS middleware allowing `http://localhost:3000`.
- The frontend renders a placeholder page confirming it can reach the backend health endpoint.

# Implementation Notes

- Use this exact command from the repo root to create the app:
  ```
  pnpm dlx shadcn@latest init --preset buFywKm --template next
  ```
  This scaffolds Next.js with TypeScript, Tailwind, and the shadcn/ui configuration.
- After init, `cd frontend` and add components via `pnpm dlx shadcn add card sheet button input badge`.
- The Lyra preset is a specific style — use it exclusively. Do not mix other shadcn themes.
- For the backend addition, add `GET /digests` to `backend/app/routes/digest_routes.py` that calls `store.list_recent()`.
- Keep the frontend simple: one page route (`app/page.tsx`) to start.
