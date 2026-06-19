---
id: T0028
title: Remove topic images and guard image selection
status: done
dependencies: []
---

# Scope

- Remove the topic image from the frontend digest card and detail sheet.
- Guard the backend LLM image-selection step behind a feature flag that is always false, keeping the existing code intact in case we revisit it later.

# Acceptance

- Digest cards no longer render an image or image placeholder at the top.
- The digest detail sheet no longer renders a topic image.
- The backend pipeline still type-checks and runs without calling the LLM to pick images.
- `DigestTopic.image` and the image-selection modules remain in the codebase; they are simply skipped by default.
- The project builds, passes lint, and all tests pass.

# Implementation Notes

- Frontend image rendering lives in two components:
  - `frontend/components/digest-card.tsx` line 49 renders `<TopicImage>`; lines 72–100 define the component and import `next/image`.
  - `frontend/components/digest-detail-sheet.tsx` lines 61–71 render the detail-sheet image and import `next/image`.
  Remove both usages and their helpers/imports. Do not remove the `DigestTopic.image` type field in `frontend/lib/api.ts`; the API may still return `null`.
- Backend image selection is wired in `backend/app/pipeline/digest.py` lines 113–114:
  ```python
  candidates = gather_candidates(topic, emails_by_id)
  image = select_image(topic, candidates, client=client)
  ```
  Introduce a module-level constant such as `_SELECT_TOPIC_IMAGES = False` and skip both calls when it is false, always setting `image=None`. Keep `gather_candidates`, `select_image`, and `backend/app/pipeline/image.py` unchanged so the code can be re-enabled later.
- `backend/tests/pipeline/test_digest.py` currently expects `select_image` to be called and to assign images; update the test assertions (or the flag) so they pass with image selection disabled.
