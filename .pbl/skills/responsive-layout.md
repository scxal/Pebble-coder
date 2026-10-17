---
name: responsive-layout
description: Make a layout responsive and robust from phone to desktop
---

1. Mobile-first: base CSS for the smallest screen, then add min-width media queries.
2. Lay out with flexbox or CSS grid; avoid fixed pixel widths on containers.
3. Use relative units (rem, %, clamp) for type and spacing; cap content width.
4. Keep the viewport meta tag: <meta name="viewport" content="width=device-width, initial-scale=1">.
5. Verify by narrowing the window: nothing overflows horizontally at any width.
