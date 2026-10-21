# R14 standalone render session (G0+G1 first round)

No Tavotto. One trusted local `(script, config, scope)` triple, one persistent
session, one JSON-RPC line protocol. Copy `examples/nmr/nmr.yaml` to a working
configuration and create the export directories first. `/tmp/work` below is
an example working directory; substitute a Windows path on Windows. Keep the
source script in place.

## Start a session

```bash
figpact render-session --script "examples/nmr/08 NMR.py" \
  --config /tmp/work/nmr.yaml --scope main --output-dir /tmp/work/published
```

`--script/--config/--scope` are required; `--output-dir` is the explicit
authorized artifact root for this session (the publication `commit` install
target). It is also the session default when an `export` request omits
`params.output_dir`, so passing it on the command line is an explicit
authorization, not an implicit fallback. The script path is named explicitly
on the trusted local command line -- it is never uploaded or accepted over
the wire. `stdin` takes one JSON-RPC 2.0 object per line; `stdout` carries one
JSON reply per line and nothing else (engine chatter is redirected to
`stderr`, so a stray script print can never corrupt the next reply).
`stdin` EOF -- or any startup/loop failure -- closes the session (`finally`);
there is no persistent cache beyond the one live session.

Minimal passing layout/intent for a stock NMR `main` copy (canvas-only edit;
`peak_font_pt` 7.2 alone is a science violation and is refused):

```json
{"jsonrpc": "2.0", "id": 1, "method": "open", "params": {}}
{"jsonrpc": "2.0", "id": 2, "method": "snapshot", "params": {}}
{"jsonrpc": "2.0", "id": 3, "method": "preview", "params": {
  "layout": {"schema": "figpact.layout/1", "source_mode": "standalone",
             "page_mm": [210.0, 297.0],
             "objects": [{"id": "nmr_main", "kind": "panel",
                          "measurement_status": "measured",
                          "rect_mm": [15.0, 20.0, 68.0, 68.0],
                          "resource": "nmr_trace",
                          "source": {"origin": "standalone_rpc"}}]},
  "intent": {"schema": "figpact.intent/1", "panel_id": "nmr_main",
             "edits": [{"control_id": "[\"canvas_w_mm\"]", "value": 68.0},
                       {"control_id": "[\"canvas_h_mm\"]", "value": 68.0}],
             "fit_canvas": true,
             "required_content": ["fig2_nmr.main.peak.vancho.9p83",
                                  "fig2_nmr.main.peak.hama.6p18"],
             "preserve": ["science", "view"]},
  "request_id": "rpc-test-1"}}
{"jsonrpc": "2.0", "id": 4, "method": "commit", "params": {
  "candidate_id": "<from preview>", "frame_revision": "<from preview>",
  "layout_revision": "<from preview>", "confirm": true, "kind": "draft"}}
{"jsonrpc": "2.0", "id": 5, "method": "close", "params": {}}
```

`preview` without a `revision` in the layout is accepted: the contract
validator recomputes it (`snapshot_revision`), and `commit` carries the
returned `layout_revision`. `export` needs the exact live frame:
export the active preview frame BEFORE `commit`, or `snapshot`/`open`
after `commit` and export that fresh committed frame — never reuse the
pre-commit `preview["frame_revision"]` after committing.

```json
{"jsonrpc": "2.0", "id": 6, "method": "export", "params": {
  "output_dir": "/tmp/work/bundle", "frame_revision": "<from preview>"}}
```
(before commit), or re-read `snapshot` after commit and export the frame it
returns.

Wire shapes (`docs/schema/render.schema.json`, `$defs` LayoutSnapshot /
EditIntent / Receipt): layout pages are `page_top_left` mm; scene sources are
`canvas_bottom_left` mm (projection converts explicitly); `preserve` is
exactly `["science", "view"]`; `crop` rects are local mm, top-left, relative
to the owning object (not page coordinates).

## Method shapes

- `open()` -> `{status:"open", frame, controls, source, revision, scope}`.
  `frame` is the worker Inspector frame verbatim (no `native` key leaked).
  `controls` are `{control_id, path, label, unit, current, min, max, objects}`.
- `snapshot()` -> same plus `pending` (`None` or `{candidate_id,
  frame_revision, layout_revision, request_id, epoch, candidate_revision,
  source_revision, base_config_revision, generation}`).
- `preview(layout, intent, request_id)` -> `{status:"OK", candidate_id, frame,
  frame_revision, layout_revision, request_id, epoch, generation, receipt,
  projection, precheck, required_content:{checked,missing}, fonts, warnings,
  limits, evidence}`. `receipt` is the Native `try_layout` receipt plus
  candidate/source/layout bindings. `evidence` is
  `{render, persistence:"NOT_WRITTEN", host:"NOT_CONNECTED",
  export_page:"NOT_RUN"}`. `preview` never writes.
- `cancel(candidate_id=None)` -> `{status:"cancelled", frame, controls,
  cancelled}`. `None` cancels the active pending; unknown ids raise
  `CANDIDATE_UNKNOWN`. No writes.
- `commit(candidate_id, frame_revision, layout_revision, confirm,
  kind="draft")` -> `{status:"committed", kind, verification, frame, receipt,
  controls, evidence}`. `evidence` is
  `{render, persistence:"WRITTEN", host:"NOT_CONNECTED",
  export_page:"NOT_RUN"}`; if post-commit refresh failed, `render` is
  `NOT_RUN`, `frame` is `null`, the receipt still reports the on-disk
  `WRITTEN` fact honestly, and later reads/edits/exports raise
  `REFRESH_REQUIRED` until the session is reopened. `confirm` must be exactly
  `True` (both kinds) or the call raises `CONFIRM_REQUIRED` with zero writes.
  `draft` writes the YAML through the existing comment-preserving gate;
  `publication` runs the existing strict path. Late failures that leave the
  on-disk outcome unknown raise -- they never return a fake success; the
  saved-but-refresh-failed case above is the only honest `WRITTEN` receipt.
- `export(output_dir, frame_revision, candidate_id=None)` ->
  `{status:"exported", bundle, evidence}`. `bundle` is the worker immutable
  bundle verbatim (`bundle_dir/png_path/pdf_path/sha256/page_mm`, ...).
  Exact-revision only: stale, superseded, cancelled, or drifted frames are
  refused (`EXPORT_STALE` / `STALE_REVISION`), and an existing bundle is
  never overwritten. The PNG bytes are the original captured frame; the PDF
  is a separate-backend product of the same candidate, re-checked for
  geometry/science drift. `evidence` keeps the four discrete dimensions
  (`render/persistence/host/export_page`); `host` stays `NOT_CONNECTED` and
  the export-page slot stays `NOT_RUN` in this round -- there is no host
  acceptance claim.
- `close()` -> `{status:"closed", already_closed}`.

Engine error replies are `{code, message, data:{status, ...}}`; match on
`data.status`: `INVALID / UNKNOWN_ID / OUT_OF_RANGE / UNSUPPORTED_GEOMETRY /
STALE_REVISION / REFRESH_REQUIRED / CANDIDATE_UNKNOWN / SUPERSEDED /
CANCELLED / CONFIRM_REQUIRED / NATIVE_REJECTED / COMMIT_REJECTED /
SCIENCE_VIOLATION / QA_BLOCKED / REQUIRED_CONTENT_MISSING / FIT_UNAVAILABLE /
FIT_CONFLICT / CROP_FIT_UNSUPPORTED / EXPORT_STALE / SESSION_CLOSED /
INTERNAL_ERROR`. Unexpected startup/engine failures use JSON-RPC `-32603`
and `data.status:"INTERNAL_ERROR"`; the message retains the original cause.
Protocol-level parse/request/parameter errors may omit `data`; match their
standard JSON-RPC numeric code instead. Numeric codes group conflicts:
`REFRESH_REQUIRED` maps to `STALE_REVISION`.

The only edit controls supported are the scalar Native controls actually
returned by `open()` for this script/scope. For example, NMR exposes
`canvas_w_mm`, `canvas_h_mm`, authorized typography (`axis_font_pt`,
`tick_font_pt`, `peak_font_pt`, `legend_font_pt`, `note_font_pt`), line width,
and declared spacing/placement parameters; FTIR exposes its own authorized
canvas, label/legend typography, and spacing controls. This is not a fixed
cross-figure catalog: the returned control list is authoritative. Edit `role`
is optional annotation, not authorization or a separate role registry.
`fonts` reports measurable scene text envelopes with captured renderer artist
facts (`get_fontsize` `font_size_pt` preserved by the Inspector into the
scene). A size is reported only when the capture actually carries it; a text
node without a captured size is `FONT_SIZE_UNAVAILABLE`, never inferred from
an authorized control value. Uniform page scaling composes to an effective pt
(`source_pt × scale`); anisotropic or unknown scaling stays unknown — no
guessed per-role numbers, and a reported envelope never implies that text
item has an editable font control.

Numeric `fit_canvas:true` uses both target width AND height through the
authorized `canvas_w_mm`/`canvas_h_mm` controls (local content swaps 90/270;
cropped objects need a supported mapping or an explicit refusal, never silent
page-mm matching).

## Python use

```python
from figpact.render_api import RenderSession
with RenderSession("examples/nmr/08 NMR.py", "/tmp/work/nmr.yaml", "main",
                   output_dir="/tmp/work/published") as session:
    _ = session.snapshot()              # frame + authorized controls
    preview = session.preview(layout, intent, "req-1")
    pre_commit = session.export("/tmp/work/bundle", preview["frame_revision"])
    record = session.commit(preview["candidate_id"], preview["frame_revision"],
                            preview["layout_revision"], True, kind="draft")
    fresh = session.snapshot()          # committed baseline frame
    post_commit = session.export("/tmp/work/bundle2", fresh["frame"]["frame_revision"])
```

`open()` and `snapshot()` return the same frame/controls view (`snapshot`
adds `pending`); the context manager only manages lifetime.
`--output-dir` authorizes the session's publication artifact root (the
`commit` install target). When an `export` request omits `params.output_dir`,
that explicit CLI value is the authorized default export destination —
not an implicit source-dir fallback (the source/script directory is never
an export target).

## Evidence notes

- Same frame: `preview` PNG and the Scene in the same `frame` are one worker
  capture (single draw). Separate PDF: `export` adds a second-backend PDF
  for the same candidate; it is not claimed pixel-identical to the PNG.
- Freshness: any source/config drift, supersede, or cancel invalidates the
  pending candidate; `commit`/`export` then refuse rather than guess.
- PDF evidence is page-box only: the worker checks Agg Figure state/science
  before and after emitting the PDF, and measures the emitted PDF page box
  (optional `pypdf` dependency; without it, export reports the missing
  capability instead of inventing a size). It is not PDF glyph-geometry
  equivalence and not a final-page QA pass.
- Renderer metadata (actual known software stack) rides with the worker
  bundle; it is not a full font-reproduction claim.
- Same-frame/second-backend export evidence versus the same-capture PNG+Scene
  distinction above is the whole page story in this round.

## Tests

```bash
python -m pytest tests/test_render_rpc.py -q
```

Real subprocess journeys on NMR/FTIR YAML copies: full
open->preview->commit(draft, `confirm:true`)->close plus fresh-reopen replay;
same-frame export immutability and stale refusal; FTIR snapshot; malformed
line / unknown method / `CANDIDATE_UNKNOWN` / `CONFIRM_REQUIRED` zero-write
(each failure asserted on status + untouched bytes, never on wording).
