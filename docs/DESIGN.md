# Eye View desk design (theme v1, 26 Nov 2026)

All desk pages share one look: a deep-teal masthead with the Eye View mark and links to the other pages, a sticky bar of section links, white paper (night #0d1416), Libre Franklin type, fine rules and figures in ruled strips.

Theme CSS: `analyses/design/desk_theme.css`. Masthead, section bar and its script: `analyses/design/parts.py`. The `build_*.py` scripts show how each page was assembled from its live version.

## Colour tokens

| Token | Light | Night | Use |
|---|---|---|---|
| `--bg` / `--p1` | #ffffff | #0d1416 / #121b1e | page / cards |
| `--p2` | #f1f4f4 | #182428 | quiet fills, buttons |
| `--lead` | #e7f1f1 | #10292c | the one highlighted card (latest read) |
| `--line` / `--l2` | #d9dfe1 / #e9edee | #25363a / #1b2a2e | rules |
| `--tx` / `--dim` / `--d2` | #14181b / #4f5a61 / #6b767d | #e8eff0 / #a3b3b7 / #82959a | text |
| `--band` | #0b3b41 | #08262a | masthead |
| `--vio` (desk teal) | #0d7680 | #4fc3c9 | the desk's own marks, selected states |
| `--red` / `--grn` / `--amb` / `--blu` | #b3123f / #16794a / #9a5b00 / #2a5db0 | #ff6f8e / #4cc38a / #f0b429 / #7fa9ff | down-miss / up-hit / flags / neutral series |

Token names are the old ones, so existing render code and `css('--vio')` calls keep working. Every token has a `*bg` tint (`--viobg`, `--redbg`, `--grnbg`, `--ambbg`).

## Adding a section

```html
<section class="sec" id="my-thing" data-nav="Short name">
  <header class="sec-h"><h2>Heading that says what it shows</h2><p class="sec-n">One-line question it answers</p></header>
  <div class="tiles" id="mytiles">
    <div class="tile"><div class="k">Label</div><div class="v">–</div><div class="s">sub line</div></div>
    ×4 (a multiple of 2; four is best)
  </div>
  <div class="card">
    <div id="myflags"></div>                         flags: <div class="flag">text</div>
    <div class="tw"><table id="mytab"></table></div> every table inside .tw
    <p class="note" id="mynote"></p>                 sources, gaps, "context only"
  </div>
</section>
```

- `data-nav` puts the section in the sticky bar automatically. Section ids: letters, digits, hyphens; never the same as an element id.
- Sentence case everywhere; no uppercase labels. Smallest text 13px.
- Colours only through tokens. Up = `class="up"`, down = `dn`, extreme = `am`, quiet = `mut`.
- Charts: size from the container (`cw(id)` in Desk Daily) and use `font-size="12"`; they redraw on resize and theme change.
- A second card in a section gets `<h3 style="margin-top:0">`.
- Every page keeps "Not investment advice" in its footer.
