VERDICT: PASS

## Findings
None.

## Notes
- The history list fits the page. It sits under `#result` with a 12px top margin, no bullets, no padding, and inherits the body font (16px/24px system-ui) and line height. Entries read as plain secondary text beneath the bold result line, which matches the spec.
- Colour `#666` on the white background is a new hard-coded value, since the page's only other colour is `#222`. Contrast is about 5.7:1, which passes WCAG AA for normal text. Leave it as is, or use `#222` if you want the page to stay on one text colour. This is taste, not a blocker.
- Checked at 1280px and 375px with six submits. The list shows five entries, newest first. `scrollWidth` equals the viewport width (375px), so nothing overflows on a phone.
- The form already wraps awkwardly at 420px on desktop, with the `=` button on its own line. This is existing behaviour and is outside this change.
