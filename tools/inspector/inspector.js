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
    if (frame.session != null) {
      requireFact(typeof frame.session === 'object', 'Invalid session metadata');
      requireFact(typeof frame.session.session_id === 'string' && frame.session.session_id, 'Invalid session id');
      requireFact(frame.session.scene_revision === frame.frame_revision, 'Stale session scene revision; refresh required');
      requireFact(frame.session.source_revision === scene.source_revision, 'Stale session source revision; refresh required');
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
  function fitViewport(bounds, wrapWidth, wrapHeight, zoom = 1) {
    requireFact(box(bounds) && bounds[2] > bounds[0] && bounds[3] > bounds[1], 'Invalid bounds');
    requireFact(finite(wrapWidth) && wrapWidth > 0 && finite(wrapHeight) && wrapHeight > 0, 'Invalid wrap dimensions');
    requireFact(finite(zoom) && zoom > 0, 'Invalid zoom');
    const margin = 18;
    const availW = Math.max(0, wrapWidth - margin);
    const availH = Math.max(0, wrapHeight - margin);
    const w = bounds[2] - bounds[0];
    const h = bounds[3] - bounds[1];
    const scale = Math.min(availW / w, availH / h) * zoom;
    const width = w * scale;
    const height = h * scale;
    const left = margin + Math.max(0, (availW - width) / 2);
    const top = margin + Math.max(0, (availH - height) / 2);
    return { scale, width, height, left, top };
  }
  function zoomViewport(before, after, scroll = { left: 0, top: 0 }, anchor) {
    requireFact(before && after, 'Invalid before/after viewport');
    const curScroll = scroll || { left: 0, top: 0 };
    const anc = anchor || { x: before.left + before.width / 2, y: before.top + before.height / 2 };
    const ratioX = (anc.x - (before.left - (curScroll.left || 0))) / before.width;
    const ratioY = (anc.y - (before.top - (curScroll.top || 0))) / before.height;
    return {
      left: after.left + ratioX * after.width - anc.x,
      top: after.top + ratioY * after.height - anc.y
    };
  }
  function canAcceptEvaluation(response, intent) {
    if (!response || !intent) return false;
    if (response.status !== 'OK') return false;
    if (response.operation_id !== intent.operation_id) return false;
    if (response.intent_state !== 'READY') return false;
    if (response.evaluation_state !== 'FEASIBLE') return false;
    if (response.verification_level !== 'RENDER_CHECKED') return false;
    if (!Array.isArray(response.target_delta_mm) || !Array.isArray(response.measured_delta_mm)) return false;
    const tol = intent.tolerance_mm ?? 0.01;
    if (Math.abs(response.measured_delta_mm[0] - intent.delta_mm[0]) > tol ||
        Math.abs(response.measured_delta_mm[1] - intent.delta_mm[1]) > tol) return false;
    if (response.error_mm != null && response.error_mm > tol) return false;
    if (!Array.isArray(response.checks) || response.checks.length === 0) return false;
    if (response.checks.some(c => c.status !== 'PASS')) return false;
    return true;
  }
  function createIntentSession(frame) {
    const scene = typeof frame.scene_json === 'string' ? JSON.parse(frame.scene_json) : (frame.scene || {});
    const nodesMap = new Map((scene.nodes || []).map(n => [n.id, n]));
    let selectedId = null;
    let currentDelta = [0, 0];
    let operationId = null;
    let selectionBlocked = false;
    function round4(v) { return Math.round(v * 10000) / 10000; }
    function getSelectedNode() { return selectedId ? nodesMap.get(selectedId) || null : null; }
    function canNodeGhost(node) {
      if (!node || !node.measured || node.fully_clipped) return false;
      if (node.type === 'curve' || node.type === 'guide' || node.type === 'panel') return false;
      return true;
    }
    function select(id) {
      if (id === selectedId) { selectionBlocked = false; return true; }
      const hasPendingIntent = (currentDelta[0] !== 0 || currentDelta[1] !== 0) && selectedId != null;
      if (hasPendingIntent) { selectionBlocked = true; return false; }
      selectionBlocked = false;
      selectedId = id != null && nodesMap.has(id) ? id : null;
      return true;
    }
    function press(event) {
      if (!event || !event.viewportFocused) return false;
      if (event.inputActive || event.ctrlKey || event.metaKey) return false;
      const node = getSelectedNode();
      if (!canNodeGhost(node)) return false;
      const key = event.key;
      let step = event.shiftKey ? 0.5 : (event.altKey ? 0.01 : 0.1);
      let dx = 0, dy = 0;
      if (key === 'ArrowUp') dy = step;
      else if (key === 'ArrowDown') dy = -step;
      else if (key === 'ArrowRight') dx = step;
      else if (key === 'ArrowLeft') dx = -step;
      else return false;
      if (!operationId) {
        operationId = 'intent-' + (globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2, 11));
      }
      currentDelta = [round4(currentDelta[0] + dx), round4(currentDelta[1] + dy)];
      selectionBlocked = false;
      return true;
    }
    function setDelta(dx, dy) {
      const node = getSelectedNode();
      if (!canNodeGhost(node)) return false;
      if (!operationId && (dx !== 0 || dy !== 0)) {
        operationId = 'intent-' + (globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2, 11));
      }
      currentDelta = [round4(dx), round4(dy)];
      selectionBlocked = false;
      return true;
    }
    function cancel() {
      currentDelta = [0, 0];
      operationId = null;
      selectionBlocked = false;
    }
    function snapshot() {
      const node = getSelectedNode();
      const hasDelta = currentDelta[0] !== 0 || currentDelta[1] !== 0;
      const canEval = !!(frame.session?.can_evaluate && node?.registered && node?.identity_stability === 'stable');
      let ghost = null;
      let status = 'DESIRED_ONLY';
      if (node && canNodeGhost(node) && hasDelta) {
        const b = node.bounds_mm;
        const dx = currentDelta[0], dy = currentDelta[1];
        const ghostBounds = box(b) ? [round4(b[0] + dx), round4(b[1] + dy), round4(b[2] + dx), round4(b[3] + dy)] : null;
        ghost = { bounds_mm: ghostBounds };
        if (node.linked_guide_gid) {
          const guideNode = (scene.nodes || []).find(n => n.gid === node.linked_guide_gid || n.id === node.linked_guide_gid);
          if (guideNode && Array.isArray(guideNode.runs_mm)) {
            ghost.guide_runs_mm = guideNode.runs_mm.map(run => {
              if (!Array.isArray(run) || run.length === 0) return run;
              return run.map((p, idx) => {
                if (idx === run.length - 1) return [round4(p[0] + dx), round4(p[1] + dy)];
                return [p[0], p[1]];
              });
            });
          }
        }
        if (ghostBounds && box(scene.canvas_bounds_mm)) {
          const [cx0, cy0, cx1, cy1] = scene.canvas_bounds_mm;
          if (ghostBounds[0] < cx0 || ghostBounds[1] < cy0 || ghostBounds[2] > cx1 || ghostBounds[3] > cy1) {
            status = 'OUT_OF_RANGE';
          }
        }
      }
      let intent = null;
      if (node && hasDelta) {
        intent = {
          operation_id: operationId,
          session_id: frame.session?.session_id || null,
          scene_revision: frame.frame_revision,
          source_revision: scene.source_revision,
          scope: scene.scope,
          target_gid: node.gid || node.id,
          operation: 'translate',
          delta_mm: [currentDelta[0], currentDelta[1]],
          tolerance_mm: 0.01,
          preserve: {
            science: true,
            follow_gids: node.linked_guide_gid ? [node.linked_guide_gid] : [],
            fixed_gids: []
          },
          demonstration: { display_only: true }
        };
      }
      return { selected: selectedId, selectionBlocked, canEvaluate: canEval, status, intent, ghost };
    }
    return { select, press, setDelta, cancel, snapshot };
  }
  function buildDecisionPayload(frame, operationId, decision) {
    requireFact(frame && typeof frame === 'object', 'Invalid frame');
    requireFact(frame.session && typeof frame.session.session_id === 'string', 'Frame must contain live session');
    requireFact(typeof operationId === 'string' && operationId.length > 0, 'Invalid operation_id');
    requireFact(['accept', 'cancel', 'undo'].includes(decision), 'Invalid decision');
    const scene = typeof frame.scene_json === 'string' ? JSON.parse(frame.scene_json) : (frame.scene || {});
    return {
      operation_id: operationId,
      decision,
      session_id: frame.session.session_id,
      scene_revision: frame.frame_revision,
      source_revision: scene.source_revision
    };
  }
  function createOperationStack(initialIds = []) {
    const stack = Array.isArray(initialIds) ? [...initialIds] : [];
    return {
      push(id) { if (typeof id === 'string' && id) stack.push(id); },
      pop() { return stack.length > 0 ? stack.pop() : null; },
      peek() { return stack.length > 0 ? stack[stack.length - 1] : null; },
      canUndo() { return stack.length > 0; },
      all() { return [...stack]; }
    };
  }
  function isDecisionSuccessful(response) {
    return !!(response && typeof response === 'object' && response.status === 'OK');
  }
  function createInFlightGuard() {
    let currentToken = 0;
    let expectedOp = null;
    let expectedDelta = null;
    return {
      start(opId, delta) {
        currentToken++;
        expectedOp = opId;
        expectedDelta = Array.isArray(delta) ? [delta[0], delta[1]] : null;
        return currentToken;
      },
      isValid(token, opId, delta) {
        if (token !== currentToken) return false;
        if (opId !== expectedOp) return false;
        if (!expectedDelta || !Array.isArray(delta)) return false;
        return expectedDelta[0] === delta[0] && expectedDelta[1] === delta[1];
      },
      cancel() {
        currentToken++;
        expectedOp = null;
        expectedDelta = null;
      }
    };
  }

  const api = { validateFrame, verifyFrame, screenToMm, hitCandidates, cycleSelection, niceTickStep, fitViewport, zoomViewport, createIntentSession, canAcceptEvaluation, buildDecisionPayload, createOperationStack, isDecisionSuccessful, createInFlightGuard };
  const globalScope = typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : root);
  globalScope.FigpactInspector = api;
  root.FigpactInspector = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  const byId = id => document.getElementById(id);
  const container = byId('inspector-root'), viewport = byId('viewport'), wrap = byId('viewport-wrap');
  if (!container || !viewport || !wrap) return;
  const state = {
    frame: null,
    scene: null,
    acceptedFrame: null,
    candidateFrame: null,
    nodes: new Map(),
    paths: new Map(),
    selected: null,
    hover: null,
    zoom: 1,
    scale: 1,
    view: null,
    ready: false,
    epoch: 0,
    space: false,
    pan: null,
    intentSession: null,
    lastEvaluation: null,
    operationStack: createOperationStack(),
    inFlightGuard: createInFlightGuard(),
    pendingOperationId: null
  };
  const svg = (tag, attrs = {}) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  };

  function formatScientificText(raw) {
    if (!raw || typeof raw !== 'string') return '';
    const subMap = { '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉', '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎', 'a': 'ₐ', 'e': 'ₑ', 'o': 'ₒ', 'x': 'ₓ', 'h': 'ₕ', 'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'p': 'ₚ', 's': 'ₛ', 't': 'ₜ' };
    const superMap = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾', 'n': 'ⁿ', 'i': 'ⁱ' };
    return raw
      .replace(/_\{([^}]+)\}/g, (_, chars) => chars.split('').map(c => subMap[c] || c).join(''))
      .replace(/\^\{([^}]+)\}/g, (_, chars) => chars.split('').map(c => superMap[c] || c).join(''))
      .replace(/_([0-9a-zA-Z])/g, (_, c) => subMap[c.toLowerCase()] || c)
      .replace(/\^([0-9])/g, (_, c) => superMap[c] || c)
      .replace(/\$/g, '');
  }

  function displayTitle(node) {
    if (!node) return '未命名图元';
    if (node.text) {
      const clean = formatScientificText(node.text);
      if (node.annotation && node.annotation.declared_exact_ppm) {
        return `${clean} (${Number(node.annotation.declared_exact_ppm.toFixed(2))} ppm)`;
      }
      return clean;
    }
    if (node.type === 'guide') {
      if (node.annotation && node.annotation.declared_exact_ppm) {
        return `峰位引线 (${Number(node.annotation.declared_exact_ppm.toFixed(2))} ppm)`;
      }
      return '峰位引导线';
    }
    if (node.gid) {
      if (node.gid.includes('3p91') || node.gid.includes('3.91')) {
        return `${node.type === 'guide' ? '引线' : '图元'} · 3.91 ppm`;
      }
      return node.gid;
    }
    return node.descriptor || `${node.type}: ${node.id}`;
  }

  const title = node => node.text || node.gid || node.descriptor || `${node.type}: ${node.id}`;

  function status(message, kind) {
    const el = byId('integrity-status');
    if (!el) return;
    el.textContent = message;
    el.className = `status status-${kind}`;
  }
  function fields(element, pairs) {
    if (!element) return;
    element.replaceChildren();
    for (const [name, value] of pairs) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = name; dd.textContent = typeof value === 'string' ? value : JSON.stringify(value);
      element.append(dt, dd);
    }
  }

  function updateIntentUI() {
    const section = byId('intent-section');
    if (!section) return;
    const node = state.nodes.get(state.selected);
    if (!state.intentSession) {
      section.hidden = true;
      return;
    }
    const canUndo = state.operationStack.canUndo();
    section.hidden = !node && !canUndo && !state.pendingOperationId;
    byId('intent-notice').hidden = true;

    if (!node) {
      byId('intent-status-badge').textContent = canUndo ? '会话已就绪' : '未选中图元';
      byId('intent-status-badge').className = 'tag';
      byId('intent-displacement').textContent = '位移：未选中图元';
      byId('intent-dx').value = 0;
      byId('intent-dx').disabled = true;
      byId('intent-dy').value = 0;
      byId('intent-dy').disabled = true;
      byId('btn-apply-delta').disabled = true;
      byId('btn-evaluate').disabled = true;
      byId('btn-evaluate').title = '请先选中可调整图元';
      byId('btn-accept').disabled = true;
      byId('btn-accept').title = '需先完成试算并通过验证';
      byId('btn-cancel-intent').disabled = true;
      byId('btn-undo').disabled = !canUndo;
      byId('btn-undo').title = canUndo ? `可撤销会话中的上一步操作 (${state.operationStack.peek()})` : '当前没有可撤销的操作';
      return;
    }

    const canGhost = !(node.type === 'guide' || node.type === 'curve' || node.type === 'panel' || !node.measured || node.fully_clipped);
    byId('intent-dx').disabled = !canGhost;
    byId('intent-dy').disabled = !canGhost;
    byId('btn-apply-delta').disabled = !canGhost;

    const snap = state.intentSession.snapshot();
    let plainStatus = '示范中（未进行排版试算）';
    let statusClass = 'tag';
    if (!canGhost) {
      if (node.type === 'guide') {
        plainStatus = '引线不支持独立编辑';
        byId('btn-apply-delta').title = '移动标签时引线会自动调整，不能单独移动引线';
      } else if (node.type === 'curve') {
        plainStatus = '科学数据曲线不可编辑';
        byId('btn-apply-delta').title = '科学数据曲线受保护，不可编辑';
      } else {
        plainStatus = '图元不支持位置调整';
        byId('btn-apply-delta').title = '该图元不支持位置调整';
      }
    } else if (snap.status === 'OUT_OF_RANGE') {
      plainStatus = '超出允许范围 (±10 mm)';
      statusClass = 'tag tag-warning';
    } else if (state.lastEvaluation) {
      if (canAcceptEvaluation(state.lastEvaluation, snap.intent)) {
        plainStatus = '真实渲染几何检验通过（待接受到会话）';
        statusClass = 'tag tag-success';
      } else {
        plainStatus = `试算未通过 (${state.lastEvaluation.status || '未通过'})`;
        statusClass = 'tag tag-warning';
      }
    }
    byId('intent-status-badge').textContent = plainStatus;
    byId('intent-status-badge').className = statusClass;

    const delta = snap.intent ? snap.intent.delta_mm : [0, 0];
    byId('intent-displacement').textContent = `位移：ΔX ${delta[0]} mm, ΔY ${delta[1]} mm`;
    byId('intent-dx').value = delta[0];
    byId('intent-dy').value = delta[1];

    const canEval = state.ready && snap.canEvaluate;
    byId('btn-evaluate').disabled = !canEval || (delta[0] === 0 && delta[1] === 0);
    byId('btn-accept').disabled = !state.ready || !(state.lastEvaluation && canAcceptEvaluation(state.lastEvaluation, snap.intent));
    const hasCancelable = (delta[0] !== 0 || delta[1] !== 0) || !!state.pendingOperationId || !!state.lastEvaluation || !!state.candidateFrame;
    byId('btn-cancel-intent').disabled = !hasCancelable;

    if (!canEval) {
      byId('btn-evaluate').title = '未注册或临时身份图元不支持真实排版试算';
      byId('btn-accept').title = '需先通过试算验证，且仅能接受到当前会话，不写回文件';
    } else {
      byId('btn-evaluate').title = '对当前示范位移执行真实排版重建与几何安全性检验';
      byId('btn-accept').title = '将通过验证的调整应用到当前交互会话（不修改源文件）';
    }
    byId('btn-undo').disabled = !canUndo;
    byId('btn-undo').title = canUndo ? `可撤销会话中的上一步操作 (${state.operationStack.peek()})` : '当前没有可撤销的操作';
  }

  function select(id) {
    if (!state.ready) return;
    if (state.pendingOperationId && id !== state.selected) {
      status('当前有正在调整的候选图元；请先在检查器中接受到会话或取消候选，再选择其他图元', 'pending');
      return;
    }
    if (state.intentSession) {
      const allowed = state.intentSession.select(id);
      if (!allowed) {
        const snap = state.intentSession.snapshot();
        byId('intent-notice').hidden = false;
        byId('intent-notice').textContent = `当前图元存在未处理的示范偏移（ΔX ${snap.intent?.delta_mm[0]} mm, ΔY ${snap.intent?.delta_mm[1]} mm）。请先在检查器中接受或取消当前示范，再选择其他图元。`;
        return;
      }
    }
    state.selected = state.nodes.has(id) ? id : null;
    container.dataset.selectedId = state.selected || '';
    const node = state.nodes.get(state.selected);
    byId('detail-empty').hidden = !!node;
    byId('detail-fields').hidden = !node;
    for (const nid of ['detail-ephemeral', 'detail-readonly', 'detail-annotation']) byId(nid).hidden = true;
    if (node) {
      const sessionObj = state.acceptedFrame?.session || state.frame?.session;
      const canRebuild = !!(sessionObj && sessionObj.can_evaluate !== false && sessionObj.source_revision);
      const cleanTitle = displayTitle(node);
      const rawText = node.text || null;
      const detailPairs = [
        ['图元名称', cleanTitle],
        ['图元类型', node.type === 'text' ? '文本标签' : (node.type === 'guide' ? '引导线' : (node.type === 'curve' ? '数据曲线' : node.type))],
        ['显示位置/尺寸', node.bounds_mm ? `[${node.bounds_mm.map(v => Number(v.toFixed(3))).join(', ')}] (${Number((node.bounds_mm[2] - node.bounds_mm[0]).toFixed(3))} × ${Number((node.bounds_mm[3] - node.bounds_mm[1]).toFixed(3))} mm)` : '无外包络'],
        ['标识稳定性', node.identity_stability === 'stable' ? '稳定标识（支持排版调整）' : '临时图元（仅当前视图有效）'],
        ['关联关系', node.linked_guide_gid ? `关联引线: ${node.linked_guide_gid}` : (node.annotation ? `关联标签: ${node.annotation.linked_label_gid}` : '无关联')],
        ['保护模式', canRebuild ? '会话调整模式（磁盘源文件受保护）' : '只读测量模式（不可编辑）']
      ];
      if (rawText && rawText !== cleanTitle) {
        detailPairs.push(['原始科学文本', rawText]);
      }
      detailPairs.push(['全局标识 (GID)', node.gid || node.id]);
      fields(byId('detail-fields'), detailPairs);

      byId('detail-ephemeral').hidden = node.identity_stability !== 'ephemeral';
      byId('detail-ephemeral').textContent = '该图元属于普通绘制元素，仅在当前画面有效；缺少永久配置，不支持真实试算与调整。';
      byId('detail-readonly').hidden = false;
      byId('detail-readonly').textContent = canRebuild
        ? '会话调整模式：可在当前会话中试算与临时应用布局；源码、配置文件及正式图件均处于受保护状态，不会被修改。'
        : '只读测量模式：本图件为普通图形或静态快照，仅支持精确测量与示范，不修改源码、YAML 或输出图件。';
      if (node.annotation || node.linked_guide_gid) {
        byId('detail-annotation').hidden = false;
        if (node.annotation) {
          byId('detail-annotation').textContent = '移动标签时，引线会跟着调整；指向峰的位置不变。这里不能单独移动引线。' +
            `（关联标签：${node.annotation.linked_label_gid} · 峰位锚点：${JSON.stringify(node.annotation.declared_guide_anchor_data)}）`;
        } else {
          byId('detail-annotation').textContent = `已关联引线：${node.linked_guide_gid}。平移本标签时，引线会自动调整并保持指向峰位。`;
        }
      }
    }
    updateIntentUI();
    highlights();
    if (byId('object-list')) {
      for (const btn of byId('object-list').querySelectorAll('button')) {
        btn.setAttribute('aria-current', String(btn.dataset.nodeId === state.selected));
      }
    }
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
    if (state.intentSession) {
      const snap = state.intentSession.snapshot();
      if (snap.ghost && state.scene) {
        const height = state.scene.canvas_bounds_mm[3];
        if (snap.ghost.bounds_mm) {
          const gb = snap.ghost.bounds_mm;
          group.append(svg('rect', {
            x: gb[0],
            y: height - gb[3],
            width: gb[2] - gb[0],
            height: gb[3] - gb[1],
            class: 'outline ghost-outline',
            'pointer-events': 'none'
          }));
        }
        if (Array.isArray(snap.ghost.guide_runs_mm)) {
          for (const run of snap.ghost.guide_runs_mm) {
            if (Array.isArray(run) && run.length > 0) {
              const d = run.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${height - p[1]}`).join(' ');
              group.append(svg('path', {
                d,
                class: 'outline ghost-guide-outline',
                'pointer-events': 'none'
              }));
            }
          }
        }
      }
    }
  }

  function objectList() {
    const query = byId('search-input').value.toLowerCase();
    const nodes = state.scene.nodes.filter(n => [n.id, n.gid, n.text, n.type, n.descriptor].some(v => String(v || '').toLowerCase().includes(query)));
    byId('object-list-count').textContent = `共 ${nodes.length} 个图元（总计 ${state.scene.nodes.length} 个）`;
    byId('object-list').replaceChildren();
    for (const node of nodes) {
      const li = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.nodeId = node.id;
      button.setAttribute('aria-current', String(node.id === state.selected));

      const titleSpan = document.createElement('span');
      titleSpan.className = 'name';
      titleSpan.textContent = displayTitle(node);
      const metaSpan = document.createElement('span');
      metaSpan.className = 'meta';
      metaSpan.textContent = `${node.type === 'text' ? '文本' : (node.type === 'guide' ? '引线' : (node.type === 'curve' ? '曲线' : node.type))} · ${node.identity_stability === 'stable' ? '稳定' : '临时'}`;
      button.append(titleSpan, metaSpan);

      button.addEventListener('click', () => {
        select(node.id);
        if (window.innerWidth < 960) listVisible(false);
      });
      li.append(button);
      byId('object-list').append(li);
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
    const viewLeft = state.view ? state.view.left : 18;
    const viewTop = state.view ? state.view.top : 18;
    for (const [element, low, high, axis] of [[top, x0, x1, 'left'], [left, y0, y1, 'top']]) {
      for (let value = Math.ceil(low / step) * step; value <= high; value += step) {
        const offset = axis === 'left' ? viewLeft + (value - x0) * state.scale - wrap.scrollLeft : viewTop + (y1 - value) * state.scale - wrap.scrollTop;
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
    if (!state.scene || !wrap.clientWidth || !wrap.clientHeight) return;
    const view = fitViewport(state.scene.canvas_bounds_mm, wrap.clientWidth, wrap.clientHeight, state.zoom);
    state.scale = view.scale;
    state.view = view;
    viewport.setAttribute('width', view.width);
    viewport.setAttribute('height', view.height);
    viewport.style.position = 'absolute';
    viewport.style.left = `${view.left}px`;
    viewport.style.top = `${view.top}px`;
    rulers();
  }

  function zoomWithAnchor(factor, anchor) {
    if (!state.scene) return;
    const bounds = state.scene.canvas_bounds_mm;
    const curZoom = state.zoom;
    const nextZoom = Math.max(0.25, Math.min(16, curZoom * factor));
    if (curZoom === nextZoom) return;
    const before = fitViewport(bounds, wrap.clientWidth, wrap.clientHeight, curZoom);
    const after = fitViewport(bounds, wrap.clientWidth, wrap.clientHeight, nextZoom);
    const anc = anchor || { x: wrap.clientWidth / 2, y: wrap.clientHeight / 2 };
    const nextScroll = zoomViewport(before, after, { left: wrap.scrollLeft, top: wrap.scrollTop }, anc);
    state.zoom = nextZoom;
    fit();
    wrap.scrollLeft = nextScroll.scrollLeft;
    wrap.scrollTop = nextScroll.scrollTop;
  }
  function zoom(factor) {
    zoomWithAnchor(factor, { x: wrap.clientWidth / 2, y: wrap.clientHeight / 2 });
  }

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
    viewport.setAttribute('aria-description', state.hover ? displayTitle(state.nodes.get(state.hover)) : '无对象命中');
    highlights();
  });
  viewport.addEventListener('pointerleave', () => { state.hover = null; container.dataset.hoverId = ''; highlights(); });
  viewport.addEventListener('pointerdown', event => {
    if (!state.ready) return;
    viewport.focus({ preventScroll: true });
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
    if ((event.ctrlKey || event.metaKey) && state.ready) {
      event.preventDefault();
      const wrapRect = wrap.getBoundingClientRect();
      zoomWithAnchor(event.deltaY < 0 ? 1.25 : 0.8, {
        x: event.clientX - wrapRect.left,
        y: event.clientY - wrapRect.top
      });
    }
  }, { passive: false });
  byId('zoom-in').addEventListener('click', () => zoom(1.25));
  byId('zoom-out').addEventListener('click', () => zoom(0.8));
  byId('view-reset').addEventListener('click', () => { state.zoom = 1; wrap.scrollLeft = wrap.scrollTop = 0; fit(); });

  const listVisible = show => {
    byId('object-list-panel').hidden = !show;
    byId('toggle-list').setAttribute('aria-expanded', String(show));
    byId('toggle-list').classList.toggle('active', show);
    fit();
  };
  byId('toggle-list').addEventListener('click', () => listVisible(byId('object-list-panel').hidden));
  byId('search-input').addEventListener('input', () => { if (state.ready) { objectList(); listVisible(true); } });
  byId('search-form').addEventListener('submit', event => event.preventDefault());

  document.addEventListener('keydown', event => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      cancelIntent(true);
      return;
    }
    if (document.activeElement !== viewport) return;
    if (event.code === 'Space') { event.preventDefault(); state.space = true; }
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25); }
    if (event.key === '-') { event.preventDefault(); zoom(0.8); }
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      if (state.intentSession && state.selected) {
        event.preventDefault();
        state.inFlightGuard.cancel();
        const handled = state.intentSession.press({
          key: event.key,
          altKey: event.altKey,
          shiftKey: event.shiftKey,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          repeat: event.repeat,
          viewportFocused: true,
          inputActive: false
        });
        if (handled) {
          state.lastEvaluation = null;
          updateIntentUI();
          highlights();
        }
      }
    }
  });
  document.addEventListener('keyup', event => { if (event.code === 'Space') state.space = false; });
  byId('btn-apply-delta').addEventListener('click', () => {
    if (!state.intentSession || !state.selected) return;
    state.inFlightGuard.cancel();
    const dx = parseFloat(byId('intent-dx').value) || 0;
    const dy = parseFloat(byId('intent-dy').value) || 0;
    state.intentSession.setDelta(dx, dy);
    state.lastEvaluation = null;
    updateIntentUI();
    highlights();
  });

  async function cancelIntent(notifyBackend = true) {
    if (!state.intentSession) return;
    const selectedId = state.selected;
    const snap = state.intentSession.snapshot();
    const opId = snap.intent?.operation_id || state.pendingOperationId || state.lastEvaluation?.operation_id;
    state.inFlightGuard.cancel();

    if (notifyBackend && opId && (state.acceptedFrame?.session || state.frame?.session)) {
      status('正在向本地服务取消当前候选…', 'pending');
      try {
        const baseline = state.acceptedFrame || state.frame;
        const payload = buildDecisionPayload(baseline, opId, 'cancel');
        const res = await fetch('/api/intents/decision', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!isDecisionSuccessful(data)) {
          status(`取消操作未通过：${data.message || data.status}`, 'error');
          return;
        }
        if (data.accepted_frame) {
          state.acceptedFrame = data.accepted_frame;
        }
      } catch (e) {
        status(`取消请求连接失败：${e.message}`, 'error');
        return;
      }
    }

    state.pendingOperationId = null;
    state.intentSession.cancel();
    state.lastEvaluation = null;
    byId('intent-eval-results').hidden = true;
    if (state.candidateFrame && state.acceptedFrame) {
      await loadFrame(state.acceptedFrame, undefined, true);
      select(selectedId);
    }
    updateIntentUI();
    highlights();
    status('已取消当前候选；之前已接受的操作继续保持生效', 'ok');
  }
  byId('btn-cancel-intent').addEventListener('click', () => {
    cancelIntent(true);
  });

  byId('btn-evaluate').addEventListener('click', async () => {
    if (!state.intentSession) return;
    const snap = state.intentSession.snapshot();
    if (!snap.intent || !snap.canEvaluate) return;
    state.pendingOperationId = snap.intent.operation_id;
    const token = state.inFlightGuard.start(snap.intent.operation_id, snap.intent.delta_mm);
    byId('btn-evaluate').disabled = true;
    status('正在进行真实排版试算与几何安全校验…', 'pending');
    try {
      const res = await fetch('/api/intents/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(snap.intent)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const currentSnap = state.intentSession.snapshot();
      if (!state.inFlightGuard.isValid(token, currentSnap.intent?.operation_id, currentSnap.intent?.delta_mm)) {
        return;
      }
      state.lastEvaluation = data;
      byId('intent-eval-results').hidden = false;
      const statusText = data.status === 'OK' ? '通过' : (data.status === 'TARGET_MISMATCH' ? '位移不匹配' : (data.status === 'IMPACT_MISMATCH' ? '产生非预期碰撞' : data.status));
      const verifyText = data.verification_level === 'RENDER_CHECKED' ? '真实渲染几何检验通过' : data.verification_level;
      byId('eval-state-text').textContent = `状态：${statusText} · 验证：${verifyText}`;
      fields(byId('eval-fields'), [
        ['目标位移', `Δ [${data.target_delta_mm?.join(', ')}] mm`],
        ['实测位移', `Δ [${data.measured_delta_mm?.map(v => Number(v.toFixed(4))).join(', ')}] mm`],
        ['位移误差', data.error_mm != null ? `${Number(data.error_mm.toFixed(4))} mm` : '无'],
        ['质检项', (data.checks || []).map(c => `${c.check}:${c.status === 'OK' ? '合格' : c.status}`).join('， ') || '全部合格']
      ]);
      const acceptable = canAcceptEvaluation(data, currentSnap.intent);
      byId('btn-accept').disabled = !acceptable;
      if (data.frame && isDecisionSuccessful(data)) {
        await loadFrame(data.frame, undefined, false);
      } else {
        if (state.candidateFrame && state.acceptedFrame) {
          await loadFrame(state.acceptedFrame, undefined, false);
        }
        status(acceptable ? '真实渲染几何检验通过 · 预览呈现中 · 尚未接受到会话' : `试算未通过：${data.message || data.status || '位移或质检不符合安全规范'}`, acceptable ? 'ok' : 'error');
      }
    } catch (e) {
      status(`试算请求失败：${e.message}`, 'error');
    } finally {
      updateIntentUI();
    }
  });

  byId('btn-accept').addEventListener('click', async () => {
    if (!state.intentSession || !state.lastEvaluation) return;
    const snap = state.intentSession.snapshot();
    if (!canAcceptEvaluation(state.lastEvaluation, snap.intent)) {
      status('无法接受：未通过几何验证', 'error');
      return;
    }
    const baseline = state.acceptedFrame || state.frame;
    const payload = buildDecisionPayload(baseline, snap.intent.operation_id, 'accept');
    status('正在应用调整并更新会话状态…', 'pending');
    try {
      const res = await fetch('/api/intents/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!isDecisionSuccessful(data)) {
        status(`接受未通过：${data.message || data.status}`, 'error');
        return;
      }
      state.operationStack.push(snap.intent.operation_id);
      const newFrame = data.accepted_frame || data.frame || state.candidateFrame;
      state.acceptedFrame = newFrame;
      state.candidateFrame = null;
      if (newFrame) await loadFrame(newFrame, undefined, true);
      state.intentSession.cancel();
      state.lastEvaluation = null;
      byId('intent-eval-results').hidden = true;
      updateIntentUI();
      highlights();
      status('已应用到当前会话 · 内存调整生效（磁盘源文件未修改）', 'ok');
    } catch (e) {
      status(`接受失败：${e.message}`, 'error');
    }
  });

  byId('btn-undo').addEventListener('click', async () => {
    const current = state.acceptedFrame || state.frame;
    const canRebuild = !!(current?.session && current.session.can_evaluate !== false && current.session.source_revision);
    if (!canRebuild) {
      status('普通图件缺少可信重建支持，无法撤销', 'error');
      return;
    }
    if (!state.operationStack.canUndo()) {
      status('当前没有可撤销的操作', 'pending');
      return;
    }
    const opId = state.operationStack.pop();
    const payload = buildDecisionPayload(current, opId, 'undo');
    status('正在撤销上一步操作…', 'pending');
    try {
      const res = await fetch('/api/intents/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!isDecisionSuccessful(data)) {
        state.operationStack.push(opId);
        status(`撤销操作未通过：${data.message || data.status}`, 'error');
        updateIntentUI();
        return;
      }
      const newFrame = data.accepted_frame || data.frame;
      state.acceptedFrame = newFrame;
      state.candidateFrame = null;
      if (newFrame) await loadFrame(newFrame, undefined, true);
      state.intentSession.cancel();
      state.lastEvaluation = null;
      byId('intent-eval-results').hidden = true;
      updateIntentUI();
      highlights();
      status('已撤销上一步操作；恢复至之前的会话状态', 'ok');
    } catch (e) {
      state.operationStack.push(opId);
      status(`撤销失败：${e.message}`, 'error');
      updateIntentUI();
    }
  });

  async function changeQuality(dpi) {
    const current = state.acceptedFrame || state.frame;
    const canRebuild = !!(current?.session && current.session.can_evaluate !== false && current.session.source_revision);
    if (!canRebuild) {
      status('静态快照或普通图件不支持切换清晰度：缺少可信重建支持', 'error');
      return;
    }
    status(`正在切换至 ${dpi} DPI 并重新生成完整几何与图像…`, 'pending');
    try {
      const res = await fetch('/api/frame/quality', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dpi,
          session_id: current.session.session_id,
          scene_revision: current.frame_revision,
          source_revision: state.scene?.source_revision
        })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!isDecisionSuccessful(data)) {
        status(`清晰度切换未通过：${data.message || data.status}`, 'error');
        return;
      }
      const newFrame = data.frame || data.accepted_frame;
      if (newFrame) {
        state.acceptedFrame = newFrame;
        state.candidateFrame = null;
        await loadFrame(newFrame, undefined, true);
      }
      status(`已加载 ${dpi} DPI 完整同帧几何与图像`, 'ok');
    } catch (e) {
      status(`清晰度切换失败：${e.message}`, 'error');
    }
  }

  byId('btn-dpi-120').addEventListener('click', () => changeQuality(120));
  byId('btn-dpi-240').addEventListener('click', () => changeQuality(240));
  if (byId('btn-dpi-600')) byId('btn-dpi-600').addEventListener('click', () => changeQuality(600));

  root.addEventListener('blur', () => { state.space = false; state.pan = null; viewport.classList.remove('panning'); });
  root.addEventListener('resize', fit);

  async function loadFrame(frame, expectedSourceRevision, isNewAccepted = true) {
    const epoch = ++state.epoch;
    state.ready = false;
    if (isNewAccepted) {
      state.scene = null;
      state.hover = state.selected = null;
      state.nodes.clear();
      state.paths.clear();
      viewport.replaceChildren();
      byId('frame-scope').textContent = byId('frame-revision').textContent = '';
      byId('state-fields').replaceChildren();
      byId('detail-fields').replaceChildren();
      byId('calibration-note').hidden = true;
      container.dataset.hoverId = container.dataset.selectedId = '';
      select(null);
    }
    container.dataset.ready = 'false';
    container.dataset.frameState = 'loading';
    status(isNewAccepted ? '正在校验图形数据与几何摘要…' : '正在校验候选图像与几何…', 'pending');
    try {
      const scene = await verifyFrame(frame, expectedSourceRevision);
      const image = new Image();
      image.src = `data:image/png;base64,${frame.png_base64}`;
      await image.decode();
      requireFact(image.naturalWidth === scene.image.width_px && image.naturalHeight === scene.image.height_px, 'Decoded PNG dimensions mismatch');
      if (epoch !== state.epoch) return;
      state.scene = scene;
      state.nodes = new Map(scene.nodes.map(node => [node.id, node]));
      state.paths.clear();
      if (isNewAccepted) {
        state.acceptedFrame = frame;
        state.candidateFrame = null;
        if (frame?.session?.accepted_operation_ids && Array.isArray(frame.session.accepted_operation_ids)) {
          state.operationStack = createOperationStack(frame.session.accepted_operation_ids);
        }
        state.frame = frame;
        state.intentSession = createIntentSession(frame);
        state.lastEvaluation = null;
        state.pendingOperationId = null;
      } else {
        state.candidateFrame = frame.frame_revision === state.acceptedFrame?.frame_revision ? null : frame;
      }
      const sessionObj = state.acceptedFrame?.session || frame.session;
      const canRebuild = !!(sessionObj && sessionObj.can_evaluate !== false && sessionObj.source_revision);

      const dpiButtons = [
        { btn: byId('btn-dpi-120'), dpi: 120, title: '标准清晰度 (120 DPI)' },
        { btn: byId('btn-dpi-240'), dpi: 240, title: '高清打印清晰度 (240 DPI)' },
        { btn: byId('btn-dpi-600'), dpi: 600, title: '出版清晰度 (600 DPI)' }
      ];
      const currentDpi = scene.measurement?.dpi;
      for (const item of dpiButtons) {
        if (!item.btn) continue;
        item.btn.disabled = !canRebuild;
        if (!canRebuild) {
          item.btn.title = '普通图件或静态快照仅支持查看测量，不支持切换清晰度';
        } else {
          item.btn.title = item.title;
        }
        const isActive = currentDpi === item.dpi;
        item.btn.classList.toggle('active', isActive);
        item.btn.setAttribute('aria-pressed', String(isActive));
      }

      const b = scene.canvas_bounds_mm, ib = scene.image.bounds_mm;
      viewport.setAttribute('viewBox', `${b[0]} 0 ${b[2] - b[0]} ${b[3] - b[1]}`);
      let img = viewport.querySelector('image');
      if (!img) {
        viewport.replaceChildren();
        img = svg('image', { x: ib[0], y: b[3] - ib[3], width: ib[2] - ib[0], height: ib[3] - ib[1], href: image.src, preserveAspectRatio: 'none' });
        viewport.append(img);
        viewport.append(svg('g', { id: 'highlights' }));
      } else {
        img.setAttribute('href', image.src);
        img.setAttribute('x', ib[0]);
        img.setAttribute('y', b[3] - ib[3]);
        img.setAttribute('width', ib[2] - ib[0]);
        img.setAttribute('height', ib[3] - ib[1]);
      }
      state.ready = true;
      container.dataset.ready = 'true';
      container.dataset.frameState = 'verified';
      byId('frame-scope').textContent = scene.scope;

      const badge = byId('badge-readonly');
      if (badge) {
        if (canRebuild) {
          badge.textContent = '会话试算（源文件受保护）';
          badge.className = 'tag mode-session';
        } else {
          badge.textContent = '只读测量';
          badge.className = 'tag mode-static';
        }
      }

      fields(byId('state-fields'), [
        ['渲染器', scene.measurement?.renderer || 'Agg'],
        ['清晰度', `${scene.measurement?.dpi || 120} DPI`],
        ['页面尺寸', `${Number((scene.canvas_bounds_mm[2] - scene.canvas_bounds_mm[0]).toFixed(2))} × ${Number((scene.canvas_bounds_mm[3] - scene.canvas_bounds_mm[1]).toFixed(2))} mm`],
        ['源版本', scene.source_revision ? scene.source_revision.slice(0, 12) : '无配置 / 未提供'],
        ['帧摘要', frame.frame_revision ? frame.frame_revision.slice(0, 12) : '无']
      ]);
      byId('calibration-note').hidden = false;
      byId('calibration-note').textContent = '物理标尺基于图件导出页面尺寸（毫米），非显示屏幕实际物理毫米。折线采用中心线几何模型，文字采用保守外包络。';

      if (isNewAccepted) {
        byId('frame-revision').textContent = frame.frame_revision.slice(0, 12);
        status(canRebuild ? '会话已就绪 · 几何数据与渲染像素完全吻合（源文件受保护）' : '图件校验通过 · 只读快照', 'ok');
        wrap.scrollLeft = wrap.scrollTop = 0;
        fit();
        objectList();
        select(null);
      } else if (state.candidateFrame) {
        byId('frame-revision').textContent = `${state.acceptedFrame?.frame_revision?.slice(0, 12) || ''} (候选: ${frame.frame_revision.slice(0, 8)})`;
        status('真实渲染几何检验通过 · 预览呈现中 · 尚未接受到会话', 'pending');
        select(state.selected);
      } else {
        byId('frame-revision').textContent = frame.frame_revision.slice(0, 12);
        select(state.selected);
      }
      updateIntentUI();
      highlights();
    } catch (error) {
      if (epoch !== state.epoch) return;
      state.ready = false;
      container.dataset.ready = 'false';
      container.dataset.frameState = 'invalid';
      if (isNewAccepted) select(null);
      status(`图件不可使用：${error.message}；请刷新或重新导出。`, 'error');
    }
  }
  api.loadFrame = loadFrame;
  if (root.FIGPACT_INSPECTOR_FRAME) {
    loadFrame(root.FIGPACT_INSPECTOR_FRAME, root.FIGPACT_INSPECTOR_EXPECTED_SOURCE_REVISION);
  } else if (typeof fetch === 'function') {
    fetch('/api/frame')
      .then(res => res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)))
      .then(frame => {
        if (frame && frame.schema === 'figpact.inspector/1') loadFrame(frame);
        else loadFrame(undefined);
      })
      .catch(() => {
        loadFrame(undefined);
      });
  } else {
    loadFrame(undefined);
  }
  globalScope.FigpactInspector = api;
})(globalThis);
