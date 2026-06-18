---
id: T0021
title: Add generate digest button and finalize dashboard
status: new
dependencies:
  - T0020
---

# Scope

- Add a prominent "Generate digest" button at the top of the dashboard.
- Clicking it calls `POST /digest/run` and shows a loading state.
- On success, refresh the card list to display the newly generated digest.
- On error, show a simple inline error message.
- Polish the layout: consistent spacing, empty state when no digests exist, and responsive grid.

# Acceptance

- The button triggers digest generation and disables itself while loading.
- After a successful run, the card list updates to show the new digest.
- Errors are surfaced in the UI without crashing the page.
- The layout is responsive and readable on mobile and desktop.
- `pnpm build` and lint pass.

# Implementation Notes

- Use shadcn `Button` with a loading state (e.g., disabled + spinner).
- The `POST /digest/run` endpoint returns `list[Digest]` (one per day, per
  T0026) — a single run can produce several digests, so do not treat the
  response as one `Digest`. The simplest correct behavior is to refetch
  `GET /digests` on success and let the list re-render, rather than reasoning
  about which element of the returned list to show.
- Add an empty-state message: "No digests yet. Generate one to get started."
- Keep the grid responsive with Tailwind: `grid-cols-1 md:grid-cols-2 lg:grid-cols-3`.
