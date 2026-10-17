---
name: accessible-ui
description: Accessibility checklist to run over any UI before shipping it
---

1. Prefer semantic HTML: header/nav/main/footer, <button> for actions, <a> for links.
2. Every image gets alt text (alt="" only for purely decorative images).
3. Tie labels to inputs (label for= / id); keep a visible or aria-label.
4. Keyboard: all controls reachable with Tab, visible :focus-visible styles, logical order.
5. Check contrast (text >= 4.5:1) and never convey meaning by color alone.
