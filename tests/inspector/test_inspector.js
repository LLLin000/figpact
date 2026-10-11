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
