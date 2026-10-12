'use strict';

// G1 frontend inspector tests: pure helper interface of tools/inspector/inspector.js.
// Node builtins only (node:test / node:assert / node:crypto for gold digests).
// The frontend script must be loadable in Node without a DOM.

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

// Static, real transparent RGBA PNG, 800x400. No image library is needed by Node.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAyAAAAGQCAYAAABWJQQ0AAAE70lEQVR42u3BAQ0AAADCoPdPbQ8HF'
  + 'A'.repeat(1653) + 'D8GIqtAAHYQ7zZAAAAAElFTkSuQmCC', 'base64');

const HELPER_PATH = process.env.FIGPACT_INSPECTOR_JS
  ? process.env.FIGPACT_INSPECTOR_JS
  : path.join(__dirname, '..', '..', 'tools', 'inspector', 'inspector.js');

function loadHelper() {
  assert.equal(fs.existsSync(HELPER_PATH), true, `missing frontend helper: ${HELPER_PATH}`);
  // eslint-disable-next-line global-require
  const mod = require(HELPER_PATH);
  assert.equal(typeof mod, 'object', 'inspector.js must export its helper namespace');
  return mod;
}

function sha256Hex(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

function strokeNode(id, runs, extra = {}) {
  return {
    id,
    gid: id,
    registered: true,
    type: 'curve',
    artist_type: 'Line2D',
    scope: 'measurement',
    parent: null,
    measured: true,
    bounds_mm: [0, 0, 100, 50],
    envelope_mm: null,
    anchors: null,
    hit_mode: 'stroke',
    runs_mm: runs,
    linewidth_mm: 0.35,
    linestyle: '-',
    marker: 'None',
    editable_capability: 'READ_ONLY',
    ...extra,
  };
}

function sceneFixture(nodes, extra = {}) {
  return {
    schema: 'figpact.inspector.scene/1',
    scope: 'measurement',
    source_revision: null,
    unit: 'mm',
    coordinate_reference: 'canvas_bottom_left',
    canvas_bounds_mm: [0, 0, 100, 50],
    image: { width_px: 800, height_px: 400, bounds_mm: [0, 0, 100, 50] },
    measurement: { unit: 'mm', dpi: 203.2, calibrated: false },
    nodes,
    diagnostics: [],
    ...extra,
  };
}

function bundleFixture(scene, overrides = {}) {
  const sceneJson = JSON.stringify(scene);
  const sceneSha = sha256Hex(sceneJson);
  const pngSha = crypto.createHash('sha256').update(PNG).digest('hex');
  return {
    schema: 'figpact.inspector/1',
    frame_revision: sha256Hex(`${pngSha}\n${sceneSha}`),
    image_revision: sha256Hex(`${pngSha}\n${sceneSha}`),
    geometry_revision: sha256Hex(`${pngSha}\n${sceneSha}`),
    png_base64: PNG.toString('base64'),
    png_sha256: pngSha,
    scene_json: sceneJson,
    scene_sha256: sceneSha,
    ...overrides,
  };
}

test('curve bbox blank area does not hit the curve', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([strokeNode('curve.main', [[[0, 0], [100, 0]]])]);
  const hits = hitCandidates(scene, { x: 50, y: 25 }, 2, 4);
  assert.deepEqual(hits.map((c) => c.id), []);
});

test('curve bbox blank area stays empty after zoom (fixed CSS pixel tolerance)', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([strokeNode('curve.main', [[[0, 0], [100, 0]]])]);
  // 4 CSS px at 8 px/mm is only 0.5 mm of slack: a 25 mm blank gap still misses.
  assert.deepEqual(hitCandidates(scene, { x: 50, y: 25 }, 8, 4).map((c) => c.id), []);
  // The same blank gap at 0.25 px/mm (4 mm of slack) still misses.
  assert.deepEqual(hitCandidates(scene, { x: 50, y: 25 }, 0.25, 4).map((c) => c.id), []);
});

test('real point-to-segment hit on the centerline within stroke + tolerance', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([strokeNode('curve.main', [[[0, 0], [100, 0]]])]);
  const hits = hitCandidates(scene, { x: 50, y: 0.8 }, 2, 4);
  assert.equal(hits.length, 1);
  assert.equal(hits[0].id, 'curve.main');
  assert.ok(Number.isFinite(hits[0].distance));
});

test('NaN gap is not bridged into a hit', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([
    strokeNode('curve.main', [[[0, 0], [10, 0], [null, null], [10, 10], [20, 10]]]),
  ]);
  const hits = hitCandidates(scene, { x: 10, y: 5 }, 2, 4);
  assert.deepEqual(hits.map((c) => c.id), []);
});

test('disconnected runs never connect across a clip break', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([
    strokeNode('curve.main', [[[0, 0], [100, 0]], [[0, 40], [100, 40]]]),
  ]);
  assert.deepEqual(hitCandidates(scene, { x: 50, y: 20 }, 2, 4).map((c) => c.id), []);
  assert.deepEqual(hitCandidates(scene, { x: 50, y: 0 }, 2, 4).map((c) => c.id), ['curve.main']);
});

test('marker-only line has no invisible centerline hit', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([
    strokeNode('markers.only', null, {
      gid: null,
      registered: false,
      hit_mode: 'none',
      marker: 'o',
      linestyle: 'None',
      descriptor: 'Line2D (markers only)',
    }),
  ]);
  const hits = hitCandidates(scene, { x: 50, y: 25 }, 2, 4);
  assert.deepEqual(hits.map((c) => c.id), []);
});

test('fully clipped and unmeasured nodes never hit by geometry', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([
    strokeNode('curve.clipped', null, { hit_mode: 'none', fully_clipped: true }),
    strokeNode('curve.unmeasured', null, { hit_mode: 'none', measured: false, bounds_mm: null }),
  ]);
  assert.deepEqual(hitCandidates(scene, { x: 10, y: 10 }, 2, 4).map((c) => c.id), []);
});

test('text/image renderer envelope hits, without becoming a curve', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([
    {
      id: 'text.label',
      gid: 'label.391',
      registered: true,
      type: 'text',
      artist_type: 'Text',
      scope: 'measurement',
      parent: null,
      measured: true,
      bounds_mm: [10, 10, 30, 20],
      envelope_mm: [10, 10, 30, 20],
      hit_mode: 'envelope',
      text: '3.91 ppm',
      editable_capability: 'READ_ONLY',
    },
  ]);
  const inside = hitCandidates(scene, { x: 20, y: 15 }, 2, 4);
  assert.deepEqual(inside.map((c) => c.id), ['text.label']);
  const outside = hitCandidates(scene, { x: 80, y: 40 }, 2, 4);
  assert.deepEqual(outside.map((c) => c.id), []);
});

test('panel is the lowest priority background hit and never dominates hover', () => {
  const { hitCandidates } = loadHelper();
  const panel = {
    id: 'measurement::panel.0',
    gid: null,
    registered: false,
    type: 'panel',
    artist_type: 'Axes',
    structural: true,
    scope: 'measurement',
    parent: 'measurement::canvas',
    measured: true,
    bounds_mm: [0, 0, 100, 50],
    envelope_mm: [0, 0, 100, 50],
    hit_mode: 'envelope',
    editable_capability: 'READ_ONLY',
  };
  const figure = { ...panel, id: 'measurement::canvas', type: 'figure', artist_type: 'Figure' };
  const scene = sceneFixture([panel, figure, strokeNode('curve.main', [[[0, 10], [100, 10]]])]);
  const hits = hitCandidates(scene, { x: 50, y: 10 }, 2, 4);
  assert.equal(hits[0].id, 'curve.main');
  assert.ok(!hits.some((c) => c.id === 'measurement::canvas'),
    'structural figure must not be a hover candidate');
  const blank = hitCandidates(scene, { x: 50, y: 30 }, 2, 4);
  assert.deepEqual(blank.map((c) => c.id), ['measurement::panel.0']);
});

test('overlapping candidates cycle deterministically', () => {
  const { cycleSelection, hitCandidates } = loadHelper();
  const scene = sceneFixture([
    strokeNode('curve.a', [[[0, 0], [100, 0]]]),
    strokeNode('curve.b', [[[0, 0.2], [100, 0.2]]]),
  ]);
  const hits = hitCandidates(scene, { x: 50, y: 0.1 }, 4, 4);
  assert.deepEqual(hits.map((c) => c.id), ['curve.a', 'curve.b']);
  const ids = hits.map((c) => c.id);
  assert.equal(cycleSelection(ids, null, false), 'curve.a');
  assert.equal(cycleSelection(ids, 'curve.a', true), 'curve.b');
  assert.equal(cycleSelection(ids, 'curve.b', true), 'curve.a');
  assert.equal(cycleSelection(ids, 'curve.a', false), 'curve.a');
  assert.equal(cycleSelection([], 'curve.a', true), null);
  // a stale selection id that is no longer a candidate restarts from the best hit
  assert.equal(cycleSelection(ids, 'gone', true), 'curve.a');
});

test('screenToMm maps the real display rectangle to canvas mm', () => {
  const { screenToMm } = loadHelper();
  const rect = { left: 0, top: 0, width: 200, height: 100 };
  const bounds = [0, 0, 100, 50];
  assert.deepEqual(screenToMm(rect, bounds, 0, 0), { x: 0, y: 50 });
  assert.deepEqual(screenToMm(rect, bounds, 200, 100), { x: 100, y: 0 });
  assert.deepEqual(screenToMm(rect, bounds, 100, 25), { x: 50, y: 37.5 });
});

test('screenToMm is invariant under view pan/zoom and tolerates resize', () => {
  const { screenToMm } = loadHelper();
  const bounds = [0, 0, 100, 50];
  const zoomed = screenToMm({ left: -30, top: -10, width: 400, height: 200 }, bounds, 170, 40);
  assert.deepEqual(zoomed, { x: 50, y: 37.5 });
  const resized = screenToMm({ left: 12, top: 8, width: 376, height: 188 }, bounds, 12 + 188, 8 + 47);
  assert.deepEqual(resized, { x: 50, y: 37.5 });
});

test('screenToMm rejects degenerate rectangles', () => {
  const { screenToMm } = loadHelper();
  assert.throws(() => screenToMm({ left: 0, top: 0, width: 0, height: 100 }, [0, 0, 100, 50], 0, 0));
  assert.throws(() => screenToMm({ left: 0, top: 0, width: 100, height: 100 }, [0, 0, 0, 50], 0, 0));
});

test('niceTickStep keeps a readable ruler interval', () => {
  const { niceTickStep } = loadHelper();
  assert.equal(niceTickStep(1), 50);
  assert.equal(niceTickStep(0.1), 5);
  assert.equal(niceTickStep(10), 500);
  for (const scale of [0.05, 0.25, 1, 2.5, 4, 12, 40]) {
    const step = niceTickStep(scale);
    assert.ok(Number.isFinite(step) && step > 0);
    const px = step / scale; // CSS px between ticks
    assert.ok(px >= 24 && px <= 240, `ruler spacing ${px}px at scale ${scale}`);
  }
  assert.throws(() => niceTickStep(0));
  assert.throws(() => niceTickStep(-1));
});


test('validateFrame rejects stale or inconsistent revisions', () => {
  const { validateFrame } = loadHelper();
  const scene = sceneFixture([]);
  const good = bundleFixture(scene);
  assert.throws(() => validateFrame({ ...good, frame_revision: sha256Hex('tampered') }));
  assert.throws(() => validateFrame({ ...good, image_revision: sha256Hex('tampered') }));
  assert.throws(() => validateFrame({ ...good, geometry_revision: sha256Hex('tampered') }));
  assert.throws(() => validateFrame({ ...good, schema: 'figpact.inspector/2' }));
});

test('validateFrame rejects non-finite geometry and wrong coordinate reference', () => {
  const { validateFrame } = loadHelper();
  const scene = sceneFixture([]);
  assert.throws(() => validateFrame(bundleFixture({ ...scene, canvas_bounds_mm: [0, 0, 100, null] })));
  assert.throws(() => validateFrame(bundleFixture({ ...scene, unit: 'px' })));
  assert.throws(() => validateFrame(bundleFixture({ ...scene, coordinate_reference: 'top_left' })));
  assert.throws(() => validateFrame(bundleFixture({ ...scene, image: { width_px: 0, height_px: 400, bounds_mm: [0, 0, 100, 50] } })));
  assert.throws(() => validateFrame(bundleFixture({ ...scene, measurement: { dpi: 200 } })));
  const brokenNodes = sceneFixture([strokeNode('curve.main', [[[0, 0], [null, 0]]])]);
  assert.throws(() => validateFrame(bundleFixture(brokenNodes)));
});

test('validateFrame rejects false stable identity for an unregistered object', () => {
  const { validateFrame } = loadHelper();
  const scene = sceneFixture([strokeNode('temporary', null, {
    registered: false, gid: null, identity_stability: 'stable', hit_mode: 'none',
  })]);
  assert.throws(() => validateFrame(bundleFixture(scene)), /identity/i);
});

test('hit width includes the real stroke width on top of the fixed CSS tolerance', () => {
  const { hitCandidates } = loadHelper();
  const thick = sceneFixture([strokeNode('curve.thick', [[[0, 0], [100, 0]]], { linewidth_mm: 2 })]);
  const inside = hitCandidates(thick, { x: 50, y: 0.6 }, 2, 0);
  assert.deepEqual(inside.map((c) => c.id), ['curve.thick']);
  const thin = sceneFixture([strokeNode('curve.thin', [[[0, 0], [100, 0]]], { linewidth_mm: 0.1 })]);
  assert.deepEqual(hitCandidates(thin, { x: 50, y: 0.6 }, 2, 0).map((c) => c.id), []);
});

test('hover is side-effect free and re-runs independently per candidate run', () => {
  const { hitCandidates } = loadHelper();
  const scene = sceneFixture([
    strokeNode('curve.main', [[[0, 0], [100, 0]], [[0, 30], [100, 30]]]),
  ]);
  const before = JSON.stringify(scene);
  const first = hitCandidates(scene, { x: 50, y: 29.5 }, 2, 4);
  const second = hitCandidates(scene, { x: 50, y: 0.5 }, 2, 4);
  assert.equal(first[0].distance, 0.5);
  assert.equal(second[0].distance, 0.5);
  assert.equal(JSON.stringify(scene), before, 'pointer observation must not mutate scene geometry');
});


test('verifyFrame rejects modified PNG bytes without a new frame', async () => {
  const { verifyFrame } = loadHelper();
  const good = bundleFixture(sceneFixture([]));
  await verifyFrame(good);
  const bytes = Buffer.from(PNG);
  bytes[40] ^= 1;
  await assert.rejects(verifyFrame({ ...good, png_base64: bytes.toString('base64') }), /png/i);
});

test('verifyFrame rejects scene bytes or digest changes', async () => {
  const { verifyFrame } = loadHelper();
  const good = bundleFixture(sceneFixture([]));
  await verifyFrame(good);
  await assert.rejects(verifyFrame({ ...good, scene_json: JSON.stringify(sceneFixture([], { source_revision: 'different' })) }), /scene/i);
  await assert.rejects(verifyFrame({ ...good, scene_sha256: sha256Hex('tampered') }), /scene/i);
});

test('verifyFrame rejects a broken revision chain even when all revision fields agree', async () => {
  const { verifyFrame } = loadHelper();
  const good = bundleFixture(sceneFixture([]));
  const revision = sha256Hex('nonsense');
  await assert.rejects(verifyFrame({ ...good, frame_revision: revision, image_revision: revision, geometry_revision: revision }), /revision/i);
});

test('verifyFrame refuses pixel dimensions inconsistent with the PNG', async () => {
  const { verifyFrame } = loadHelper();
  const scene = sceneFixture([], {
    image: { width_px: 400, height_px: 200, bounds_mm: [0, 0, 50, 25] },
  });
  await assert.rejects(verifyFrame(bundleFixture(scene)), /dimensions/i);
});

test('validateFrame rejects a guessed physical pixel scale', () => {
  const { validateFrame } = loadHelper();
  const scene = sceneFixture([], { measurement: { unit: 'mm', dpi: 200, calibrated: false } });
  assert.throws(() => validateFrame(bundleFixture(scene)), /DPI/i);
});

test('validateFrame compares an optional expected source revision without inventing one', () => {
  const { validateFrame } = loadHelper();
  const withSource = sceneFixture([], { source_revision: 'source-sha-1' });
  const bundle = bundleFixture(withSource);
  assert.equal(validateFrame(bundle, 'source-sha-1').source_revision, 'source-sha-1');
  assert.throws(() => validateFrame(bundle, 'source-sha-2'), /source/i);
  const noSource = bundleFixture(sceneFixture([]));
  assert.equal(validateFrame(noSource, null).source_revision, null);
  assert.throws(() => validateFrame(noSource, 'source-sha-2'), /source/i);
});

function labelNode(extra = {}) {
  return { id: 'label', gid: 'label.391', registered: true, identity_stability: 'stable',
    type: 'text', measured: true, hit_mode: 'envelope', bounds_mm: [10, 10, 30, 20],
    editable_capability: 'READ_ONLY', ...extra };
}

function liveBundle(nodes = [labelNode()]) {
  const frame = bundleFixture(sceneFixture(nodes, { source_revision: 'source-1' }));
  frame.session = { session_id: 'session-1', scene_revision: frame.frame_revision,
    source_revision: 'source-1', can_evaluate: true };
  return frame;
}

test('G1 fit uses actual wrap width and height and centers the canvas', () => {
  const { fitViewport } = loadHelper();
  const view = fitViewport([0, 0, 100, 50], 418, 218, 1);
  assert.equal(view.scale, 4);
  assert.deepEqual([view.width, view.height, view.left, view.top], [400, 200, 18, 18]);
  const tall = fitViewport([0, 0, 100, 50], 818, 218, 1);
  assert.equal(tall.left, 218);
  assert.equal(tall.top, 18);
});

test('G1 zoom preserves the pointed mm location with positioned viewport offsets', () => {
  const { fitViewport, zoomViewport, screenToMm } = loadHelper();
  const before = fitViewport([0, 0, 100, 50], 818, 418, 1);
  const after = fitViewport([0, 0, 100, 50], 818, 418, 2);
  const anchor = { x: 450, y: 240 };
  const scroll = zoomViewport(before, after, { left: 0, top: 0 }, anchor);
  const mmBefore = screenToMm({ left: before.left, top: before.top, width: before.width, height: before.height }, [0, 0, 100, 50], anchor.x, anchor.y);
  const mmAfter = screenToMm({ left: after.left - scroll.left, top: after.top - scroll.top, width: after.width, height: after.height }, [0, 0, 100, 50], anchor.x, anchor.y);
  assert.deepEqual(mmAfter, mmBefore);
});

test('G2 fifteen Alt presses aggregate one desired operation without mutating geometry', () => {
  const { createIntentSession } = loadHelper();
  const frame = liveBundle(), original = frame.scene_json;
  const session = createIntentSession(frame);
  session.select('label');
  session.press({ key: 'ArrowRight', altKey: true, viewportFocused: true });
  const operation = session.snapshot().intent.operation_id;
  for (let i = 1; i < 15; i++) session.press({ key: 'ArrowRight', altKey: true, viewportFocused: true, repeat: true });
  const snapshot = session.snapshot();
  assert.equal(snapshot.intent.operation_id, operation);
  assert.deepEqual(snapshot.intent.delta_mm, [0.15, 0]);
  assert.equal(snapshot.status, 'DESIRED_ONLY');
  assert.deepEqual(snapshot.ghost.bounds_mm, [10.15, 10, 30.15, 20]);
  assert.equal(frame.scene_json, original);
});

test('G2 Arrow input focus and system shortcuts cannot create a desired operation', () => {
  const { createIntentSession } = loadHelper();
  const session = createIntentSession(liveBundle());
  session.select('label');
  for (const context of [{ inputActive: true }, { viewportFocused: false }, { ctrlKey: true }, { metaKey: true }]) {
    assert.equal(session.press({ key: 'ArrowUp', viewportFocused: true, ...context }), false);
    assert.equal(session.snapshot().intent, null);
  }
  session.press({ key: 'ArrowUp', shiftKey: true, viewportFocused: true });
  assert.deepEqual(session.snapshot().intent.delta_mm, [0, 0.5]);
});

test('G2 scientific curves and independent guide endpoints cannot masquerade as rigid ghosts', () => {
  const { createIntentSession } = loadHelper();
  const session = createIntentSession(liveBundle([
    strokeNode('curve', [[[10, 10], [20, 20]]]),
    strokeNode('guide', [[[10, 10], [20, 20]]], { type: 'guide' }),
    labelNode({ id: 'unmeasured', measured: false }),
  ]));
  for (const id of ['curve', 'guide', 'unmeasured']) {
    session.select(id);
    assert.equal(session.press({ key: 'ArrowRight', viewportFocused: true }), false);
    assert.equal(session.snapshot().ghost, null);
  }
});

test('G2 exact numeric delta retains out-of-range ghost and requires explicit selection decision', () => {
  const { createIntentSession } = loadHelper();
  const session = createIntentSession(liveBundle([labelNode(), labelNode({ id: 'other', gid: 'other' })]));
  session.select('label');
  session.setDelta(0.15, 0);
  assert.deepEqual(session.snapshot().intent.delta_mm, [0.15, 0]);
  assert.equal(session.select('other'), false);
  assert.equal(session.snapshot().selected, 'label');
  assert.equal(session.snapshot().selectionBlocked, true);
  session.setDelta(150, 0);
  assert.deepEqual(session.snapshot().ghost.bounds_mm, [160, 10, 180, 20]);
  assert.equal(session.snapshot().status, 'OUT_OF_RANGE');
  session.cancel();
  assert.equal(session.select('other'), true);
});

test('G2 linked guide prediction fixes the scientific endpoint and never changes the original', () => {
  const { createIntentSession } = loadHelper();
  const guide = strokeNode('guide', [[[4, 5], [15, 15]]], { type: 'guide', gid: 'guide.391' });
  const frame = liveBundle([labelNode({ linked_guide_gid: 'guide.391' }), guide]);
  const session = createIntentSession(frame);
  session.select('label');
  session.setDelta(0.15, 0);
  assert.deepEqual(session.snapshot().intent.preserve.follow_gids, ['guide.391']);
  assert.deepEqual(session.snapshot().ghost.guide_runs_mm, [[[4, 5], [15.15, 15]]]);
  assert.deepEqual(guide.runs_mm, [[[4, 5], [15, 15]]]);
});

test('G2 static ordinary plots are desired-only and cannot claim live accept capability', () => {
  const { createIntentSession, canAcceptEvaluation } = loadHelper();
  const session = createIntentSession(bundleFixture(sceneFixture([labelNode({ registered: false, identity_stability: 'ephemeral', gid: null })])));
  session.select('label');
  session.setDelta(0.15, 0);
  assert.equal(session.snapshot().canEvaluate, false);
  assert.equal(session.snapshot().status, 'DESIRED_ONLY');
  assert.equal(canAcceptEvaluation({}, session.snapshot().intent), false);
});

test('G2 accept refuses actual 0.11mm mismatch and unverified evidence despite OK status', () => {
  const { createIntentSession, canAcceptEvaluation } = loadHelper();
  const session = createIntentSession(liveBundle());
  session.select('label'); session.setDelta(0.15, 0);
  const intent = session.snapshot().intent;
  const response = { status: 'OK', operation_id: intent.operation_id, intent_state: 'READY',
    evaluation_state: 'FEASIBLE', verification_level: 'RENDER_CHECKED', persistence_state: 'EPHEMERAL',
    target_delta_mm: [0.15, 0], measured_delta_mm: [0.15, 0], error_mm: 0,
    checks: [{ check: 'science', status: 'PASS' }] };
  assert.equal(canAcceptEvaluation(response, intent), true);
  assert.equal(canAcceptEvaluation({ ...response, measured_delta_mm: [0.11, 0], error_mm: 0 }, intent), false);
  assert.equal(canAcceptEvaluation({ ...response, verification_level: 'NONE' }, intent), false);
  assert.equal(canAcceptEvaluation({ ...response, checks: [{ check: 'science', status: 'UNVERIFIED' }] }, intent), false);
  assert.equal(canAcceptEvaluation({ ...response, operation_id: 'other' }, intent), false);
});

test('G2 stale live session metadata is rejected before interaction', () => {
  const { validateFrame } = loadHelper();
  const frame = liveBundle();
  assert.throws(() => validateFrame({ ...frame, session: { ...frame.session, scene_revision: sha256Hex('stale') } }), /session|revision/i);
  assert.throws(() => validateFrame({ ...frame, session: { ...frame.session, source_revision: 'different' } }), /session|source/i);
});

test('G2 decision payload enforces accepted scene_revision and valid operation identity', () => {
  const { buildDecisionPayload } = loadHelper();
  const frame = liveBundle();
  const payload = buildDecisionPayload(frame, 'op-test-1', 'accept');
  assert.equal(payload.operation_id, 'op-test-1');
  assert.equal(payload.decision, 'accept');
  assert.equal(payload.session_id, 'session-1');
  assert.equal(payload.scene_revision, frame.frame_revision);
  assert.equal(payload.source_revision, 'source-1');
  assert.throws(() => buildDecisionPayload(frame, '', 'accept'), /operation_id/i);
  assert.throws(() => buildDecisionPayload(frame, 'op-1', 'invalid_decision'), /decision/i);
  assert.throws(() => buildDecisionPayload({ ...frame, session: null }, 'op-1', 'cancel'), /session/i);
});

test('G2 session operation stack manages real accepted operation ids without history bloat', () => {
  const { createOperationStack } = loadHelper();
  const stack = createOperationStack();
  assert.equal(stack.canUndo(), false);
  assert.equal(stack.pop(), null);
  stack.push('op-1');
  stack.push('op-2');
  assert.equal(stack.canUndo(), true);
  assert.equal(stack.peek(), 'op-2');
  assert.deepEqual(stack.all(), ['op-1', 'op-2']);
  assert.equal(stack.pop(), 'op-2');
  assert.equal(stack.pop(), 'op-1');
  assert.equal(stack.canUndo(), false);
});

test('G2 decision response validation rejects QUALITY_LOCKED, STALE_REVISION, and non-OK status', () => {
  const { isDecisionSuccessful } = loadHelper();
  assert.equal(isDecisionSuccessful({ status: 'OK' }), true);
  assert.equal(isDecisionSuccessful({ status: 'QUALITY_LOCKED' }), false);
  assert.equal(isDecisionSuccessful({ status: 'STALE_REVISION' }), false);
  assert.equal(isDecisionSuccessful({ status: 'INVALID_INTENT' }), false);
  assert.equal(isDecisionSuccessful({ status: 'UNDO_CONFLICT' }), false);
  assert.equal(isDecisionSuccessful(null), false);
  assert.equal(isDecisionSuccessful({}), false);
});

test('G2 in-flight evaluation guard prevents stale or mismatched responses from overriding state', () => {
  const { createInFlightGuard } = loadHelper();
  const guard = createInFlightGuard();
  const gen1 = guard.start('op-1', [0, 0.15]);
  assert.equal(guard.isValid(gen1, 'op-1', [0, 0.15]), true);
  assert.equal(guard.isValid(gen1, 'op-2', [0, 0.15]), false);
  assert.equal(guard.isValid(gen1, 'op-1', [0, 0.20]), false);
  const gen2 = guard.start('op-2', [0.15, 0]);
  assert.equal(guard.isValid(gen1, 'op-1', [0, 0.15]), false);
  assert.equal(guard.isValid(gen2, 'op-2', [0.15, 0]), true);
  guard.cancel();
  assert.equal(guard.isValid(gen2, 'op-2', [0.15, 0]), false);
});

test('G3 minimal panel mode is decided purely from the query string', () => {
  const { readPanelMode } = loadHelper();
  assert.equal(readPanelMode('?panel=min'), 'min');
  assert.equal(readPanelMode('panel=min'), 'min');
  assert.equal(readPanelMode('?other=1&panel=min&x=2'), 'min');
  assert.equal(readPanelMode(''), 'full');
  assert.equal(readPanelMode(undefined), 'full');
  assert.equal(readPanelMode(null), 'full');
  assert.equal(readPanelMode('?panel=full'), 'full');
  assert.equal(readPanelMode('?panel=MIN'), 'full');
  assert.equal(readPanelMode('?panel=minimal'), 'full');
});

test('G3 agent snapshot exposes the selection facts hidden from the minimal panel', () => {
  const { createIntentSession, buildAgentDetail } = loadHelper();
  const frame = liveBundle();
  const node = JSON.parse(frame.scene_json).nodes[0];
  const session = createIntentSession(frame);
  session.select('label');
  session.setDelta(0, 0.15);
  const detail = buildAgentDetail({
    node,
    title: '3.91 ppm',
    type: '文本',
    snapshot: session.snapshot(),
    frame,
    scene: JSON.parse(frame.scene_json),
    acceptedOperationIds: ['op-1']
  });
  assert.equal(detail.selected, 'label.391');
  assert.equal(detail.id, 'label');
  assert.equal(detail.title, '3.91 ppm');
  assert.equal(detail.type, '文本');
  assert.deepEqual(detail.bounds_mm, [10, 10, 30, 20]);
  assert.deepEqual(detail.delta_mm, [0, 0.15]);
  assert.equal(detail.status, 'DESIRED_ONLY');
  assert.equal(detail.can_evaluate, true);
  assert.equal(detail.frame_revision, frame.frame_revision);
  assert.equal(detail.source_revision, 'source-1');
  assert.equal(detail.session_id, 'session-1');
  assert.deepEqual(detail.accepted_operation_ids, ['op-1']);
  assert.equal(detail.evaluation, null);
  assert.equal(detail.schema, 'figpact.inspector.agent_detail/1');
  // the snapshot must not alias the live operation stack
  const ids = ['op-1'];
  buildAgentDetail({ node, acceptedOperationIds: ids }).accepted_operation_ids.push('op-9');
  assert.deepEqual(ids, ['op-1']);
});

test('G3 agent snapshot is explicit when nothing is selected and carries the last verdict', () => {
  const { createIntentSession, buildAgentDetail } = loadHelper();
  const empty = buildAgentDetail();
  assert.equal(empty.selected, null);
  assert.equal(empty.id, null);
  assert.equal(empty.title, null);
  assert.equal(empty.bounds_mm, null);
  assert.equal(empty.status, 'NO_SELECTION');
  assert.equal(empty.can_evaluate, false);
  assert.deepEqual(empty.delta_mm, [0, 0]);
  assert.deepEqual(empty.accepted_operation_ids, []);

  const frame = liveBundle();
  const node = JSON.parse(frame.scene_json).nodes[0];
  const session = createIntentSession(frame);
  session.select('label');
  session.setDelta(0, 0.15);
  const intent = session.snapshot().intent;
  const detail = buildAgentDetail({
    node,
    snapshot: session.snapshot(),
    frame,
    evaluation: {
      status: 'OK', operation_id: intent.operation_id, intent_state: 'READY', evaluation_state: 'FEASIBLE',
      verification_level: 'RENDER_CHECKED', persistence_state: 'EPHEMERAL', target_delta_mm: [0, 0.15],
      measured_delta_mm: [0, 0.15], error_mm: 0, checks: [{ check: 'science', status: 'PASS' }]
    }
  });
  assert.equal(detail.evaluation.verification_level, 'RENDER_CHECKED');
  assert.deepEqual(detail.evaluation.measured_delta_mm, [0, 0.15]);
  assert.equal(detail.evaluation.error_mm, 0);
  assert.deepEqual(detail.evaluation.checks, [{ check: 'science', status: 'PASS' }]);
  assert.deepEqual(detail.evaluation.target_delta_mm, [0, 0.15]);
});

test('G3 minimal status line stays one short line for every interaction state', () => {
  const { createIntentSession, minimalStatusText } = loadHelper();
  assert.equal(minimalStatusText({}), '未选择对象');
  assert.equal(minimalStatusText(null), '未选择对象');

  const frame = liveBundle();
  const node = JSON.parse(frame.scene_json).nodes[0];
  const session = createIntentSession(frame);
  session.select('label');
  assert.equal(minimalStatusText({ node, snapshot: session.snapshot() }), '方向键微调位置');

  session.setDelta(0, 0.15);
  const snapshot = session.snapshot();
  assert.equal(minimalStatusText({ node, snapshot }), '已上移 0.15 mm');

  const intent = snapshot.intent;
  const evaluation = {
    status: 'OK', operation_id: intent.operation_id, intent_state: 'READY', evaluation_state: 'FEASIBLE',
    verification_level: 'RENDER_CHECKED', target_delta_mm: [0, 0.15], measured_delta_mm: [0, 0.15], error_mm: 0,
    checks: [{ check: 'science', status: 'PASS' }]
  };
  assert.equal(minimalStatusText({ node, snapshot, evaluation }), '试算通过 · 实测 +0.150 mm');
  assert.equal(minimalStatusText({ node, snapshot, evaluation: { status: 'TARGET_MISMATCH' } }), '试算未通过 · TARGET_MISMATCH');

  session.setDelta(-150, 0);
  assert.equal(minimalStatusText({ node, snapshot: session.snapshot() }), '已左移 150 mm · 超出允许范围');
});

test('G3 stage resize triggers a refit only when the stage size really changed', () => {
  const { stageSizeChanged } = loadHelper();
  assert.equal(stageSizeChanged(null, 880, 719), true);
  assert.equal(stageSizeChanged({ width: 880, height: 719 }, 880, 719), false);
  assert.equal(stageSizeChanged({ width: 880, height: 719 }, 880, 745), true);
  assert.equal(stageSizeChanged({ width: 880, height: 719 }, 700, 719), true);
});

test('G3 arrow keys need the viewport in full mode but accept a focused host in minimal mode', () => {
  const { acceptsArrowKeys } = loadHelper();
  // full mode: unchanged judge — the canvas itself must hold focus
  assert.equal(acceptsArrowKeys({ activeElementIsViewport: true }), true);
  assert.equal(acceptsArrowKeys({ activeElementIsViewport: false }), false);
  assert.equal(acceptsArrowKeys({ activeElementIsViewport: false, hasDocumentFocus: true }), false);
  assert.equal(acceptsArrowKeys({}), false);
  // minimal mode: the host may keep focus on body/WebView after a native click
  assert.equal(acceptsArrowKeys({ minimal: true, activeElementIsViewport: true, hasDocumentFocus: true }), true);
  assert.equal(acceptsArrowKeys({ minimal: true, activeElementIsViewport: false, hasDocumentFocus: true }), true);
  assert.equal(acceptsArrowKeys({ minimal: true, activeElementIsViewport: false, hasDocumentFocus: false }), false);
  // a focused field always wins, in both modes
  assert.equal(acceptsArrowKeys({ minimal: true, activeElementIsViewport: true, hasDocumentFocus: true, inputActive: true }), false);
  assert.equal(acceptsArrowKeys({ minimal: true, activeElementIsViewport: false, hasDocumentFocus: true, inputActive: true }), false);
});

test('G5b selection sequence seeds above everything the hub already knows', () => {
  const { seedSelectionSeq } = loadHelper();
  // 刷新后计数器从 0 重来：hub_revision 与上次 selection_seq 里更大的那个必须被越过
  assert.equal(seedSelectionSeq({ hub_revision: 7, selection: { selection_seq: 5 } }, 0), 8);
  assert.equal(seedSelectionSeq({ hub_revision: 2, selection: { selection_seq: 9 } }, 0), 10);
  assert.equal(seedSelectionSeq({ hub_revision: 7, selection: null }, 3), 8);
  // 播种只上不下：本地已经在更高处时不许被 Hub 拉回去
  assert.equal(seedSelectionSeq({ hub_revision: 1 }, 500), 501);
  // 取不到 / 字段缺失 / 脏数据：本地计数器仍然递增（较大随机起点由调用方给）
  assert.equal(seedSelectionSeq(null, 4), 5);
  assert.equal(seedSelectionSeq({}, 4), 5);
  assert.equal(seedSelectionSeq(undefined, -5), 1);
  assert.equal(seedSelectionSeq({ hub_revision: null, selection: { selection_seq: '9' } }, 4), 5);
  assert.equal(seedSelectionSeq({ hub_revision: -3, selection: { selection_seq: 1.9 } }, 4), 5);
  // 重播前用 GET 的最新值再播种一次，结果必须严格大于刚读到的值
  const fresh = { hub_revision: 12, selection: { selection_seq: 11 } };
  const retry = seedSelectionSeq(fresh, 10);
  assert.equal(retry, 13);
  assert.ok(retry > fresh.hub_revision && retry > fresh.selection.selection_seq);
});

test('G5b reseed is attempted only for a real INVALID_SELECTION rejection', () => {
  const { shouldReseed } = loadHelper();
  assert.equal(shouldReseed(400, { status: 'INVALID_SELECTION', message: 'selection_seq 必须严格递增（当前 3）' }), true);
  assert.equal(shouldReseed(409, { status: 'INVALID_SELECTION' }), true);
  // 服务端其它拒绝理由重播也没用：不许瞎重试
  assert.equal(shouldReseed(400, { status: 'INVALID_INTENT', message: '必须使用 application/json' }), false);
  assert.equal(shouldReseed(415, { status: 'INVALID_INTENT' }), false);
  assert.equal(shouldReseed(409, { status: 'STALE_SELECTION' }), false);
  assert.equal(shouldReseed(500, { status: 'INVALID_SELECTION' }), false);
  assert.equal(shouldReseed(404, null), false);
  assert.equal(shouldReseed(200, { status: 'OK', selection_seq: 4 }), false);
});
