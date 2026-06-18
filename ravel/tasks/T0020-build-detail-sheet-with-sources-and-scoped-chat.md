---
id: T0020
title: Build detail Sheet with sources and scoped chat
status: done
dependencies:
  - T0019
---

# Scope

- On card click, open a shadcn `Sheet` showing the full topic summary.
- Inside the Sheet: list all source citations with "view original" links, and the selected image.
- At the bottom of the Sheet, add a small chat input wired to `POST /chat?topic_label=<label>`.
- The chat stays scoped to the current topic's sources. Pass the topic `label` as the `topic_label` query parameter. If no `topic_label` is specified, the chat is global (searches across all digests).

# Acceptance

- Clicking a card opens the Sheet with correct topic data.
- The Sheet displays the full summary, every source with its URL, and the image.
- Typing a question in the chat input sends it to `POST /chat?topic_label=<label>` and renders the answer.
- The Sheet closes on outside click or explicit close button.
- Builds and lints cleanly.

# Implementation Notes

- Use shadcn `Sheet` for the slide-out panel.
- The chat is a small local component: an input, a submit button, and a scrollable message area.
- `topic_label` for the chat query is the topic `label` string. The backend's `ask()` function uses `where={"topic_label": topic_label}` to scope the Chroma search. The frontend should pass the exact `topic.label` string from the digest data.
- Use React state to hold the messages for the current Sheet session; no need to persist them.
