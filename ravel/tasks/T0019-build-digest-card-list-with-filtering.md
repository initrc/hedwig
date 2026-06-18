---
id: T0019
title: Build digest card list with filtering
status: new
dependencies:
  - T0018
---

# Scope

- Display the most recent digests as a grid of cards.
- Each card shows: topic label, summary snippet, source badge, and the LLM-selected image (if any).
- Add a filter bar by category/topic label so users can narrow the list.
- Fetch data from `GET /digests` on mount and refresh after a new digest is generated.

# Acceptance

- The dashboard page renders cards for each topic in the latest digest.
- Cards are filterable by topic label; the filter updates the list without a page reload.
- Images are rendered with `next/image` and handle the "no image" case gracefully.
- Clicking a card opens the detail Sheet (T0020) and passes the topic `label` to it — the Sheet uses this label as `topic_label` for the scoped chat.
- The page builds and passes `pnpm run lint`.

# Implementation Notes

- Use the shadcn `Card` component for the card shell.
- Use `Badge` for the source label.
- Use `Input` for the filter text.
- The digest schema from the backend is `Digest` with `topics: [{label, summary, sources[], image}]`.
- Keep the component flat for now; extract shared UI later if needed.
