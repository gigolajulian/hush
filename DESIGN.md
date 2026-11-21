# DESIGN.md

## Direction (locked 2026-11-20; change only with Julian's yes)
- **Subject:** Hush, a tray icon that mutes Discord while I dictate to the Claude app. No windows: an icon, a tooltip, a menu and release cards.
- **Palette (60/30/10):**
  - 60% base: `#0d0e10` (icon tile, card ground)
  - 30% support: `#787a7e` grey dot while watching
  - 10% accent: `#00c8dc` cyan dot while Hush holds the mute
  - Line glyph `#e8e8e6` (holding) / `#c8c8c6` (watching), muted `#8a8d92`, faint `#55585d`.
- **Type:** Wordmark "hush." in Segoe UI / Inter 600, tight (-6 px at 168 to 190 px), full stop in cyan. Taglines and footers in Consolas / Cascadia Mono, lowercase.
- **Layout:** Glyph: a dot with a vertical line through it, drawn at 4x and downsampled; padded to 46/64 on macOS. Icon tile radius 112/512. Release cards 1280x640.
- **Motion:** None.
- **References:**
  - `assets/icon.svg`, `assets/thumbnail.html`, `assets/release-1.2.0.html`.
- **Never:** Changing the glyph shape between states. A third state color. Emoji in the menu.

## Tokens
CSS custom properties that match the direction. Mocks and the app both use these.

```css
:root{ /* hush.py and assets */
  --tile:#0d0e10; --held:#00c8dc; --watch:#787a7e;
  --glyph:#e8e8e6; --glyph-watch:#c8c8c6; --mute:#8a8d92; --faint:#55585d;
}
```

## Standing checks
One line each, checked on every mock and build:
- Tap targets at least 44 px; text contrast at least 4.5:1.
- No em dashes in any copy.
- Only the colors change between states.
- Menu labels short, sentence case.
