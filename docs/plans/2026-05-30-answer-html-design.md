# answer.html — browser-native answer view with hover preview

## Goal

Each `groundling render` run already produces `answer.md` (markdown with
cite links) and `cites/N.html` (per-cite PDF page with bbox highlight).
Add a third output, `answer.html`, that renders the answer for reading
in a browser:

- Cite link spans are visually highlighted (soft yellow background).
- **Hover** any cite → floating popover shows a true-resolution crop
  of the source PDF centred on the cited bbox, with the highlight
  overlay.
- **Click** any cite → opens `cites/N.html` in a fixed side pane on
  the right (iframe). Escape or close button dismisses.
- **Mobile / no-hover devices** → cite spans are plain links; click
  navigates to `cites/N.html` as a full page. No popover, no pane.

## Non-goals

- Not replacing `answer.md`. Markdown stays for piping, indexing,
  diffs, and AGENTS.md workflows.
- Not regenerating cite pages or PDF page images. `answer.html`
  reuses the existing `cites/N.html` and `cites/N.png` files.
- Not building a full reading app — no search, no annotations, no
  cross-document navigation beyond what cite pages already provide.

## File shape

```
qa-runs/<run-id>/
├── answer.md            (existing)
├── answer.html          (new — sibling to answer.md, self-contained)
├── manifest.json        (existing)
└── cites/
    ├── 1.html, 1.png    (reused unchanged for iframe + hover background)
    └── …
```

Cite link hrefs in `answer.html` use the same `--web-base` already
passed to `render`. The iframe inherits those URLs.

## Architecture

One new helper module, one new template, one new dependency.

```
src/groundling/answer_html.py
    build_answer_html(answer_md, cite_records, run_dir, web_base) -> str

src/groundling/templates/answer.html.j2
    page shell: <head> styles + <body> shell + JS + side-pane aside

pyproject.toml
    +markdown-it-py
```

Integration: in `run_render`, after `answer.md` is written, call
`build_answer_html(...)` with the same data already in scope and write
the result to `run_dir / "answer.html"`.

## Data flow inside build_answer_html

1. Parse `answer_md` with `markdown-it-py` → HTML.
2. Walk the HTML for `<a href>` whose href matches the run's cite URL
   pattern (`<web_base>/<run_dir.name>/cites/N.html` or the file://
   equivalent). Capture the cite_id from the URL.
3. For each matched anchor, look up the corresponding `cite_record`,
   compute the **union bbox** across all its spans (in image pixels,
   already-scaled), and inject:
   - `class="cite"`
   - `data-cite-id`, `data-kind` ("pdf" or "web")
   - For PDF cites: `data-img` (relative path to N.png),
     `data-img-w`, `data-img-h`, `data-bx`, `data-by`,
     `data-bw`, `data-bh`
   - A child `<span class="preview"></span>` (empty; CSS draws it)
4. Render the page template (Jinja) wrapping the decorated answer
   HTML in the styles + body shell + JS + side-pane aside.

Point markers (`[N]` reference style) and wrap markers (inline
`[claim](url "quote")`) converge at this step — by the time render
hands off, both have produced `<a href="…/cites/N.html">` anchors.
One transform decorates both. The visible difference is only the
link text.

## Hover preview — pure CSS

Each cite anchor carries the page image as a CSS custom property and
the bbox geometry as data attributes. A child `<span class="preview">`
is hidden by default and shown on `.cite:hover .preview`. The
preview is a fixed-size viewport (~480×280 px) whose background-image
is the cite's full-page PNG, positioned so the bbox centre sits at
the viewport centre. A `::after` pseudo-element draws the same yellow
highlight overlay at the viewport centre.

Result: the source PDF region appears at true PDF resolution (the
2x-rendered PNG, uncropped, just positioned and clipped). No new
image generation.

Bbox at page edge → preview still works; page edge appears inside the
viewport. Multi-span cite → union bbox is precomputed in step 3.
Web cite → no PDF preview; the popover shows the cited quote text in
a styled card via `data-kind="web"` selector.

## Click → side pane — minimal JS (~20 lines)

```
.cite click handler:
  if !matchMedia('(hover: hover)').matches: return  // mobile fall-through
  preventDefault
  iframe.src = a.href
  pane.hidden = false; body.classList.add('pane-open')

close button click: pane.hidden = true; iframe.src = 'about:blank'
Escape key: close
```

Layout: `body.pane-open main.answer` shrinks to 60% width, `aside.cite-pane`
becomes a fixed 40%-wide column with the iframe filling it. Smooth
transition. The iframe loads the existing `cites/N.html` whose own
prev/next nav lets the user browse cites without disturbing the answer
text on the left.

## Mobile / accessibility

- `@media (hover: none)` → cite previews disabled, side pane disabled,
  links navigate normally.
- All cite anchors keep their `href`. Keyboard-tabbable. Screen
  readers see anchor + link text.
- Side pane is `<aside>` with a labelled close button.
- Escape closes the pane.

## Tests

In `tests/test_answer_html.py`:

1. Wrap-cite answer → one `<a class="cite">` with expected
   `data-bbox` (union, image pixels), `data-img`, `data-img-w/h`,
   `data-kind="pdf"`.
2. Point-marker `[N]` reference answer → same decoration after
   normalisation.
3. Web cite → `data-kind="web"`, no PDF image attrs.
4. Multi-span cite → `data-bbox` reflects the union of all span
   bboxes, not the first one.
5. End-to-end: render a 2-cite answer, assert `answer.html` exists,
   contains the iframe `<aside>`, contains both cites decorated.
6. Mobile regression guard: regex-assert that `(hover: hover)` and
   `.pane-open` appear in the emitted HTML so the fall-through can't
   silently break.

## Rollout

Ship in the existing `experiment/wrapping-cites` worktree as a
follow-up commit. AGENTS.md gets one short note: "for browser
viewing, point at `answer.html` from `groundling serve`."

No CLI flag — the file is always produced.

## Out of scope (file as follow-ups if needed)

- Inline PDF embedding (`<embed>` of the PDF, scrolled to the cite
  region) instead of an image crop. Worth considering when we hit
  zoom/resolution limits.
- Multi-document split view (one iframe per cite source
  side-by-side).
- Print stylesheet — answer.html as PDF-via-print.
- Dark mode.
