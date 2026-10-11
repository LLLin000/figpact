'use strict';

(function (root) {
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const point = (p) => Array.isArray(p) && p.length === 2 && p.every(finite);
  const box = (b) => Array.isArray(b) && b.length === 4 && b.every(finite) && b[2] >= b[0] && b[3] >= b[1];
  const hex = (v) => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  function requireFact(condition, message) { if (!condition) throw new Error(message); }

  function validateFrame(frame, expectedSourceRevision) {
    requireFact(frame && frame.schema === 'figpact.inspector/1', 'Unsupported frame schema');
    requireFact(['frame_revision', 'image_revision', 'geometry_revision', 'png_sha256', 'scene_sha256'].every(k => hex(frame[k])), 'Invalid revision or digest');
    requireFact(frame.frame_revision === frame.image_revision && frame.frame_revision === frame.geometry_revision, 'Stale image/geometry revision');
    requireFact(typeof frame.scene_json === 'string' && typeof frame.png_base64 === 'string', 'Missing frame data');
    const scene = JSON.parse(frame.scene_json);
    requireFact(scene.schema === 'figpact.inspector.scene/1' && scene.unit === 'mm' && scene.coordinate_reference === 'canvas_bottom_left', 'Invalid scene units/reference');
    requireFact(box(scene.canvas_bounds_mm) && scene.canvas_bounds_mm[2] > scene.canvas_bounds_mm[0] && scene.canvas_bounds_mm[3] > scene.canvas_bounds_mm[1], 'Invalid canvas bounds');
    requireFact(scene.source_revision === null || typeof scene.source_revision === 'string', 'Invalid source revision');
    if (expectedSourceRevision !== undefined) requireFact(scene.source_revision === expectedSourceRevision, 'Stale source revision; refresh required');
    requireFact(scene.measurement && scene.measurement.calibrated === false && finite(scene.measurement.dpi) && scene.measurement.dpi > 0, 'Missing uncalibrated measurement conditions');
    const image = scene.image;
    requireFact(image && Number.isInteger(image.width_px) && image.width_px > 0 && Number.isInteger(image.height_px) && image.height_px > 0 && box(image.bounds_mm), 'Invalid image dimensions');
    const pixelMm = 25.4 / scene.measurement.dpi;
    requireFact(Math.abs(image.bounds_mm[2] - image.bounds_mm[0] - image.width_px * pixelMm) < 1e-7 && Math.abs(image.bounds_mm[3] - image.bounds_mm[1] - image.height_px * pixelMm) < 1e-7, 'Image physical dimensions disagree with renderer DPI');
    requireFact(Array.isArray(scene.nodes), 'Missing scene objects');
    const ids = new Set();
    for (const node of scene.nodes) {
      requireFact(typeof node.id === 'string' && node.id && !ids.has(node.id), 'Duplicate/missing object identity');
      ids.add(node.id);
      requireFact(node.editable_capability === 'READ_ONLY', 'Inspector only accepts READ_ONLY objects');
      requireFact(node.bounds_mm == null || box(node.bounds_mm), 'Invalid object bounds');
      requireFact(node.runs_mm == null || (Array.isArray(node.runs_mm) && node.runs_mm.every(run => Array.isArray(run) && run.every(point))), 'Invalid polyline geometry');
      if (node.identity_stability !== undefined) requireFact(node.identity_stability === (node.registered ? 'stable' : 'ephemeral'), 'Identity registration/stability mismatch');
    }
    return scene;
  }

  async function sha256(bytes) {
    const subtle = root.crypto?.subtle || (typeof require === 'function' ? require('node:crypto').webcrypto.subtle : null);
    requireFact(subtle, 'WebCrypto unavailable; cannot verify frame');
    const digest = new Uint8Array(await subtle.digest('SHA-256', bytes));
    return Array.from(digest, v => v.toString(16).padStart(2, '0')).join('');
  }
  async function verifyFrame(frame, expectedSourceRevision) {
    const scene = validateFrame(frame, expectedSourceRevision);
    const png = Uint8Array.from(atob(frame.png_base64), c => c.charCodeAt(0));
    requireFact(png.length >= 24 && [137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => png[i] === v), 'Invalid PNG bytes');
    const header = new DataView(png.buffer, png.byteOffset, png.byteLength);
    requireFact(header.getUint32(16) === scene.image.width_px && header.getUint32(20) === scene.image.height_px, 'PNG pixel dimensions differ from scene');
    const encoder = new TextEncoder();
    const [pngHash, sceneHash] = await Promise.all([sha256(png), sha256(encoder.encode(frame.scene_json))]);
    requireFact(pngHash === frame.png_sha256, 'Stale png bytes; refresh required');
    requireFact(sceneHash === frame.scene_sha256, 'Stale scene bytes; refresh required');
    requireFact(await sha256(encoder.encode(`${pngHash}\n${sceneHash}`)) === frame.frame_revision, 'Broken frame revision chain');
    return scene;
  }

  function screenToMm(rect, bounds, clientX, clientY) {
    requireFact(rect && finite(rect.left) && finite(rect.top) && finite(rect.width) && rect.width > 0 && finite(rect.height) && rect.height > 0 && box(bounds) && bounds[2] > bounds[0] && bounds[3] > bounds[1], 'Invalid display rectangle');
    requireFact(finite(clientX) && finite(clientY), 'Invalid pointer coordinates');
    return { x: bounds[0] + (clientX - rect.left) / rect.width * (bounds[2] - bounds[0]), y: bounds[3] - (clientY - rect.top) / rect.height * (bounds[3] - bounds[1]) };
  }
  function distanceSquared(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, ((p.x - a[0]) * dx + (p.y - a[1]) * dy) / length)) : 0;
    return (p.x - a[0] - t * dx) ** 2 + (p.y - a[1] - t * dy) ** 2;
  }
  function hitCandidates(scene, p, cssPixelsPerMm, tolerancePx = 4) {
    requireFact(finite(cssPixelsPerMm) && cssPixelsPerMm > 0 && finite(tolerancePx) && tolerancePx >= 0 && finite(p.x) && finite(p.y), 'Invalid hit-test scale');
    const priority = { guide: 0, text: 10, legend: 10, image: 15, curve: 20, collection: 20, panel: 50 };
    const hits = [];
    for (const node of scene.nodes) {
      if (!node.measured || node.fully_clipped || node.type === 'figure' || node.type === 'group' || node.hit_mode === 'none') continue;
      let distance = Infinity;
      if (node.hit_mode === 'stroke' && Array.isArray(node.runs_mm) && !['none', ''].includes(String(node.linestyle).toLowerCase())) {
        const radius = (finite(node.linewidth_mm) ? Math.max(0, node.linewidth_mm) / 2 : 0) + tolerancePx / cssPixelsPerMm;
        const b = node.bounds_mm;
        if (box(b) && (p.x < b[0] - radius || p.x > b[2] + radius || p.y < b[1] - radius || p.y > b[3] + radius)) continue;
        let nearest = Infinity;
        for (const run of node.runs_mm) {
          let previous = null;
          for (const next of run) {
            if (!point(next)) { previous = null; continue; }
            if (previous) nearest = Math.min(nearest, distanceSquared(p, previous, next));
            previous = next;
          }
        }
        if (nearest <= radius * radius) distance = Math.sqrt(nearest);
      } else if (node.hit_mode === 'envelope' && box(node.bounds_mm)) {
        const b = node.bounds_mm;
        if (p.x >= b[0] && p.x <= b[2] && p.y >= b[1] && p.y <= b[3]) distance = 0;
      }
      if (finite(distance)) hits.push({ id: node.id, distance, priority: priority[node.type] ?? 30 });
    }
    hits.sort((a, b) => a.priority - b.priority || (Math.abs(a.distance - b.distance) > 1e-10 ? a.distance - b.distance : a.id.localeCompare(b.id)));
    return hits;
  }
  function cycleSelection(ids, selected, altKey) {
    if (!ids.length) return null;
    const current = ids.indexOf(selected);
    return altKey && current >= 0 ? ids[(current + 1) % ids.length] : ids[0];
  }
  function niceTickStep(mmPerCssPx) {
    requireFact(finite(mmPerCssPx) && mmPerCssPx > 0, 'Invalid ruler scale');
    const wanted = mmPerCssPx * 50;
    const base = 10 ** Math.floor(Math.log10(wanted));
    return [1, 2, 5, 10].map(n => n * base).find(n => n >= wanted) || base * 10;
  }

  const api = { validateFrame, verifyFrame, screenToMm, hitCandidates, cycleSelection, niceTickStep };
  root.FigpactInspector = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  const byId = id => document.getElementById(id);
  const container = byId('inspector-root'), viewport = byId('viewport'), wrap = byId('viewport-wrap');
  const state = { scene: null, nodes: new Map(), paths: new Map(), selected: null, hover: null, zoom: 1, scale: 1, ready: false, epoch: 0, space: false, pan: null };
  const svg = (tag, attrs = {}) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  };
  const title = node => node.text || node.gid || node.descriptor || `${node.type}: ${node.id}`;
  function status(message, kind) {
    byId('integrity-status').textContent = message;
    byId('integrity-status').className = `status status-${kind}`;
  }
  function fields(element, pairs) {
    element.replaceChildren();
    for (const [name, value] of pairs) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = name; dd.textContent = typeof value === 'string' ? value : JSON.stringify(value);
      element.append(dt, dd);
    }
  }
  function select(id) {
    state.selected = state.ready && state.nodes.has(id) ? id : null;
    container.dataset.selectedId = state.selected || '';
    const node = state.nodes.get(state.selected);
    byId('detail-empty').hidden = !!node;
    byId('detail-fields').hidden = !node;
    for (const id of ['detail-ephemeral', 'detail-readonly', 'detail-annotation']) byId(id).hidden = true;
    if (node) {
      fields(byId('detail-fields'), [['对象', title(node)], ['GID / 单帧 ID', node.gid || node.id], ['类型', node.type], ['身份', node.identity_stability], ['位置包络 mm', node.bounds_mm], ['锚点 mm', node.anchors], ['科学声明', node.science_policy || '未声明'], ['测量限制', node.hit_note || node.stroke?.limitation || '包络不等于复杂形状的精确轮廓']]);
      byId('detail-ephemeral').hidden = node.identity_stability !== 'ephemeral';
      byId('detail-ephemeral').textContent = '临时身份只在当前帧有效；重建后需要重新选择，不能用于持久编辑。';
      byId('detail-readonly').hidden = false;
      byId('detail-readonly').textContent = 'READ_ONLY：这里只能测量与选择，不修改图元、Python、YAML 或正式产物。';
      if (node.annotation || node.linked_guide_gid) {
        byId('detail-annotation').hidden = false;
        byId('detail-annotation').textContent = node.annotation
          ? `关联标签：${node.annotation.linked_label_gid}。科学锚点（ppm / a.u.）：${JSON.stringify(node.annotation.declared_guide_anchor_data)}；本帧显示首末端（mm）：${JSON.stringify([node.annotation.displayed_first_run_endpoint_mm, node.annotation.displayed_last_run_endpoint_mm])}。科学锚点固定，引线可随关联标签重建，本界面不能编辑或独立拖端点。`
          : `关联引线：${node.linked_guide_gid}。标签和引线是两个可分别选择的对象；本界面不编辑它们。`;
      }
    }
    highlights();
  }
  function outline(node, className) {
    if (!node || !node.measured || node.fully_clipped) return null;
    const height = state.scene.canvas_bounds_mm[3];
    if (node.hit_mode === 'stroke' && node.runs_mm) {
      if (!state.paths.has(node.id)) state.paths.set(node.id, node.runs_mm.map(run => run.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${height - p[1]}`).join(' ')).join(' '));
      const d = state.paths.get(node.id);
      return svg('path', { d, class: `outline ${className}`, 'pointer-events': 'none' });
    }
    if (box(node.bounds_mm)) {
      const b = node.bounds_mm;
      return svg('rect', { x: b[0], y: height - b[3], width: b[2] - b[0], height: b[3] - b[1], class: `outline ${className}`, 'pointer-events': 'none' });
    }
    return null;
  }
  function highlights() {
    const group = byId('highlights');
    if (!group) return;
    group.replaceChildren();
    for (const [id, style] of [[state.hover, 'hover-outline'], [state.selected, 'selected-outline']]) {
      const shape = outline(state.nodes.get(id), style);
      if (shape) group.append(shape);
    }
  }
  function objectList() {
    const query = byId('search-input').value.toLowerCase();
    const nodes = state.scene.nodes.filter(n => [n.id, n.gid, n.text, n.type, n.descriptor].some(v => String(v || '').toLowerCase().includes(query)));
    byId('object-list-count').textContent = `${nodes.length} / ${state.scene.nodes.length} 个对象；列表选择不会修改图件`;
    byId('object-list').replaceChildren();
    for (const node of nodes) {
      const li = document.createElement('li'), button = document.createElement('button');
      button.type = 'button'; button.textContent = `${title(node)} · ${node.identity_stability}`;
      button.dataset.nodeId = node.id; button.addEventListener('click', () => { select(node.id); listVisible(false); });
      li.append(button); byId('object-list').append(li);
    }
  }
  function rulers() {
    if (!state.scene) return;
    const [x0, y0, x1, y1] = state.scene.canvas_bounds_mm;
    const step = niceTickStep(1 / state.scale);
    const top = byId('ruler-top'), left = byId('ruler-left');
    top.replaceChildren(); left.replaceChildren();
    top.style.top = `${wrap.scrollTop}px`; top.style.left = `${wrap.scrollLeft + 18}px`; top.style.width = `${wrap.clientWidth - 18}px`;
    left.style.left = `${wrap.scrollLeft}px`; left.style.top = `${wrap.scrollTop + 18}px`; left.style.height = `${wrap.clientHeight - 18}px`;
    for (const [element, low, high, axis] of [[top, x0, x1, 'left'], [left, y0, y1, 'top']]) {
      for (let value = Math.ceil(low / step) * step; value <= high; value += step) {
        const offset = axis === 'left' ? (value - x0) * state.scale - wrap.scrollLeft : (y1 - value) * state.scale - wrap.scrollTop;
        const limit = axis === 'left' ? wrap.clientWidth : wrap.clientHeight;
        if (offset < -10 || offset > limit) continue;
        const tick = document.createElement('span'), label = document.createElement('span');
        tick.className = 'tick'; label.className = 'label';
        tick.style[axis] = label.style[axis] = `${offset}px`;
        label.textContent = `${Number(value.toFixed(4))} mm`;
        element.append(tick, label);
      }
    }
  }
  function fit() {
    if (!state.scene) return;
    const b = state.scene.canvas_bounds_mm, width = b[2] - b[0], height = b[3] - b[1];
    state.scale = Math.min(Math.max(100, wrap.clientWidth - 20) / width, Math.max(300, innerHeight - 270) / height) * state.zoom;
    viewport.setAttribute('width', width * state.scale); viewport.setAttribute('height', height * state.scale);
    rulers();
  }
  function zoom(factor) { state.zoom = Math.max(0.25, Math.min(16, state.zoom * factor)); fit(); }
  function candidates(event) {
    const rect = viewport.getBoundingClientRect();
    const p = screenToMm(rect, state.scene.canvas_bounds_mm, event.clientX, event.clientY);
    return hitCandidates(state.scene, p, rect.width / (state.scene.canvas_bounds_mm[2] - state.scene.canvas_bounds_mm[0]));
  }
  viewport.addEventListener('pointermove', event => {
    if (!state.ready) return;
    if (state.pan) {
      wrap.scrollLeft = state.pan.left - (event.clientX - state.pan.x);
      wrap.scrollTop = state.pan.top - (event.clientY - state.pan.y);
      state.pan.moved ||= Math.abs(event.clientX - state.pan.x) + Math.abs(event.clientY - state.pan.y) > 3;
      rulers(); return;
    }
    const hovered = candidates(event)[0]?.id || null;
    if (hovered === state.hover) return;
    state.hover = hovered;
    container.dataset.hoverId = state.hover || '';
    viewport.setAttribute('aria-description', state.hover ? title(state.nodes.get(state.hover)) : '无对象命中');
    highlights();
  });
  viewport.addEventListener('pointerleave', () => { state.hover = null; container.dataset.hoverId = ''; highlights(); });
  viewport.addEventListener('pointerdown', event => {
    if (!state.ready) return;
    viewport.focus();
    if (state.space || event.button === 1) {
      event.preventDefault(); viewport.setPointerCapture(event.pointerId);
      state.pan = { x: event.clientX, y: event.clientY, left: wrap.scrollLeft, top: wrap.scrollTop, moved: false };
      viewport.classList.add('panning');
    }
  });
  viewport.addEventListener('pointerup', event => {
    if (!state.ready) return;
    if (state.pan) { state.pan = null; viewport.classList.remove('panning'); return; }
    if (event.button === 0) select(cycleSelection(candidates(event).map(n => n.id), state.selected, event.altKey));
  });
  viewport.addEventListener('pointercancel', () => { state.pan = null; viewport.classList.remove('panning'); });
  wrap.addEventListener('scroll', rulers);
  wrap.addEventListener('wheel', event => {
    if (event.ctrlKey && state.ready) { event.preventDefault(); zoom(event.deltaY < 0 ? 1.25 : 0.8); }
  }, { passive: false });
  byId('zoom-in').addEventListener('click', () => zoom(1.25));
  byId('zoom-out').addEventListener('click', () => zoom(0.8));
  byId('view-reset').addEventListener('click', () => { state.zoom = 1; wrap.scrollLeft = wrap.scrollTop = 0; fit(); });
  const listVisible = show => {
    byId('object-list-panel').hidden = !show; byId('detail-panel').hidden = show;
    byId('toggle-list').setAttribute('aria-expanded', String(show));
  };
  byId('toggle-list').addEventListener('click', () => listVisible(byId('object-list-panel').hidden));
  byId('search-input').addEventListener('input', () => { if (state.ready) { objectList(); listVisible(true); } });
  byId('search-form').addEventListener('submit', event => event.preventDefault());
  document.addEventListener('keydown', event => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
    if (event.key === 'Escape') select(null);
    if (document.activeElement !== viewport) return;
    if (event.code === 'Space') { event.preventDefault(); state.space = true; }
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25); }
    if (event.key === '-') { event.preventDefault(); zoom(0.8); }
  });
  document.addEventListener('keyup', event => { if (event.code === 'Space') state.space = false; });
  root.addEventListener('blur', () => { state.space = false; state.pan = null; viewport.classList.remove('panning'); });
  root.addEventListener('resize', fit);

  async function loadFrame(frame, expectedSourceRevision) {
    const epoch = ++state.epoch;
    state.ready = false; state.scene = null; state.hover = state.selected = null; state.nodes.clear(); state.paths.clear();
    viewport.replaceChildren();
    byId('frame-scope').textContent = byId('frame-revision').textContent = '';
    byId('state-fields').replaceChildren(); byId('detail-fields').replaceChildren();
    byId('calibration-note').hidden = true;
    container.dataset.ready = 'false'; container.dataset.frameState = 'loading'; container.dataset.hoverId = container.dataset.selectedId = '';
    select(null); status('正在校验图像、几何与帧摘要…', 'pending');
    try {
      const scene = await verifyFrame(frame, expectedSourceRevision);
      const image = new Image();
      image.src = `data:image/png;base64,${frame.png_base64}`;
      await image.decode();
      requireFact(image.naturalWidth === scene.image.width_px && image.naturalHeight === scene.image.height_px, 'Decoded PNG dimensions mismatch');
      if (epoch !== state.epoch) return;
      state.scene = scene; state.nodes = new Map(scene.nodes.map(node => [node.id, node])); state.zoom = 1;
      const b = scene.canvas_bounds_mm, ib = scene.image.bounds_mm;
      viewport.setAttribute('viewBox', `${b[0]} 0 ${b[2] - b[0]} ${b[3] - b[1]}`);
      viewport.append(svg('image', { x: ib[0], y: b[3] - ib[3], width: ib[2] - ib[0], height: ib[3] - ib[1], href: image.src, preserveAspectRatio: 'none' }));
      viewport.append(svg('g', { id: 'highlights' }));
      state.ready = true; container.dataset.ready = 'true'; container.dataset.frameState = 'verified';
      byId('frame-scope').textContent = scene.scope;
      byId('frame-revision').textContent = frame.frame_revision.slice(0, 12);
      byId('calibration-note').hidden = false;
      byId('calibration-note').textContent = 'calibrated=false：标尺是 renderer / 导出页面毫米，不是显示器的实际毫米；折线为中心线模型，文字为保守包络。固定快照：源文件改变后请重新导出，不提供实时源码监控或 strict 验收。';
      fields(byId('state-fields'), [['renderer', scene.measurement.renderer || '未声明'], ['DPI', scene.measurement.dpi], ['source revision', scene.source_revision || '无 YAML / 未提供'], ['诊断', scene.diagnostics?.length || 0]]);
      status('同帧摘要与 PNG 尺寸核对通过 · 只读快照', 'ok');
      wrap.scrollLeft = wrap.scrollTop = 0; fit(); objectList();
    } catch (error) {
      if (epoch !== state.epoch) return;
      state.ready = false; container.dataset.ready = 'false'; container.dataset.frameState = 'invalid'; select(null);
      status(`不可使用：${error.message}；请重新导出或刷新。`, 'error');
    }
  }
  api.loadFrame = loadFrame;
  loadFrame(root.FIGPACT_INSPECTOR_FRAME, root.FIGPACT_INSPECTOR_EXPECTED_SOURCE_REVISION);
})(globalThis);
