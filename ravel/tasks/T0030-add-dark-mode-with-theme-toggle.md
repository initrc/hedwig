---
id: T0030
title: Add dark mode with theme toggle
status: done
dependencies: []
---

# Scope

- Wire up dark mode so the app respects the user's OS-level color scheme
  preference by default.
- Add a theme toggle button in the top-right of the page so the user can
  override the system setting to light or dark.

# Acceptance

- The app renders in dark mode when the OS is set to dark, and light mode when
  the OS is set to light (no manual intervention).
- A theme toggle button sits in the top-right corner, aligned with the "Hedwig"
  heading. Clicking it flips between light and dark.
- The toggle icon animates: the sun spins out as the moon spins in, and vice
  versa.
- The app builds and TypeScript compiles with no errors.

# Implementation Notes

- Installed `next-themes` for its `ThemeProvider` and `useTheme` hook. The
  `ThemeProvider` uses `attribute="class"` so it toggles the `dark` class on
  `<html>`, which is what Tailwind's `@custom-variant dark (&:is(.dark *))` and
  the existing `.dark {}` CSS block in `globals.css` expect.
- `frontend/components/theme-provider.tsx` is a thin `"use client"` wrapper
  around `next-themes`'s `ThemeProvider`. The file exists only because
  `ThemeProvider` uses React context and cannot be imported directly into the
  server-component `layout.tsx`. Without this client-component boundary the
  import would fail.
- `frontend/app/layout.tsx` imports `ThemeProvider` and wraps `{children}`
  inside `<body>`. It also adds `suppressHydrationWarning` to `<html>` to
  prevent React from complaining about the `dark` class that `next-themes`
  injects via a pre-hydration script.
- `frontend/components/theme-toggle.tsx` is a ghost-style icon button that calls
  `setTheme` to flip between light and dark. It uses `resolvedTheme` (not
  `theme`) because `theme` may be `"system"` — toggling from `"system"` doesn't
  make sense; you toggle from the actual effective theme.
- The sun and moon icons from `lucide-react` are stacked with `absolute`
  positioning. CSS transitions on `rotate` and `scale` make them morph into each
  other when the `dark` class changes.
