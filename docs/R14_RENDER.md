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

## G3-A/B: snapshot-bound capability and fixed-layout reports

G2 is frozen at core `50f2ad0` paired with Tavotto fork `fd019239`
(`feat/figpact-g2-live-handoff`). This stage adds read-only reports, not a
solver. The `LayoutSnapshot` and `FrameBinding` contracts are unchanged.
Same-capture Scene nodes gain optional `semantic` facts: canonical role,
X/Y axis, axes identity and structural `root`/child-`inset` ownership.
An arbitrary `add_axes` overlay is not guessed to be a scientific main plot.
Unregistered inset labels remain measurable but do not acquire edit authority.

```bash
figpact layout-snapshot --layout /project/layout.json --base /project --canvas page
# Use the exact revision returned above; a changed revision is refused.
figpact layout-report --layout /project/layout.json --base /project --canvas page \
  --expected-revision <snapshot-revision> --target nmr --target ftir
```

Without `--managed`, targets retain their actual page rectangles and neighbour
constraints but are `SPACE_ONLY`; no runtime script is executed. To measure a
supported, already figpact-managed figure, explicitly authorize it as well:

```bash
figpact layout-report --layout /project/layout.json --base /project --canvas page \
  --expected-revision <snapshot-revision> --target nmr \
  --managed nmr /project/nmr/plot.py /project/nmr/config.yaml main
```

All four managed arguments must agree with the captured host record. The
adapter verifies explicit ownership, project-root-contained script/config,
scope and absence of unreplayed overrides before any script starts. It does
not migrate old Tavotto runtime figures or clear their overrides. Scripts are
trusted executable local code: a path found in a layout alone is not execution
authorization. Sessions are closed and temporary work removed on command exit.

`--snapshot <file>` instead of `--layout` accepts an explicitly handed-off
`figpact.layout/1` JSON, including a live G2 capture. It is still only that
capture, not a subscription to the active page; `--canvas` applies only to
`--layout`. Standalone managed objects declare exact `source.script`,
`source.config` and `source.scope`, with no external override state.

### Report facts and permissions

- `figpact/role_report.py`: `capability_report(frame, controls, projection,
  editable=False)` reads captured artist sizes and exact semantic ownership.
  Role discovery never parses GIDs, text labels or parameter-name regexes.
  Font-control authorization uses existing canonical role policy plus exact
  Native path, object membership and Scene control bindings. Custom properties
  without an explicit supported policy stay unbound, not guessed from `pt`.
- `font_controls[].editable` is per measured role. Hidden, unregistered,
  readonly or anisotropically scaled roles cannot become automatic font
  targets. Shared controls list all affected IDs, role/axis/axes groups and
  unmatched members; two labels sharing one parameter are not independently
  editable. Generic text/Annotation remains unclassified measurement-only.
- `figpact/spatial_report.py`: `spatial_report(layout, target_ids, observations,
  regions=(), required_content=None)` reuses G2 page projection and conservative
  prechecks. Fixed neighbours and targets are never moved. Known envelope
  clipping/outside-page and absent required identities are separate from
  potential neighbour overlap and unknown measurements. An envelope is not an
  exact-ink silhouette; an unknown required label is `UNSUPPORTED`, not proved
  lost and never a QA pass.
- `figpact/layout_report.py`: `report_layout()` combines independent, existing
  `RenderSession` snapshots using adapter-confirmed `source_bindings`. It
  requires `expected_revision`, validates frame/source/config/scope bindings,
  refuses pending candidates, and rechecks all measured source/frame identities
  after collection. Optional `refresh_layout` re-reads the same page producer
  before/after. This API imports no Tavotto host implementation.

To declare an allocated row/column region and confirmed content IDs, pass a
`--constraints` JSON containing only `regions` and/or `required_content`:

```json
{
  "regions": [{
    "id": "spectra",
    "member_ids": ["nmr", "ftir"],
    "axis": "x",
    "region_mm": [10, 20, 126, 50],
    "gap_mm": 2
  }],
  "required_content": {"nmr": ["fig2_nmr.main.xlabel"]}
}
```

Regions and row/column membership are explicit user/host allocation, not
inferred universal layout rules. The engine derives `available_mm` from the
region, `occupied_mm` from current final member widths/heights plus declared
gaps, and `current_span_mm` from actual member coordinates. These are different
facts when current gaps differ from the declared row policy. `excess_mm > 0`
is current budget information, not proof that internal changes cannot help.
Hidden members are rejected; unknown geometry yields an unknown budget.

The combined report is `figpact.layout-report/1`:

- `READY`: measured report available, **not** a feasible candidate, saved result
  or final-page PASS.
- `UNSUPPORTED`: some requested capabilities/measurements are unavailable;
  known geometry and its limits remain in the report.
- `CONSTRAINT_VIOLATION`: a known geometric/content criterion fails.
- `STALE`: requested snapshot/source/frame no longer matches; no retry quietly
  accepts a different page.

CLI exits are 0 for READY, 1 for a completed unsupported/violating report, and 2
for refused/invalid/stale inputs. Evidence remains `SNAPSHOT_BOUND`,
`persistence: NOT_WRITTEN`, `page: NOT_CHANGED`, `host: NOT_VERIFIED`,
`export_page: NOT_RUN`. Reading a saved file twice, or fetching cached
`host-session /snapshot` twice, cannot turn it into an active-page lock.
No continuous live-report UI/transport, font search, page adjustment,
multi-figure save transaction or final export is added here.

### G3-A/B exercised evidence

- The actual reference saved page produced 33 objects / 31 panels. All three
  legacy runtime targets remained SPACE_ONLY; each retained all 32 neighbour
  records. Old DLS/XRD/NMR runtime code was not executed to invent capability.
- The actual public CLI independently rendered the supported NMR and FTIR
  scripts with different uniform page scales. Both science fingerprints were
  verified; measured title sizes were:

  | Figure | Captured source pt | Final page pt |
  | --- | ---: | ---: |
  | NMR | 8.5 | 4.25 |
  | FTIR | 8.5 | 6.375 |

  Both reports exposed X/Y control coupling. The original G3-A/B report marked
  `fig2_nmr.main.tick.3` as clipped. G3-C's native-draw audit subsequently
  identified that finding as a **measurement false positive**: Matplotlib
  retained a visible-flagged 15 ppm tick outside the 10.5–0 ppm display window,
  but never drew it. The capture correction below supersedes that finding.
- The derived budget regression checks 134.7 mm against 126 mm and reports
  8.7 mm current excess without declaring global infeasibility. Other checks
  cover actual child-inset labels, anisotropic scalar refusal, readonly
  references, fixed-neighbour drift, missing versus unmeasured required
  content, zero-extent baselines and source/config drift.
- Related checks covered 95 distinct passed cases, one skipped case and two
  passed subtests; the final-source rerun covered 53 cases including every new
  G3 test. No full-repository regression or frontend build was run.
- Original scripts/configs/page and all 33 original referenced asset/script
  files remained byte-hash unchanged during the CLI scenarios. This is
  saved-page and standalone rendering evidence, not a new active Tavotto
  display/acceptance or whole-page export proof.

## G3-C: bounded common-effective-font search

`figpact layout-search` searches one semantic font group across two or more
explicitly managed figures. It uses existing hot `RenderSession` workers,
G3-A role/control bindings, G2 placed-rectangle projection and G3-B conservative
space checks. It does not use the old width-only fitter or move page objects.

```bash
figpact layout-search --snapshot /work/page.snapshot.json --base /work \
  --expected-revision <snapshot-revision> --target nmr --target ftir \
  --managed nmr /work/nmr/plot.py /work/nmr/config.yaml main \
  --managed ftir /work/ftir/plot.py /work/ftir/config.yaml main \
  --intent /work/font-intent.json
```

The page/source authorization rules are the same as `layout-report`. Every
target needs an explicit trusted script/config/scope matching the host record.
The intent may also be supplied as inline JSON:

```json
{
  "schema": "figpact.font-search/1",
  "role": "axis.title",
  "axis": "x",
  "axes_context": "root",
  "candidate_pt": [10, 9, 8.5, 8],
  "tolerance_pt": 0.02,
  "max_renders": 16,
  "allow_coupled": true,
  "variants": [{}],
  "required_content": {
    "nmr": ["fig2_nmr.main.peak.vancho.9p83", "fig2_nmr.main.peak.hama.6p18"]
  }
}
```

`candidate_pt` is an explicit, positive, unique finite grid, searched in
descending order; no binary search or monotonic-layout assumption is used.
Supported roles are `axis.title`, `axis.tick` and `legend` when genuine
bindings exist. Axis is `x`, `y` or null (both); context is structural `root`
or child `inset`, never guessed from GID text. A single group's members must
share an unambiguous authorized font control within each figure.

`allow_coupled` defaults false. The example explicitly permits the shared
X/Y title parameter to affect the Y label too; affected IDs and role groups
are reported. The engine protects the selected and visible coupled labels
in addition to the confirmed `required_content` IDs. It never hides required
content to obtain a candidate.

`variants` lists optional finite alternatives, each mapping a panel ID to
Native scalar edits. For example, a discrete alternative can include
`{"nmr":[{"control_id":"[\"legend_cols\"]","value":2}]}`. Numeric types and
declared ranges are preserved; unknown/locked controls and duplicate edits
are refused. Variants cannot override the automatic font control. Defaults
are one empty alternative, tolerance 0.02 pt and 24 preview calls. Hard caps
are 128 grid points, 64 alternatives and 512 preview calls.

### What is actually verified

- Each attempt is an absolute Native preview from the accepted baseline,
  not accumulated edits from a previous candidate. Extra edits may change
  native canvas extent; the engine measures the resulting frame and corrects
  the font proposal from its actual projection. It never substitutes a
  config width for measured native extent.
- Effective size is remeasured after drawing. Nonuniform/unknown scaling,
  unavailable bindings, disappearing selected members or changed scientific
  payload cannot be accepted. Explicit scientific/view protections remain
  enforced by the Native engine.
- Every target is checked against fixed page neighbours, including other
  target panels. Known clipping/outside-page, required-content failures and
  relevant conservative envelope conflicts block a candidate. Broad canvas
  rectangle overlap and current budget excess alone do not establish
  infeasibility. Initial conflicts are not assumed irreparable.
- Preview-call budget includes **failed calls**, intermediate measurements
  and winning replay; it is not a claim about internal Matplotlib draw count.
  Source checks native to each preview are retained, with all-session checks
  at batch boundaries and after replay rather than redundant checks before
  every draw.
- The winner is rebuilt on every session, remeasured and frame-hash compared
  with its trial. Final page/source/pending-ID checks reject stale results.
  Failure cancels only the search's own pending candidates; unrelated
  candidates are never cancelled. Callers must give the API exclusive use
  of its sessions; this is not a G4 lease or multi-figure transaction.

`search_common_font(layout, sessions, intent, expected_revision=...,
source_bindings=..., refresh_layout=...)` returns
`figpact.font-search-result/1`. Outcomes are `FEASIBLE`, `NO_CANDIDATE`,
`UNSUPPORTED`, `STALE` or `CONSTRAINT_VIOLATION`; invalid input is refused.
Attempts include the checked point/alternative and failure bottlenecks.
`NO_CANDIDATE` describes the checked finite search, not mathematical global
infeasibility. Unexpected renderer failures are not reclassified as ordinary
layout failures.

For the Python API, a successful result leaves only the replayed winner
pending in each caller-owned session, with current IDs, captured frames,
projected geometry, actual fonts and absolute edits. Nothing is saved.
The CLI closes its sessions: its returned `active_candidates` is false,
`lifetime` is `ENDED` and those IDs cannot be reused for commit. Frame bytes
and plans are evidence, not an active host transaction. CLI exits 0 for a
feasible candidate, 1 for a completed nonfeasible/unsupported report, and 2
for stale/invalid/refused input.

### Native visibility correction

`Text.get_visible()` alone does not prove native draw eligibility. Scene
capture now reuses Matplotlib's native axis tick selector, axis visibility
and axes/ancestor visibility. Off-view tick nodes retain their raw
`artist_visible` flag and `visibility_source`, but are not reported as drawn
content or exposed as geometric hit targets. No artist flags, scientific
window or pixels are modified. The regression observes actual `Text.draw`
calls and checks the same RGBA buffer before/after capture; there is no
second draw or screenshot-similarity shortcut.

G4 host acceptance/multi-figure transactions and G5 native final export
remain separate. All G3-C evidence remains snapshot-bound,
`NOT_WRITTEN`, `host: NOT_VERIFIED`, `export_page: NOT_RUN`.

### G3-C exercised evidence

Two independent verification jobs checked the API and the actual public CLI:
58 related cases passed and one was skipped. After the final narrow changes,
only the directly affected real two-figure lifecycle test and two CLI boundary
tests were rerun: all three passed. No full regression or frontend build ran.

The public CLI used actual NMR and FTIR scripts with different fixed page
rectangles. In grid `[10, 9, 8.5, 8]`, 10 pt exceeded FTIR's declared source
font range; 9 and 8.5 pt were rejected by Native QA. The selected 8 pt point
was rebuilt and replayed, with source/scientific/content evidence retained:

| Figure | Captured source pt | Measured page scale | Final effective pt |
| --- | ---: | ---: | ---: |
| NMR | 8 | 1 | 8 |
| FTIR | 10.6667 | 0.75 | 8 |

A final-source CLI run also selected the explicit integer-valued NMR
`legend_cols=2` alternative at that common effective size. It used four
preview calls out of twelve: two figure trials and their two replays.
Native extents did not change on this path, so no additional scale-correction
preview was needed; canvas-changing G3-C variants are not claimed exercised
by this scenario.

The real API check covered failed previews consuming budget, coupled-control
refusal, returned IDs matching currently pending replay frames, and an owner
moving the fixed photo during replay. The last case returned STALE, exposed
no candidate and removed only the search's own pending candidates. Confirmed
NMR annotation IDs remained required throughout.

The restored `layout-snapshot` command still captured the reference saved page's
33 objects / 31 panels; its legacy runtime figures remained SPACE_ONLY in
`layout-report`. Original scripts, configurations and reference page were
byte-hash unchanged. The successful CLI ended its sessions and explicitly
returned inactive IDs. These are measured candidate and saved-page facts,
not a live Tavotto display, multi-figure commit or final export proof.

## G3-D: real three-figure integration (DERIVED standalone)

G3-D does not extend the core. It adds two real Native providers and one
read-only harness that consumes the **actual saved page** with the **actual**
supported figures, and reports measured facts.

- `examples/xrd/plot_xrd.py` + `examples/xrd/xrd.yaml`: a Native provider for
  the real XRD panel. Scientific constants are locked verbatim from the
  original project script (display window 10-80 deg, ALS 2e7/0.01/15,
  Savitzky-Golay 7/2, offset step 2.40, wavelength 1.540593, the five ZnO
  crystal faces at [31.77, 36.25, 47.54, 56.60, 62.86]). `data_dir` is
  LOCKED_SCIENCE; the portable default is empty and `load_science` fails
  clearly rather than guessing a path. The five real scan files that are
  actually read are declared through `science_inputs()`, so the native worker
  hashes them into the input revision: a changed scan invalidates the
  candidate instead of silently producing a different rebuild.
- `examples/plate/verify_three_figures.py`: one command that reads the real
  saved page, keeps every original object and rectangle fixed, and runs one
  bounded common-X-title search over NMR, FTIR and XRD. The managed binding
  exists only inside a **DERIVED standalone** snapshot; the original page
  stays untouched and its legacy runtime figures stay SPACE_ONLY.

### Two status fields, never one exit code

`evidence.json` carries independent fields:

- `harness_status`: `OK` / `PREREQUISITE_MISSING` / `HARNESS_ERROR` - did the
  harness execute and produce evidence.
- `search_status`: `FEASIBLE` / `NO_CANDIDATE` / `UNSUPPORTED` / `STALE` /
  `CONSTRAINT_VIOLATION` / `UNSUPPORTED_GEOMETRY` - the solver's verdict.

The exit code maps `harness_status` only (0 / 2 / 1). A reader must never
infer search feasibility from the exit code. A `NO_CANDIDATE` or `UNSUPPORTED`
result with `harness_status: OK` means the chain ran and the layout is
genuinely not solvable under the stated constraints - that is an integration
result, not an optimization success.

### Host placement is not a uniform scale

The Tavotto host maps the **crop window** onto the placed rectangle with
independent horizontal and vertical scales (`placement.py`: crop to source
mm, then `sx = Rw/Cw`, `sy = Rh/Ch`; the canvas preview does the same as an
overflow-hidden viewport). The crop window fills the rectangle; the rest of
the native image lies outside the viewport. A cropped panel is therefore
**not** a uniform-scale placement, and the harness refuses to assume 1:1.
It proves, from measured frame and projection facts, that the measured extent
matches the intended canvas, that the stored crop lies inside it (remapped
with the existing G2 rule when the stored native basis differs), that the
engine's projected scale equals the host's own crop-to-rect scales, and that
the placement is not distorted. An unprovable placement is refused with
`UNSUPPORTED_GEOMETRY` and the measured numbers; transforms are never
auto-corrected.

The measured outcome and its limits

The real run opened all three providers with verified science and proved the
geometry for all three targets: NMR and XRD are isotropic (0.99191 and 1.0),
while the FTIR panel is the host's own anisotropic crop-fill
(sx 1.11776 / sy 0.99272; the horizontal scale exceeds the vertical one by
about 12.6 percent of the vertical scale, and the two differ by about 11.2
percent of the horizontal one). A single scalar effective font
is therefore not measurable for that panel, and the search refuses it with
`ANISOTROPIC_SCALE` naming the panel and the role. No constraint was relaxed
to obtain a candidate.

Two real provider defects were found and fixed on the way, both by
measurement rather than by guesswork:

- The NMR provider parsed its own arguments with an empty list at import, so
  its contract baseline was built from the repository default 48x48 config
  while the session baseline used the page's native 41.0x46.13 mm. At the
  smaller canvas four annotation objects are legitimately not placed, and the
  contract then declared gids that did not exist. The provider now resolves
  the configuration the native runtime passes it, and keys its baseline cache
  by canvas size.
- The XRD provider's label placement zipped the drawn artists against all
  candidate items, so drawn labels were registered under the wrong gids. A
  numeric bisection showed the label solver itself behaved identically to the
  original project; only the gid pairing differed. It now follows the
  solver's own dropped list.

The XRD provider reproduces the original project's published figure: at the
source canvas 41.0 x 46.13444575910199 mm it draws exactly `(100)`, `(102)`,
`(103)` - the same three labels present in the original exported SVG. The
original script drops `(101)` and `(110)` because they do not fit; those
crystal faces remain scientific anchors in the manifest, marked
`hkl_labels_not_drawn`, with no gid declared for an artist that was never
drawn. The NMR manifest does the same for template peaks that cannot be
placed at a given canvas (`placement: DRAWN` / `NOT_PLACED`).

This is snapshot-bound, read-only integration evidence for a derived
scenario. It is not a live Tavotto display, a multi-figure commit, a
whole-page export or a claim that the three figures were jointly optimized.

### G3-D exercised evidence

One clean real run of the harness over the actual saved page and the three
actual providers:

- `harness_status: OK`, `search_status: UNSUPPORTED`, exit 0 (the exit code
  reports execution only). Reason:
  `p_ti835i4w:ANISOTROPIC_SCALE:fig2_ftir.main.xlabel`. The FTIR panel is the
  host's own anisotropic crop-fill, so one scalar effective font is not
  measurable there and the search refuses it by name. `render_count` 0, no
  candidate, no preview, `active_candidates` false.
- The page still reads 33 objects / 31 panels; all three targets bound and
  proved geometry `PROVEN` with `engine_scale_matches_host` true:
  NMR extent 41.0 x 46.1344 mm, no crop, scale 0.99191 isotropic; FTIR extent
  38.8765 x 46.1344 mm, crop window [6.0914, 0, 32.7851, 43.8066] mm, host
  and engine scale [1.11776380, 0.99271615], anisotropic; XRD extent
  41.0 x 46.1344 mm, no crop, scale 1.0 isotropic.
- Captured visible labels: XRD `hkl.100/102/103` drawn (`101`/`110` are
  dropped by the source itself and have no artist); NMR peaks
  `hama.6p18`, `vancho.3p91`, `vancho.9p83`, `vannh2.3p03`, `vanoh.4p62`
  drawn, `vancho.3p68` and `hama.2p02` not placed. The template lists all
  twelve identities; the required set is the captured visible subset.
- Measured baseline effective title sizes: NMR 8.4313 pt on both titles, XRD
  8.17 pt on both, FTIR unknown with `font_reason: ANISOTROPIC_SCALE`.
- Invariants all true: original rectangles identical, untouched neighbours
  identical, page bytes unchanged, official configs unchanged. All 14 inputs
  (page, three YAMLs, three scripts, harness, five scan files) were
  byte-identical before and after. All three sessions closed with no pending
  candidate left behind.
- Focused checks: 15 passed, 0 failed, 0 skipped
  (`test_three_figure_integration.py`, `test_xrd_native.py`,
  `test_nmr_sized_canvas.py`). The existing NMR checks (10 cases) also still
  pass, so the default 48x48 path did not regress. No full-repository
  regression was run.

**G3-D verdict: integration verified, candidate infeasible.** The chain
measured the real page, the real providers and the real placement rules, and
reported precisely why one common effective font does not exist for this
page as the host places it. It is not a claim that the three figures were
jointly optimized, and it is not a final page export.

## G4-A: prepared acceptance plans (PREPARED only)

G4 turns a **verified** figpact candidate into something the host actually
uses. G4-A is the thin first half: it prepares immutable resources and the
minimal document change, and checks every stale precondition before anything
is staged. It never writes a host document, never commits a Native config and
never mutates a page.

The two halves of the evidence stay separate, as they must: figpact proves
"this figure may be changed this way"; the host proves "this current page has
actually adopted the result". Neither substitutes for the other.

### What the host already provides (reused, not rebuilt)

The Tavotto host has one document authority and one atomic writer
(`engine/atomicio.py`: same-directory temp file, fsync, `os.replace`,
directory fsync), reached through two whole-document save routes that both
validate, take a per-path lock, compare an optional `base_revision` and
re-read the revision inside the lock. Staleness is the **content-hash
revision** (`X-Tavotto-Revision`), not `updatedAt`; a mismatch is
`409 external_change`. There is **no per-panel endpoint and no batch-panel
helper**, so applying several prepared figures is **one whole-document
write**, not one request per panel. The backend's only revert path is the
versions timeline (full-document snapshots); undo/redo is frontend-only.
Panels reference resources by a relative `fileId`; there is no content hash
field inside a panel object. figpact therefore adds **no** second page model,
resource store, revision model or undo system.

### The plan

`figpact.acceptance.build_acceptance_plan(candidates, *, host_document,
base_revision, resources_dir, expected_document_revision=None)` returns a
`figpact.acceptance-plan/1` document:

- `status` `READY` (state `PREPARED`) or `REFUSED`, and
  `evidence.first_failure` naming the failed check.
- `preconditions`: every check with its expected and observed values, in
  order: `document_identity`, `candidate_freshness`,
  `panel_identity_ownership`, `panel_placement`, `uniform_scale`,
  `required_content`, `resource_preparation`, `document_patch_minimality`.
- `resources`: per panel, the staged PDF's project-relative path, the
  absolute staging path, its `bytes_sha256`, the measured `page_mm` and the
  frame/candidate/science facts it came from.
- `document_patch`: the canvas and the exact per-panel field changes, and
  `next_document`: the schema-3 document the host **would** write, computed
  but never written.

The order matters: resources are produced and hashed **before** any page
reference exists, so the page can never point at bytes that were not fully
prepared. The prepared reference is relative to the project root, because
that is how the host resolves a panel's `fileId`; a staging directory outside
the project root is refused rather than producing a dangling reference. The
prepared PDF's measured page size must equal the panel's stored
`nativeW`/`nativeH`, otherwise the panel's displayed layout would change and
the candidate's measured sizes would no longer describe the page.

### What the plan refuses

- A page, candidate or override that moved since the plan was based on it
  (`document_identity`, `candidate_freshness`).
- A panel that is not explicitly figpact-managed, whose `figpact`
  config/scope binding does not match the candidate, or that carries
  unreplayed host overrides (`panel_identity_ownership`). Legacy runtime
  panels are **not** migrated by flipping an owner flag; native figure
  migration is a separate, explicitly authorized action that keeps the old
  resource and a recovery path.
- A panel whose placement no longer matches the one the candidate was
  measured against (`panel_placement`).
- A panel placed with an **anisotropic** host transform (`uniform_scale`).
  The host maps a crop window onto the placed rectangle with independent
  horizontal and vertical scales, so a cropped panel has no single scalar
  effective font; the plan refuses it by name instead of accepting a font
  measurement that does not exist.
- A confirmed required id that is absent from the prepared resource
  (`required_content`).
- Any difference between the host document and the computed next document
  outside the named panel fields (`document_patch_minimality`).

### G4-A exercised evidence

One real run against the actual saved page and the actual providers, in a
temporary copy of the project root. All twelve inputs (the page, three
provider scripts, three provider YAMLs, five Rigaku scan files) were
byte-identical before and after, and **no case wrote the host document**.

- Legacy page as-is: **REFUSED**, `panel_identity_ownership` - the real
  panels are `renderOwner` tavotto/asset with no `figpact` binding.
- The real FTIR panel in a derived managed host document: **REFUSED**,
  `uniform_scale`, observed scales `[1.11776380, 0.99271615]` - the same
  honest verdict G3-D reached, now enforced before anything is staged.
- The real XRD panel in a derived managed host document (isotropic,
  41.0 x 46.1344 mm): **READY / PREPARED**. The resource was staged and
  hashed, its project-relative path resolves to exactly those bytes, the
  prepared PDF's measured page size matched the stored native size, the patch
  set only that panel's `fileId`, and the next document differed from the host
  document in that field alone.

The derived host documents in the last two cases were prepared for the plan
in a temporary copy; they are not the live page, and no host write happened.
G4-A reaches PREPARED only. `HOST_APPLIED`, `HOST_PERSISTED`,
`REOPEN_VERIFIED` and `FINAL_EXPORT_VERIFIED` remain out of reach here, and
G4's own goal is `REOPEN_VERIFIED`; the final export is G5.

## G4-B: dual-resource persistence and reopen verification

G4-A prepares resources. G4-B fixes the pair: a managed panel is displayed by
the host from a LIVE figpact frame, not from its `fileId`, and a saved PDF
whose `figpact.config` still points at the old config will re-render the OLD
figure on reopen. Staging a PDF alone would therefore leave a page that shows
one thing in the file and rebuilds another from the config. The plan must fix
the immutable PDF **and** the immutable candidate CONFIG together, and patch
the page with both `fileId` and `figpact.config`.

### What the host needs from a reopened managed panel

Today a managed panel with no live frame renders an empty box with a stale
badge; its `fileId` is never fetched for display, and the in-memory stale PNG
dies on reload. For a reopened page to show the figure, the host needs an
explicit branch: when no live binding/frame exists, resolve the panel's own
prepared resource and display it, keyed by the panel's identity facts
(`fileId`, `script`, `config`, `scope`, `overrides`), never fabricating a
binding or a display receipt. A managed panel whose `fileId` is still an
opaque runtime id has no fetchable resource and keeps the empty/stale state
with a reason. The live frame still wins when present.

### What the plan now proves

`build_acceptance_plan` gains `persist_config=True`: each managed candidate
carries its Native `config_patch` plus the config source it was produced
from. The plan applies that patch through the parameter catalog, stages the
resulting config durably (same-dir temp file, fsync, replace, directory
fsync; never overwriting a different file), rebuilds it in a fresh session
over the staged path and requires the rebuild to reproduce the candidate:
the science digest and verified flag, the same declared science inputs with
identical content hashes, the same projection geometry, the same measured
effective fonts within 0.01 pt, and the same required content in the visible
measured crop. A patch that cannot be produced from the given source, a
rebuild that renders a different figure or a changed science basis refuses
the plan with `config_persisted`. The document patch for a managed panel
then sets `fileId` and `figpact.config` (scope unchanged); a non-managed
panel still receives `fileId` only.

The review's three hardening items are part of the plan:

- `required_content` is checked against visibility, measured state and the
  visible crop, using the existing engine rule; an id that exists but is
  invisible or cropped refuses, with the id named.
- A target panel id must be unique across the whole document and belong to
  the plan's canvas; a duplicate id anywhere else refuses instead of being
  resolved by first match.
- Staged resources are durably written before the page could ever reference
  them, reusing the atomic-file discipline, not a second database.

New plan fields: `resources[].config_path`, `config_sha256`,
`config_rebuild_verified`, `config_rebuild_frame_revision`; new checks
`config_persisted` and `panel_binding_update` alongside the eight G4-A names.
G4-B reaches PREPARED only. HOST_APPLIED, HOST_PERSISTED and REOPEN_VERIFIED
stay with the host: figpact prepares and verifies the pair, the host applies
the one whole-document write, confirms the save, and re-reads the page from
disk. The final export stays G5.
