# R14 render sessions and layout handoff

Standalone rendering needs no Tavotto installation. One trusted local
`(script, config, scope)` triple owns one persistent session. Live page
handoff is optional and requires the corresponding updated Tavotto frontend.
Copy `examples/nmr/nmr.yaml` to a working configuration and create export
directories first; substitute a Windows path for `/tmp/work` on Windows.

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

## G2-A: explicit saved Tavotto page

```bash
python -m figpact.cli layout-snapshot \
  --layout project/tavottofile/fig2.json --base project --canvas canvas-id
```

The command prints the existing `figpact.layout/1` contract. `source_mode` is
always `saved`, never `live`. Use an exact canvas id or an unambiguous name;
a multi-canvas file requires an explicit selection, even if it contains
`activeCanvasId`. Relative asset paths resolve only against the supplied
`--base`; no autosave, ancestor-directory, or basename search is performed.

Every saved `objects[]` entry is retained in order: runtime panels, PDF and
raster panels, text, shapes, and unsupported kinds. Counts distinguish all
objects from panels. Unknown geometry stays unknown rather than becoming an
invented rectangle. Lightweight group ids and raw layout-group declarations
are recorded, not executed.

Core fields carry page-mm rectangles, crop in source-local top-left mm,
quarter-turn rotation, flips, opacity, group membership, rendering ownership,
and available resource/override revisions. Stored native dimensions are
saved-descriptor facts, not fresh render measurements. Normalized host crops
are converted only with a known native-size basis; unsupported transforms
remain explicitly unsupported.

`extensions.tavotto_saved` holds adapter evidence: exact saved-file hash,
selected canvas, counts, unaltered object records, raw group/style declarations,
resource availability and byte hashes, and unreplayed host overrides.
`runtime:` ids remain opaque capture references, not filenames. A persisted
runtime fingerprint is declared evidence, not proof that a current captured
frame exists. An existing script or a matching filename never implicitly makes
a panel figpact-managed.

The adapter neither executes scripts nor replays overrides, rewrites layouts,
resizes panels, or accepts candidates into Tavotto. Snapshot hashes change
with captured resource/override facts; read-time consistency checks do not
provide a live-page lock or a cross-application transaction.

The saved command cannot observe unsaved moves, prove a host is displaying a
frame, or report final-page QA. Active-page capture and managed-frame display
use the separate explicit handoff below; a saved snapshot never becomes live
merely because its filename contains `autosave`.

Related checks only:

```bash
python -m pytest -q tests/test_tavotto_saved.py tests/test_render_contract.py
```

The reference Fig2 saved-page smoke captured 33 objects: 31 panels
(3 runtime, 2 PDF, 26 raster) and 2 text objects, with one lightweight group.
It retained the unreplayed overrides on the adhesion panel. The saved JSON
and 33 referenced asset/script files were byte-hash unchanged after capture;
all page rectangles remain conservative saved facts, not measured glyphs.

The crop/rotation checks also cover a non-square 90-degree panel: `rect_mm`
is always the final page bounding box, so content width/height transpose
before scaling and flipping. A real NMR worker preview confirmed the same
projection at native 80 × 68 mm inside a final 68 × 80 mm panel, without
claiming Tavotto display or changing a host page.

## G2-B/C: active-page capture and managed-frame display

Start a capture-only session against the exact open project root. The origin
is the actual Tavotto page origin, not a discovered or guessed backend port:

```bash
figpact host-session --base project --host-origin http://127.0.0.1:5089
```

For one explicitly managed figure, provide all four rendering arguments:

```bash
figpact host-session --base project --host-origin http://127.0.0.1:5089 \
  --script project/managed/nmr.py --config project/managed/nmr.yaml \
  --scope main --panel-id panel-nmr
```

The command prints a loopback connection string with an ephemeral token in
the URL fragment. Paste it into the Tavotto toolbar's figpact connection
dialog. It is a local capability: do not share it or put it in a query string.
Disconnect drops it from frontend memory; it is not saved with the project.

Capture and frame display are separate explicit actions:

1. Connect the updated Tavotto frontend to that session.
2. Capture the active page. Tavotto sends its own in-memory `buildProject()`,
   document id, active canvas id and actual adopted project root.
3. Inspect the resulting `figpact.layout/1`, with `source_mode: "live"`.
   All objects remain present, including legacy runtime panels and photos.
4. Request the configured managed figure's frame. The host displays the
   actual figpact PNG and retains its same-capture Scene identity.

The managed panel must already declare ownership and the matching trusted
source/config/scope. This is a declaration in the document, not a migration
performed by G2:

```json
{
  "id": "panel-nmr",
  "renderOwner": "figpact",
  "script": "managed/nmr.py",
  "figpact": {"config": "managed/nmr.yaml", "scope": "main"},
  "overrides": []
}
```

Other normal panel fields still apply. Script and configuration paths resolve
inside the explicitly authorized project root. An old filename, a Python
script or an empty override list alone never grants figpact ownership.
Unreplayed host overrides block managed display rather than being silently
removed. Legacy runtime figures retain their existing execution path;
photos remain opaque spatial objects.

`FrameBinding` (`figpact.frame-binding/1`) binds the exact snapshot, panel,
resource, overrides, source/config and frame revisions. PNG and Scene refs
are their actual SHA-256 content identities. Native extent comes from the
captured Scene, not from a configuration value. `native_size_changed` reports
a difference from stored host dimensions; G2 does **not** resize, rebase or
save the host panel. For a crop, projection preserves its normalized
fractions against the new measured native extent.

Moving an object, switching canvas/project or changing resource/override
facts invalidates the old page binding. Late responses and stale image-load
callbacks cannot make old geometry current. Unchanged frame content may be
reused only with a fresh snapshot binding and projection. Save-status-only
updates are not page edits.

The loopback transport exposes authenticated `/session`, `/snapshot`,
`/capture`, `/frame` and `/display` routes. Browser requests require the
configured exact origin; clients also need the session Bearer token. There
are no source-write, commit, export or arbitrary-script upload routes.
`/display` records a client-reported image-load observation, not a G4
`HOST_ACCEPTED` transaction or G5 final-export proof.

`/snapshot` returns the latest explicitly handed-off snapshot and its
snapshot-bound display observation, not a continuous lock on the host page.
Recapture after editing before using its geometry as a new calculation
condition. A browser reload creates a new host instance: start a fresh
`host-session` rather than taking over a different tab's session.

The installed MCP tools alone do not expose an activity-page handoff.
A stock frontend without `FigpactBridge` cannot satisfy G2-B by reading
an autosave, and an unmodified installed binary is not upgraded by changing
the figpact Python package. Run/build the paired Tavotto frontend integration
before using these controls.

Related Python checks:

```bash
python -m pytest -q tests/test_tavotto_saved.py tests/test_frame_binding.py \
  tests/test_host_server.py tests/test_render_contract.py
```

Related Tavotto frontend checks live with its source integration:
`figpactStore.test.ts`, `figpactOwnership.test.ts`, `useEngineSync.test.ts`,
`renderScheduler.test.ts`, `renderStore.test.ts` and `panelTransform.test.ts`.

### G2 integration evidence and limits

The source Tavotto 0.18.1 frontend was built and exercised in a real Chromium
tab against an isolated copy of the reference Fig2 project. This was not a
connection to the user's installed MCP 0.18.0 or desktop window.

- The frontend handed off 33 actual objects: 31 panels (3 runtime, 2 PDF,
  26 raster) plus 2 text objects, with the group and overrides retained.
- Repeated unchanged captures kept one revision despite `buildProject()`'s
  changing read-time `updatedAt`. An unsaved photo drag changed the live
  rectangle while the explicitly saved file kept its old rectangle.
- The managed NMR image decoded in the host. Its actual DOM PNG bytes,
  Scene reference and frame revision matched the authoritative engine frame.
  Restarting the render service and reopening the frontend reproduced the
  same PNG, Scene and frame identities without source writes.
- A real `/frame` response was held while a photo was dragged. The old
  response returned successfully but did not restore a current binding;
  labeled stale pixels remained visible, and no display observation was
  posted for the old layout.
- Stored native size 41 × 46.13444575910199 mm differed from the measured
  80 × 68 mm frame. The host reported that change without changing its
  stored native size, placed rectangle or 180 × 254.4 mm page.
- A 90-degree rotation with both flips and normalized cropping displayed
  the same frame. A temporary DOM geometry probe agreed with the engine's
  projected curve rectangle within 0.0037 mm (CSS layout quantization);
  the probe was removed immediately.
- A managed panel with a retained, nonempty host override was refused,
  rather than clearing the override or showing a legacy fallback.
- All 33 referenced original asset/script files remained byte-hash unchanged.

Only related checks were run: 99 Python cases and 115 frontend cases,
with corrected failing subsets rerun after fixes, plus the frontend build
and actual UI scenarios above. No full-repository regression was run.

The isolated legacy DLS/XRD runtime figures were not executed to manufacture
fresh previews. The adhesion panel's existing execution path requested a
missing-pandas environment preparation; that request was declined, not
silently installed or treated as a successful redraw. Thus this evidence
does not certify a complete legacy-page redraw, G3 optimization, G4
acceptance, final vector resources or G5 native export.
