---
id: T0027
title: Show every digest on the dashboard
status: new
dependencies:
  - T0026
---

# Scope

- Replace the dashboard's "latest digest only" view with one that renders every
  digest returned by `GET /digests`, grouped by day, newest date first.
- No day picker or date filter — just show everything the backend returns,
  one section per day.
- The existing label filter continues to operate, now across all days' topics.

# Acceptance

- The dashboard renders every digest in the `GET /digests` response, newest
  date first, as one section per day (date heading + that day's topic cards).
- The label filter filters topics across all visible days; a day with no
  matching topics is hidden, not shown empty.
- Empty, loading, and error states still render correctly when there are no
  digests, while `GET /digests` is in flight, or when the request fails.
- The dashboard fetches enough digests to show the full history rather than the
  default 10-cap (see Implementation Notes).
- `pnpm build` and lint pass.

# Implementation Notes

- The backend change that motivates this task is T0026: `POST /digest/run` now
  produces one digest per day, so `GET /digests` can return several digests
  spanning different days.
- **`GET /digests` caps results at `limit` (default 10).** The route is
  `backend/app/routes/digest_routes.py:99` (`def digests_list(..., limit: int
  = 10)`), backed by `DigestStore.list_recent(limit=...)`
  (`backend/app/storage/digest_store.py:93`). The frontend must fetch more
  than the default — either pass a high `?limit=` from the frontend, or raise
  the route default. Prefer raising the route default (or dropping the cap) so
  every caller sees the full history; note the chosen value in the task when
  implemented. This is a small backend change and is in scope for this task.
- The component to change is `frontend/components/digest-card-list.tsx`. Today
  it fetches `GET /digests` into `data: Digest[]` and only ever uses
  `data?.[0]` as `latestDigest` (`digest-card-list.tsx:22`). Render the whole
  list instead: one `<section>` per digest, with the digest's `date` as the
  heading and the existing `DigestCard` grid for its topics.
- `Digest` is already typed in `frontend/lib/api.ts:45` with a `date: string`
  field — use it as the per-day heading.
- Keep the responsive grid from T0021/T0019 (`grid-cols-1 sm:grid-cols-2
  lg:grid-cols-3`); each day's grid is independent.
- The `DigestDetailSheet` (`digest-card-list.tsx:74`) is scoped to a single
  topic and is unaffected by showing multiple days; leave it as-is.
- The "Generate digest" button from T0021 is a separate task; do not build it
  here. But make sure the layout plays nicely with a future mutate/refetch of
  `GET /digests` — when the list refreshes, the whole history re-renders.
- Out of scope: the generate button (T0021), any per-source navigation, and any
  pagination/virtualization (the digest count will stay small for the demo).
