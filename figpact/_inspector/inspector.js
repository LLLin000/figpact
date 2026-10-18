'use strict';

(function (root) {
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const point = (p) => Array.isArray(p) && p.length === 2 && p.every(finite);
  const box = (b) => Array.isArray(b) && b.length === 4 && b.every(finite) && b[2] >= b[0] && b[3] >= b[1];
  const hex = (v) => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  const round4 = (v) => Math.round(v * 10000) / 10000;
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
  // 拖动的像素位移 → 毫米位移。右 / 上为正：screenToMm 的 y 轴朝上，差值天然就是这个符号。
  function dragDeltaMm(rect, bounds, from, to) {
    const a = screenToMm(rect, bounds, from.x, from.y);
    const b = screenToMm(rect, bounds, to.x, to.y);
    return { dx: round4(b.x - a.x), dy: round4(b.y - a.y) };
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

  // ---------- P1：图上直接拖动（预览留在本地，验证仍归引擎）----------
  //: 按下后超过这个像素位移才算拖动；否则仍旧按"单击选中"处理（与空格平移同一阈值）。
  const DRAG_THRESHOLD_PX = 3;

  // 能被当作刚体示范位置的对象：曲线与引线受保护、未测量或被裁掉的对象没有可比对的轮廓。
  // 只做平移：缩放/改尺寸需要引擎侧新的 operation kind，不在本切片。
  function canGhostNode(node) {
    if (!node) return false;
    return !(node.type === 'guide' || node.type === 'curve' || node.type === 'panel' || node.annotation
      || node.gid?.includes('guide') || !node.measured || node.fully_clipped);
  }

  // 预览 ≠ 验证：只有引擎回执（状态 OK 且逐项检查 PASS）才能说"检查通过"。
  // 拖动期间、写盘、以及任何本地 overlay 都不得借用"已验证 / 已保存"这类文案。
  function previewStatusText(input) {
    const { dragging = false, evaluating = false, hasDelta = false, outOfRange = false,
            evaluation = null, acceptable = false } = input || {};
    if (dragging) return { text: '拖动预览，尚未验证', className: 'tag' };
    if (evaluating) return { text: '验证中…', className: 'tag' };
    if (outOfRange) return { text: '超出允许范围 (±10 mm)', className: 'tag tag-warning' };
    if (evaluation) {
      return acceptable
        ? { text: '已重新绘图，位置检查通过', className: 'tag tag-success' }
        : { text: `检查未通过 (${evaluation.status || '未通过'})`, className: 'tag tag-warning' };
    }
    return hasDelta ? { text: '位置示范，尚未验证', className: 'tag' } : { text: '未调整', className: 'tag' };
  }

  // 拖动期间的状态机：pointermove 只能走到预览，**任何**鼠标移动都不许发出后端请求；
  // 只有"松手 + 位移非零 + 这个对象可重新绘图验证"才允许走一次真实 evaluate。
  function dragPointerAction(event, input) {
    const { dragging = false, hasDelta = false, canEvaluate = false } = input || {};
    if (!dragging) return 'ignore';
    if (event === 'pointermove') return 'preview';
    if (event === 'pointerup') return hasDelta && canEvaluate ? 'evaluate' : 'end';
    return 'end';
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

  function readPanelMode(search) {
    return new URLSearchParams(search || '').get('panel') === 'min' ? 'min' : 'full';
  }
  const signedMm = v => `${v >= 0 ? '+' : '-'}${Math.abs(v).toFixed(3)}`;
  function minimalStatusText(input) {
    const { node = null, snapshot = null, evaluation = null, dragging = false } = input || {};
    if (!node) return '未选择对象';
    if (dragging) {
      const preview = snapshot?.intent?.delta_mm || [0, 0];
      return `预览 ${signedMm(preview[0])} · ${signedMm(preview[1])} mm（未验证）`;
    }
    if (evaluation) {
      if (canAcceptEvaluation(evaluation, snapshot?.intent)) {
        const measured = Array.isArray(evaluation.measured_delta_mm) ? (evaluation.measured_delta_mm[0] || evaluation.measured_delta_mm[1]) : null;
        return measured == null ? '试算通过' : `试算通过 · 实测 ${signedMm(measured)} mm`;
      }
      return `试算未通过 · ${evaluation.status || '未通过'}`;
    }
    const delta = snapshot?.intent?.delta_mm || [0, 0];
    const parts = [];
    if (delta[1]) parts.push(`已${delta[1] > 0 ? '上' : '下'}移 ${Math.abs(delta[1])} mm`);
    if (delta[0]) parts.push(`已${delta[0] > 0 ? '右' : '左'}移 ${Math.abs(delta[0])} mm`);
    if (parts.length) return snapshot?.status === 'OUT_OF_RANGE' ? `${parts.join(' · ')} · 超出允许范围` : parts.join(' · ');
    return snapshot?.selectionBlocked ? '请先保留或取消当前调整' : '方向键微调位置';
  }
  function buildAgentDetail(input) {
    const { node = null, title = null, type = null, snapshot = null, frame = null, scene = null, evaluation = null, acceptedOperationIds = [] } = input || {};
    const delta = snapshot?.intent?.delta_mm || [0, 0];
    return {
      schema: 'figpact.inspector.agent_detail/1',
      selected: node ? (node.gid || node.id || null) : null,
      id: node ? node.id : null,
      title: node ? (title ?? null) : null,
      type: node ? (type ?? null) : null,
      bounds_mm: node?.bounds_mm ?? null,
      delta_mm: [delta[0], delta[1]],
      status: node ? (snapshot?.status || 'DESIRED_ONLY') : 'NO_SELECTION',
      selection_blocked: !!snapshot?.selectionBlocked,
      can_evaluate: !!snapshot?.canEvaluate,
      frame_revision: frame?.frame_revision ?? null,
      source_revision: scene?.source_revision ?? null,
      session_id: frame?.session?.session_id ?? null,
      accepted_operation_ids: Array.isArray(acceptedOperationIds) ? [...acceptedOperationIds] : [],
      evaluation: evaluation ? {
        status: evaluation.status ?? null,
        verification_level: evaluation.verification_level ?? null,
        target_delta_mm: evaluation.target_delta_mm ?? null,
        measured_delta_mm: evaluation.measured_delta_mm ?? null,
        error_mm: evaluation.error_mm ?? null,
        checks: evaluation.checks ?? null
      } : null
    };
  }

  function stageSizeChanged(previous, width, height) {
    return !previous || previous.width !== width || previous.height !== height;
  }

  // 方向键是否可用：完整模式仍要求画布聚焦；极简模式额外接受“宿主给了焦点且没有输入框聚焦”
  function acceptsArrowKeys(input) {
    const { minimal = false, activeElementIsViewport = false, hasDocumentFocus = false, inputActive = false } = input || {};
    if (inputActive) return false;
    if (activeElementIsViewport) return true;
    return !!minimal && !!hasDocumentFocus;
  }

  // ---------- G5b 计划（同意 / 取消）----------
  // 页面只是「同意」的通道：它回传的是服务端铸造的 plan_id + 服务端注入页面的会话令牌。
  // 页面侧的动作只有 authorize / cancel：apply（写盘）由申请该计划的客户端做，这里没有这条路。
  const PLAN_ACTIONS = ['authorize', 'cancel'];

  function planRequest(planId, action, token) {
    requireFact(typeof planId === 'string' && planId, 'Invalid plan id');
    requireFact(PLAN_ACTIONS.includes(action), `Plan action ${action} is not available to the Inspector page`);
    // 不带 body：授权不是请求体里的布尔字段，而是 header 里的页面会话令牌。
    return { url: `/api/plans/${encodeURIComponent(planId)}/${action}`,
             init: { method: 'POST', headers: { 'X-Figpact-Ui': typeof token === 'string' ? token : '' } } };
  }
  function plansFromPayload(payload) {
    const list = Array.isArray(payload) ? payload : (payload && Array.isArray(payload.plans) ? payload.plans : null);
    return list ? list.filter(plan => plan && typeof plan.plan_id === 'string' && plan.plan_id) : [];
  }
  function pendingPlans(payload) {
    return plansFromPayload(payload).filter(plan => plan.state === 'PENDING');
  }
  function planValueText(value) {
    return Array.isArray(value) && value.length && value.every(finite)
      ? `[${value.map(v => Number(v.toFixed(4))).join(', ')}]`
      : '（无值）';
  }
  function planFilesText(plan) {
    const paths = (Array.isArray(plan?.files) ? plan.files : []).map(file => file?.path).filter(Boolean);
    return paths.length ? paths.join(', ') : '（无文件）';
  }
  function planSummaryText(plan) {
    if (!plan) return '';
    const count = Array.isArray(plan.files) ? plan.files.length : 0;
    return `${plan.gid ?? '?'} ← ${planValueText(plan.value)} · ${count} 个文件：${planFilesText(plan)}`;
  }
  function planDiffText(plan) {
    const files = Array.isArray(plan?.files) ? plan.files : [];
    if (!files.length) return '（没有可显示的改动）';
    return files.map(file => {
      const diff = typeof file?.diff === 'string' && file.diff.trim() ? file.diff.replace(/\s+$/, '') : '（无 unified diff）';
      return `--- ${file?.path ?? '?'}\n${diff}`;
    }).join('\n');
  }
  // 失败必须可读：HTTP 状态 + 服务端信封文案，一个都不许吞。
  function planFailureText(status, payload) {
    const code = payload && typeof payload.status === 'string' ? payload.status : `HTTP ${status}`;
    const message = payload && typeof payload.message === 'string' && payload.message ? `：${payload.message}` : '';
    return `${status} ${code}${message}`;
  }

  // P0a：**两个独立状态**——源码提交（写盘与否）与图形验证（独立重建与否），谁也推不出谁。
  const SOURCE_COMMIT_TEXT = {
    COMMITTED: '源码已提交',
    NOT_WRITTEN: '源码未写入',
    RECOVERY_REQUIRED: '源码写入状态不可判定（需人工恢复）',
  };
  const FIGURE_VERIFICATION_TEXT = {
    PASS: '独立重建验证通过',
    FAIL: '独立重建验证失败',
    ERROR: '独立重建验证未完成',
    NOT_RUN: '尚未独立重建验证',
  };
  // 只有 COMMITTED + PASS 才允许说这句话；写盘已成事实而验证没过/没跑完时必须照实说。
  function planCommitText(plan) {
    const source = plan && plan.source_commit_state;
    const verify = plan && plan.figure_verification_state;
    if (source === 'COMMITTED' && verify === 'PASS') return '修改已保存并通过验证';
    if (source === 'COMMITTED') return '源码已提交，图形验证失败/未完成';
    if (source === 'RECOVERY_REQUIRED') return SOURCE_COMMIT_TEXT.RECOVERY_REQUIRED;
    return '源码未写入，图形未验证';
  }
  function commitDetailText(plan) {
    const source = plan && plan.source_commit_state;
    const verify = plan && plan.figure_verification_state;
    const parts = [
      `写入：${SOURCE_COMMIT_TEXT[source] || source || '（未知）'}`,
      `验证：${FIGURE_VERIFICATION_TEXT[verify] || verify || '（未知）'}`,
    ];
    const measured = plan && plan.figure_verification && plan.figure_verification.measured_mm;
    if (Array.isArray(measured) && measured.length === 2 && measured.every(finite)) {
      parts.push(`实测位移 [${measured.map(v => Number(v.toFixed(4))).join(', ')}] mm`);
    }
    if (plan && plan.figure_verification_stale) {
      parts.push('源码在验证之后又被改动，旧结论已失效');
    }
    return parts.join(' · ');
  }
  // 已经碰过磁盘的计划（写盘是事实 / 状态不可判定）才进"事后状态"区；待授权的仍走计划条。
  function committedPlans(payload) {
    return plansFromPayload(payload).filter(plan => plan.source_commit_state === 'COMMITTED'
      || plan.source_commit_state === 'RECOVERY_REQUIRED');
  }

  // G7b 保存闭环的纯函数：待保存集合、双状态→文案、拒绝文案。
  function saveResultText(resp) {
    const source = resp && resp.source_commit_state;
    const verify = resp && resp.figure_verification_state;
    if (resp && resp.status === 'REFUSED') return '原文件未修改';
    if (resp && resp.status === 'STALE_SOURCE') return `拒绝：${resp.message || ''}`.trim();
    if (source === 'COMMITTED' && verify === 'PASS') return '修改已保存并通过验证';
    if (source === 'COMMITTED') return '源码已写入，但图形验证失败';
    if (source === 'NOT_WRITTEN') return '有待保存修改';
    return planCommitText(resp);
  }
  function pendingSaveEntry(input) {
    const it = input || {};
    return {
      id: it.id || it.operation_id || `save-${Date.now()}`,
      target: it.target || it.path || it.file || '目标文件',
      params: Array.isArray(it.params) ? it.params : (it.params ? [it.params] : []),
      diff: typeof it.diff === 'string' ? it.diff : (typeof it.sourceDiff === 'string' ? it.sourceDiff : ''),
    };
  }
  function addPendingSave(list, entry) {
    const next = Array.isArray(list) ? [...list] : [];
    next.push(pendingSaveEntry(entry));
    return next;
  }
  function removePendingSave(list, id) {
    return (Array.isArray(list) ? list : []).filter(item => item && item.id !== id);
  }
  function pendingSaveCount(list) { return Array.isArray(list) ? list.length : 0; }

  // G5b：选区序号。Hub 要求 selection_seq 跨页面会话严格递增，而模块级计数器每次刷新都
  // 从 0 重来——所以发布前先按 GET /api/selection 的 hub_revision / selection_seq 播种；
  // 被 400 INVALID_SELECTION 拒掉时按最新值再播种一次并重播。
  // 返回本地计数器应当采用的下一序号：严格大于 Hub 已知值与本地现值。
  function seedSelectionSeq(payload, current) {
    const local = typeof current === 'number' && Number.isFinite(current) && current >= 0
      ? Math.floor(current)
      : 0;
    const known = [payload && payload.hub_revision, payload && payload.selection && payload.selection.selection_seq]
      .filter(value => typeof value === 'number' && Number.isFinite(value) && value >= 0)
      .map(value => Math.floor(value));
    return Math.max(local, ...known) + 1;
  }

  // 只有服务端明确说"序号非法"才值得重播；其它拒绝（415 不是 JSON、409 STALE_SELECTION…）重播也是白搭。
  function shouldReseed(status, payload) {
    const code = payload && typeof payload.status === 'string' ? payload.status : '';
    if (code !== 'INVALID_SELECTION') return false;
    const http = Number(status);
    return Number.isFinite(http) ? http >= 400 && http < 500 : true;
  }

  const api = { validateFrame, verifyFrame, screenToMm, dragDeltaMm, canGhostNode, previewStatusText, dragPointerAction, hitCandidates, cycleSelection, niceTickStep, fitViewport, zoomViewport, createIntentSession, canAcceptEvaluation, buildDecisionPayload, createOperationStack, isDecisionSuccessful, createInFlightGuard, readPanelMode, buildAgentDetail, minimalStatusText, stageSizeChanged, acceptsArrowKeys, planRequest, plansFromPayload, pendingPlans, planSummaryText, planDiffText, planFailureText, planCommitText, commitDetailText, committedPlans, seedSelectionSeq, shouldReseed, saveResultText, pendingSaveEntry, addPendingSave, removePendingSave, pendingSaveCount };
  const globalScope = typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : root);
  globalScope.FigpactInspector = api;
  root.FigpactInspector = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  const byId = id => document.getElementById(id);
  const container = byId('inspector-root'), viewport = byId('viewport'), wrap = byId('viewport-wrap');
  if (!container || !viewport || !wrap) return;
  const minimal = readPanelMode(location.search) === 'min';
  if (minimal) {
    container.dataset.panel = 'min';
    const statusLine = byId('min-status');
    if (statusLine) statusLine.hidden = false;
  }
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
    drag: null,
    evaluating: false,
    intentSession: null,
    lastEvaluation: null,
    operationStack: createOperationStack(),
    inFlightGuard: createInFlightGuard(),
    pendingOperationId: null,
    styleSelected: null,
    stylePending: null,
    styleBusy: false,
    styleTargets: [],
    styleOverlaySha: null,
    styleClientMs: null,
    styleServerMs: null,
    plansError: '',
    planNotice: '',
    planErrors: new Map(),
    selectionError: ''
  };
  const svg = (tag, attrs = {}) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  };

  function formatScientificText(raw) {
    if (typeof raw !== 'string') return '';
    const sub = '₀₁₂₃₄₅₆₇₈₉₊₋', sup = '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻';
    // Only format supported numeric math spans; keep identifiers, case and literal $ intact.
    return raw.replace(/\$([_^])(?:\{([0-9+-]+)\}|([0-9+-]))\$/g,
      (_, op, group, single) => [...(group || single)]
        .map(c => (op === '_' ? sub : sup)['0123456789+-'.indexOf(c)]).join(''));
  }

  function displayTitle(node) {
    if (!node) return '未命名对象';
    if (node.text) {
      const clean = formatScientificText(node.text);
      if (node.annotation && node.annotation.declared_exact_ppm) {
        return `${clean} (${Number(node.annotation.declared_exact_ppm.toFixed(2))} ppm)`;
      }
      return clean;
    }
    if (node.type === 'guide' || node.annotation || node.gid?.includes('guide')) {
      if (node.annotation && node.annotation.declared_exact_ppm) {
        return `峰位引线 (${Number(node.annotation.declared_exact_ppm.toFixed(2))} ppm)`;
      }
      return '峰位引线';
    }
    const ordinal = (state.scene?.nodes.findIndex(n => n.id === node.id) ?? -1) + 1;
    return `${displayType(node)} ${ordinal || ''}`.trim();
  }

  function displayType(node) {
    if (!node) return '对象';
    if (node.type === 'guide' || node.annotation || node.gid?.includes('guide')) return '引线';
    if (node.type === 'text') return '文本';
    if (node.type === 'curve') return '曲线';
    if (node.type === 'image') return '图像';
    if (node.type === 'panel') return '子图';
    if (node.type === 'group') return '对象组';
    if (node.type === 'legend') return '图例';
    if (node.type === 'figure') return '整张图';
    return '对象';
  }

  function formatBounds(b) {
    if (!Array.isArray(b) || b.length !== 4) return '无位置信息';
    const x = Number(b[0].toFixed(3));
    const y = Number(b[1].toFixed(3));
    const w = Number((b[2] - b[0]).toFixed(3));
    const h = Number((b[3] - b[1]).toFixed(3));
    return `水平 x: ${x} mm, 垂直 y: ${y} mm · 宽 ${w} mm × 高 ${h} mm`;
  }

  const title = node => displayTitle(node);

  function status(message, kind) {
    const el = byId('integrity-status');
    if (el) {
      el.textContent = message;
      el.className = `status status-${kind}`;
    }
    // 极简模式隐藏了顶栏，加载失败必须落在唯一的动作行上，否则页面看起来是空的
    if (minimal && kind === 'error') {
      const line = byId('min-status');
      if (line) line.textContent = message;
    }
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

  // ---------- G5b 待授权计划：极简一条 + 授权 / 取消 ----------
  // 这一块只读 /api/plans、只发 authorize / cancel；写盘（apply）永远由申请计划的客户端做。
  function uiToken() {
    return typeof root.FIGPACT_UI_TOKEN === 'string' ? root.FIGPACT_UI_TOKEN : '';
  }

  function planStrip(plan) {
    const strip = document.createElement('article');
    strip.className = 'plan-strip';
    strip.setAttribute('data-plan-id', plan.plan_id);

    const head = document.createElement('div');
    head.className = 'plan-head';
    const title = document.createElement('span');
    title.className = 'plan-title';
    title.textContent = planSummaryText(plan);
    head.append(title);

    const actions = document.createElement('span');
    actions.className = 'plan-actions';
    for (const [action, label] of [['authorize', '授权'], ['cancel', '取消']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('data-plan-action', action);
      button.textContent = label;
      button.addEventListener('click', () => planAction(plan.plan_id, action));
      actions.append(button);
    }
    head.append(actions);

    const line = document.createElement('span');
    line.className = 'plan-status';
    line.setAttribute('data-plan-status', '');
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    line.textContent = state.planErrors.get(plan.plan_id) || '';
    head.append(line);

    // diff 摘要可折叠：默认展开（节点始终有内容），极简模式靠 CSS 压成细条，点 summary 收起
    const details = document.createElement('details');
    details.className = 'plan-diff-wrap';
    details.open = true;
    const summary = document.createElement('summary');
    summary.textContent = 'unified diff';
    const diff = document.createElement('pre');
    diff.className = 'plan-diff';
    diff.setAttribute('data-plan-diff', '');
    diff.textContent = planDiffText(plan);
    details.append(summary, diff);

    strip.append(head, details);
    return strip;
  }

  // 已写盘计划的事后状态：写入与验证分别说，**只有 COMMITTED+PASS** 才出现"已保存并通过验证"。
  function commitStrip(plan) {
    const strip = document.createElement('article');
    strip.className = 'plan-strip commit-strip';
    strip.setAttribute('data-commit-id', plan.plan_id);
    strip.setAttribute('data-source-commit-state', String(plan.source_commit_state || ''));
    strip.setAttribute('data-figure-verification-state', String(plan.figure_verification_state || ''));
    if (plan.figure_verification_stale) strip.setAttribute('data-figure-verification-stale', 'true');

    const head = document.createElement('div');
    head.className = 'plan-head';
    const title = document.createElement('span');
    title.className = 'plan-title';
    title.setAttribute('data-commit-status', '');
    title.textContent = planCommitText(plan);
    const detail = document.createElement('span');
    detail.className = 'plan-status';
    detail.setAttribute('data-commit-detail', '');
    detail.textContent = commitDetailText(plan);
    head.append(title, detail);
    strip.append(head);
    return strip;
  }

  function renderCommits() {
    const holder = byId('agent-commits');
    if (!holder) return;
    holder.replaceChildren();
    for (const plan of committedPlans(state.plans)) holder.append(commitStrip(plan));
  }

  function renderPlans() {
    const holder = byId('agent-plans');
    if (!holder) return;
    holder.replaceChildren();
    const notice = state.plansError || state.planNotice;
    if (notice) {
      const line = document.createElement('p');
      line.className = 'plan-notice';
      line.setAttribute('data-plans-notice', '');
      line.setAttribute('role', 'status');
      line.setAttribute('aria-live', 'polite');
      line.textContent = notice;
      holder.append(line);
    }
    // 选区通道失败和计划失败共用这条可见通道，但各有自己的标记属性
    if (state.selectionError) {
      const line = document.createElement('p');
      line.className = 'plan-notice';
      line.setAttribute('data-selection-error', '');
      line.setAttribute('role', 'status');
      line.setAttribute('aria-live', 'polite');
      line.textContent = state.selectionError;
      holder.append(line);
    }
    for (const plan of pendingPlans(state.plans)) holder.append(planStrip(plan));
    renderCommits();
  }

  function setSelectionError(text) {
    if (text === state.selectionError) return;
    state.selectionError = text;
    renderPlans();
  }

  async function refreshPlans() {
    if (typeof fetch !== 'function') return;
    try {
      const response = await fetch('/api/plans', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const plans = plansFromPayload(await response.json());
      const wasError = !!state.plansError;
      state.plansError = '';
      // 内容没变就不重画：轮询不能把用户展开的 diff 收回去，也不能打断点击。
      // 两个状态字段也算内容：写盘/验证结果变了就必须重画。
      const signature = plans.map(plan => [plan.plan_id, plan.state, plan.source_commit_state,
        plan.figure_verification_state, plan.figure_verification_stale].join(':')).join('|');
      if (signature === state.plansSignature && !wasError) return;
      state.plansSignature = signature;
      state.plans = plans;
    } catch (error) {
      const text = `无法获取待授权计划：${error.message}`;
      if (text === state.plansError) return;
      state.plansError = text;
    }
    renderPlans();
  }

  function renderPendingSaves() {
    const holder = byId('pending-saves');
    if (!holder) return;
    holder.replaceChildren();
    for (const item of state.pendingSaves) {
      const el = document.createElement('article');
      el.className = 'pending-save';
      el.setAttribute('data-pending-save', item.id);
      const path = document.createElement('div');
      path.className = 'pending-save-target';
      path.textContent = item.target;
      const params = document.createElement('div');
      params.className = 'pending-save-params';
      params.textContent = (Array.isArray(item.params) ? item.params : []).join(' → ') || '（无参数变更）';
      const diff = document.createElement('pre');
      diff.className = 'pending-save-diff';
      diff.textContent = item.diff || '（无 unified diff）';
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.textContent = '移除';
      rm.addEventListener('click', () => { state.pendingSaves = removePendingSave(state.pendingSaves, item.id); renderPendingSaves(); });
      el.append(path, params, diff, rm);
      holder.append(el);
    }
    const btn = byId('save-changes');
    if (btn) btn.hidden = state.pendingSaves.length === 0;
  }

  async function planAction(planId, action) {
    const label = action === 'authorize' ? '授权' : '取消';
    const strip = byId('agent-plans')?.querySelector(`[data-plan-id="${planId}"]`);
    let request;
    try {
      request = planRequest(planId, action, uiToken());
    } catch (error) {
      state.planErrors.set(planId, `${label}失败 · ${error.message}`);
      renderPlans();
      return;
    }
    // 本条先锁住，避免同一条细条被连点两次
    if (strip) {
      for (const button of strip.querySelectorAll('button')) button.disabled = true;
      strip.querySelector('[data-plan-status]').textContent = '请求中…';
    }
    try {
      const response = await fetch(request.url, request.init);
      let payload = null;
      try { payload = await response.json(); } catch (error) { payload = null; }
      if (!response.ok || !payload || payload.status !== 'OK') {
        const failure = new Error(planFailureText(response.status, payload));
        failure.http = true;
        throw failure;
      }
      state.planErrors.delete(planId);
      state.planNotice = action === 'authorize'
        ? `已授权 · 计划 ${planId.slice(0, 8)}（等待申请它的客户端应用，本页不写盘）`
        : `已取消 · 计划 ${planId.slice(0, 8)}`;
      await refreshPlans();
    } catch (error) {
      const text = `${label}失败 · ${error.http ? error.message : `网络异常：${error.message}`}`;
      state.planErrors.set(planId, text);
      await refreshPlans();
      // 计划已经不再是 PENDING（细条会消失）时，失败只能落在容器这一行，不许静默
      if (!pendingPlans(state.plans).some(plan => plan.plan_id === planId)) state.planNotice = text;
      renderPlans();
    }
  }

  // 机器可读快照：极简模式看不到的细节都写进这个不可见元素，供 agent 读取（完整模式同样写入）
  function publishAgentDetail() {
    const node = state.nodes.get(state.selected) || null;
    const snapshot = state.intentSession ? state.intentSession.snapshot() : null;
    const holder = byId('agent-detail');
    if (holder) {
      holder.textContent = JSON.stringify(buildAgentDetail({
        node,
        title: node ? displayTitle(node) : null,
        type: node ? displayType(node) : null,
        snapshot,
        frame: state.acceptedFrame || state.frame,
        scene: state.scene,
        evaluation: state.lastEvaluation,
        acceptedOperationIds: state.operationStack.all()
      }));
    }
    const line = byId('min-status');
    if (line) line.textContent = minimalStatusText({ node, snapshot, evaluation: state.lastEvaluation });
    publishSelection();
  }

  // G5a：把当前选区上下文发布给 Hub（只读取选区；不授予源码写入或发布权限）。
  // 只在选区/微调/试算/决定/加载时随 publishAgentDetail 发出，hover 不发布。
  // G5b：刷新后计数器从 0 重来会被 Hub 按"严格递增"拒掉，所以先播种；失败不静默。
  const selectionRandomBase = 1 + Math.floor(Math.random() * 1e9); // 读不到 Hub 时才用的较大随机起点
  let selectionSeq = 0; // 下一个要用的序号：先播种，再发布
  let selectionSeeded = null;
  let selectionChain = Promise.resolve(); // 串行发送：并发 POST 乱序到达会被 Hub 拒掉

  async function fetchSelectionSnapshot() {
    if (typeof fetch !== 'function') return null;
    try {
      const response = await fetch('/api/selection', { headers: { Accept: 'application/json' } });
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      return null; // 取不到 Hub 就退化成随机起点，发布照样递增
    }
  }

  function ensureSelectionSeeded() {
    if (!selectionSeeded) {
      selectionSeeded = fetchSelectionSnapshot().then(payload => {
        // 读到 Hub 就按它的 hub_revision / 上次 seq 播种（空 Hub 就是 1）；读不到才退化成随机起点
        selectionSeq = Math.max(selectionSeq, payload ? seedSelectionSeq(payload, 0) : selectionRandomBase);
        return payload;
      });
    }
    return selectionSeeded;
  }

  // 每次发送时重建 body：排队中的发布永远带最新选区，不重放旧状态。
  function selectionBody(seq) {
    const node = state.nodes.get(state.selected) || null;
    const snapshot = state.intentSession ? state.intentSession.snapshot() : null;
    const frame = state.acceptedFrame || state.frame;
    const delta = snapshot?.intent?.delta_mm || [0, 0];
    const guideNode = node?.linked_guide_gid
      ? (state.scene?.nodes || []).find(n => n.gid === node.linked_guide_gid || n.id === node.linked_guide_gid)
      : null;
    return {
      selection_seq: seq,
      session_id: frame?.session?.session_id ?? null,
      scene_revision: frame?.frame_revision ?? null,
      source_revision: state.scene?.source_revision ?? null,
      scope: state.scene?.scope ?? null,
      mode: 'canvas',
      selected: node ? {
        gid: node.gid || node.id,
        title: displayTitle(node),
        type: displayType(node),
        bounds_mm: node.bounds_mm ?? null,
        linked_guide_gid: node.linked_guide_gid ?? null,
        registered: !!node.registered,
        identity_stability: node.identity_stability ?? null,
        can_evaluate: !!snapshot?.canEvaluate
      } : null,
      delta_mm: [delta[0], delta[1]],
      status: node ? (snapshot?.status || 'DESIRED_ONLY') : 'NO_SELECTION',
      related: guideNode ? [{ gid: guideNode.gid || guideNode.id, relation: 'guide', bounds_mm: guideNode.bounds_mm ?? null }] : [],
      constraints: ['preserve_science']
    };
  }

  async function postSelection(seq) {
    const response = await fetch('/api/selection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(selectionBody(seq))
    });
    let payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    return { ok: response.ok, status: response.status, payload };
  }

  async function publishSelectionOnce() {
    await ensureSelectionSeeded();
    let result = await postSelection(selectionSeq++);
    if (!result.ok && shouldReseed(result.status, result.payload)) {
      // 序号非法：按 Hub 现值重新播种，重播一次
      selectionSeq = seedSelectionSeq(await fetchSelectionSnapshot(), selectionSeq);
      result = await postSelection(selectionSeq++);
    }
    setSelectionError(result.ok ? '' : `选区发布失败 · ${planFailureText(result.status, result.payload)}`);
  }

  function publishSelection() {
    selectionChain = selectionChain
      .then(publishSelectionOnce)
      .catch(error => setSelectionError(`选区发布失败 · 网络异常：${error.message}`));
  }

  function updateIntentUI() {
    publishAgentDetail();
    const section = byId('intent-section');
    if (!section) return;
    const node = state.nodes.get(state.selected);
    try { if (typeof isStyleOnly === 'function' && isStyleOnly()) { section.hidden = true; return; } } catch (e) {}
    if (!state.intentSession) {
      section.hidden = !minimal;
      return;
    }
    const canUndo = state.operationStack.canUndo();
    section.hidden = minimal ? false : (!node && !canUndo && !state.pendingOperationId);
    byId('intent-notice').hidden = true;

    if (!node) {
      byId('intent-status-badge').textContent = canUndo ? '可撤销上一步' : '未选中对象';
      byId('intent-status-badge').className = 'tag';
      byId('intent-displacement').textContent = '本次调整：未选中对象';
      byId('intent-dx').value = 0;
      byId('intent-dx').disabled = true;
      byId('intent-dy').value = 0;
      byId('intent-dy').disabled = true;
      byId('btn-apply-delta').disabled = true;
      byId('btn-evaluate').disabled = true;
      byId('btn-evaluate').title = '请先选中可微调的对象';
      byId('btn-accept').disabled = true;
      byId('btn-accept').title = '需先检查排版并通过验证';
      byId('btn-cancel-intent').disabled = true;
      byId('btn-undo').disabled = !canUndo;
      byId('btn-undo').title = canUndo ? `可撤销上一步调整 (${state.operationStack.peek()})` : '当前没有可撤销的调整';
      return;
    }

    const canGhost = canGhostNode(node);
    byId('intent-dx').disabled = !canGhost;
    byId('intent-dy').disabled = !canGhost;
    byId('btn-apply-delta').disabled = !canGhost;
    const snap = state.intentSession.snapshot();
    const delta = snap.intent ? snap.intent.delta_mm : [0, 0];
    const hasDelta = delta[0] !== 0 || delta[1] !== 0;
    let plainStatus = '未调整';
    let statusClass = 'tag';

    if (!canGhost) {
      if (node.type === 'guide' || node.annotation || node.gid?.includes('guide')) {
        plainStatus = '引线不支持独立微调';
        byId('btn-apply-delta').title = '移动标签时引线会自动调整，这里不能单独移动引线';
      } else if (node.type === 'curve') {
        plainStatus = '科学曲线不可编辑';
        byId('btn-apply-delta').title = '科学曲线受保护，不可移动';
      } else {
        plainStatus = '对象不支持位置调整';
        byId('btn-apply-delta').title = '该对象不支持位置调整';
      }
    } else {
      ({ text: plainStatus, className: statusClass } = previewStatusText({
        dragging: !!state.drag,
        evaluating: state.evaluating,
        hasDelta,
        outOfRange: snap.status === 'OUT_OF_RANGE',
        evaluation: state.lastEvaluation,
        acceptable: !!(state.lastEvaluation && canAcceptEvaluation(state.lastEvaluation, snap.intent))
      }));
    }
    byId('intent-status-badge').textContent = plainStatus;
    byId('intent-status-badge').className = statusClass;

    byId('intent-displacement').textContent = `本次调整：ΔX ${delta[0]} mm, ΔY ${delta[1]} mm`;
    byId('intent-dx').value = delta[0];
    byId('intent-dy').value = delta[1];
    const canEval = state.ready && snap.canEvaluate && canGhost;
    byId('btn-evaluate').disabled = !canEval || state.evaluating || (delta[0] === 0 && delta[1] === 0);
    byId('btn-accept').disabled = !state.ready || !(state.lastEvaluation && canAcceptEvaluation(state.lastEvaluation, snap.intent));
    const hasCancelable = (delta[0] !== 0 || delta[1] !== 0) || !!state.pendingOperationId || !!state.lastEvaluation || !!state.candidateFrame;
    byId('btn-cancel-intent').disabled = !hasCancelable;

    if (!canGhost) {
      byId('btn-evaluate').title = '该对象不支持位置微调';
      byId('btn-accept').title = '该对象不支持位置微调';
    } else if (!snap.canEvaluate) {
      byId('btn-evaluate').title = '这个对象可以示范位置，但无法重新绘图验证';
      byId('btn-accept').title = '这张图只能查看和示范，不能保留修改';
    } else {
      byId('btn-evaluate').title = '按这个位置重新绘图，并检查实际位移和安全限制';
      byId('btn-accept').title = '保留这次调整（只保留在当前服务中，未保存到文件）';
    }
    byId('btn-undo').disabled = !canUndo;
    byId('btn-undo').title = canUndo ? `可撤销上一步调整 (${state.operationStack.peek()})` : '当前没有可撤销的调整';
  }

  function select(id) {
    if (!state.ready) return;
    if (state.pendingOperationId && id !== state.selected) {
      status('当前有未完成的位置微调；请先保留或取消，再选择其他对象', 'pending');
      return;
    }
    if (state.intentSession) {
      const allowed = state.intentSession.select(id);
      if (!allowed) {
        const snap = state.intentSession.snapshot();
        byId('intent-notice').hidden = false;
        byId('intent-notice').textContent = `当前对象存在未处理的示范偏移（ΔX ${snap.intent?.delta_mm[0]} mm, ΔY ${snap.intent?.delta_mm[1]} mm）。请先保留或取消本次调整，再选择其他对象。`;
        return;
      }
    }
    state.selected = state.nodes.has(id) ? id : null;
    container.dataset.selectedId = state.selected || '';
    const node = state.nodes.get(state.selected);
    byId('detail-empty').hidden = !!node;
    byId('detail-fields').hidden = !node;
    if (byId('detail-tech-wrap')) byId('detail-tech-wrap').hidden = !node;
    for (const nid of ['detail-ephemeral', 'detail-readonly', 'detail-annotation']) byId(nid).hidden = true;
    if (node) {
      const sessionObj = state.acceptedFrame?.session || state.frame?.session;
      const canRebuild = !!(sessionObj && sessionObj.can_evaluate !== false && sessionObj.source_revision);
      const cleanTitle = displayTitle(node);
      const rawText = node.text || null;
      const typeText = displayType(node);
      const canGhost = canGhostNode(node);

      // 1. 第一视线：通俗易懂的核心对象属性
      // style-only 且 exact 命中样式目标：显示样式来源，不谈位置权限。
      const hitTarget = (state.styleTargets || []).find(t => Array.isArray(t.scene_ids) && t.scene_ids.includes(node.id)) || null;
      // 1. 第一视线：通俗易懂的核心对象属性
      fields(byId('detail-fields'), hitTarget ? [
        ['对象名称', cleanTitle],
        ['对象类型', typeText],
        ['位置与尺寸', formatBounds(node.bounds_mm)],
        ['样式目标', hitTarget.label || hitTarget.target_id],
        ['样式属性', `${hitTarget.property || ''} · 当前 ${hitTarget.current_pt} pt · ${hitTarget.saved_pt == null ? '尚未保存' : `已保存 ${hitTarget.saved_pt} pt`}`]
      ] : [
        ['对象名称', cleanTitle],
        ['对象类型', typeText],
        ['位置与尺寸', formatBounds(node.bounds_mm)],
        ['编号属性', node.identity_stability === 'stable' ? '固定编号' : '本次临时编号'],
        ['位置调整', (node.registered && canRebuild && canGhost)
          ? '可以试调，检查通过后才能保留'
          : canGhost ? '可以示范位置，不能保留修改' : '仅查看']
      ]);

      // 2. 二级折叠：详细技术参数（收起在 details 内，不淹没首屏）
      if (byId('detail-tech-fields')) {
        const techPairs = [
          ['全局标识 (GID)', node.gid || '未分配'],
          ['底层节点 (ID)', node.id],
          ['显示模式', hitTarget ? '样式可调（右侧样式微调）' : (canRebuild ? '可微调（不改原文件）' : '仅查看（不可编辑）')]
        ];
        if (hitTarget) techPairs.push(['样式目标 ID', hitTarget.target_id]);
        if (rawText && rawText !== cleanTitle) {
          techPairs.push(['原始科学文本', rawText]);
        }
        if (node.annotation) {
          techPairs.push(['关联标签 GID', node.annotation.linked_label_gid || '无']);
          techPairs.push(['峰位锚定数据', JSON.stringify(node.annotation.declared_guide_anchor_data)]);
          techPairs.push(['显示端点坐标 mm', JSON.stringify([node.annotation.displayed_first_run_endpoint_mm, node.annotation.displayed_last_run_endpoint_mm])]);
        } else if (node.linked_guide_gid) {
          techPairs.push(['关联引线 GID', node.linked_guide_gid]);
        }
        if (state.scene?.source_revision) {
          techPairs.push(['配置版本摘要', state.scene.source_revision.slice(0, 16)]);
        }
        if (state.frame?.frame_revision) {
          techPairs.push(['图像校验哈希', state.frame.frame_revision.slice(0, 16)]);
        }
        if (state.lastEvaluation?.checks) {
          techPairs.push(['原始检查结果', state.lastEvaluation.checks]);
        }
        fields(byId('detail-tech-fields'), techPairs);
      }

      byId('detail-ephemeral').hidden = node.identity_stability !== 'ephemeral';
      byId('detail-ephemeral').textContent = '这个编号只在当前图上有效。重新生成图后，请重新选择对象。';

      if (hitTarget) {
        // exact 样式目标：隐藏位置未授权提示，改说样式控制来源（下方样式微调可保存）。
        byId('detail-readonly').hidden = false;
        byId('detail-readonly').textContent = `样式可调：在右侧“样式微调”中改 ${hitTarget.label || hitTarget.target_id}（${hitTarget.property || ''}），预览后确认保存。`;
      } else {
        byId('detail-readonly').hidden = false;
        byId('detail-readonly').textContent = canRebuild
          ? '可以预览位置调整；不会修改原始脚本、配置或正式图片。'
          : '不会修改原图。可移动对象的轮廓来示范位置，但不能保留到图中。';
      }

      if (node.annotation || node.linked_guide_gid || node.type === 'guide') {
        byId('detail-annotation').hidden = false;
        if (node.annotation || node.type === 'guide') {
          // 用户特别指定的通俗引导提示，绝不拼接技术数组
          byId('detail-annotation').textContent = '移动标签时，引线会跟着调整；指向峰的位置不变。这里不能单独移动引线。';
        } else {
          byId('detail-annotation').textContent = `已关联引线：${displayTitle(state.nodes.get(node.linked_guide_gid)) || '对应引线'}。平移本标签时，引线会自动调整并保持指向峰的位置。`;
        }
      }
    }
    updateIntentUI();
    try {
      if (!state.stylePending && state.styleTargets.length && node) {
        for (const t of state.styleTargets) {
          if (Array.isArray(t.scene_ids) && t.scene_ids.includes(node.id) && t.target_id !== state.styleSelected) {
            state.styleSelected = t.target_id; renderStyle(); break;
          }
        }
      }
    } catch (e) {}
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
    byId('object-list-count').textContent = `共 ${nodes.length} 个对象（总计 ${state.scene.nodes.length} 个）`;
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
      metaSpan.textContent = `${displayType(node)} · ${node.identity_stability === 'stable' ? '固定编号' : '本次临时编号'}`;
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
    if (!state.scene || minimal) return;
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

  let lastStageSize = null;
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
    lastStageSize = { width: wrap.clientWidth, height: wrap.clientHeight };
    rulers();
  }

  // 首次 fit() 可能早于最终布局（极简模式的动作条由 hidden 转可见、窄窗口重排），
  // 之后 stage 尺寸变化不会再触发适配，画布就会越过容器被裁切或要滚动。尺寸真的变了才重排。
  const refitStage = () => {
    if (!stageSizeChanged(lastStageSize, wrap.clientWidth, wrap.clientHeight)) return;
    fit();
  };
  if (minimal && typeof ResizeObserver === 'function') new ResizeObserver(refitStage).observe(wrap);

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

  // ---------- P1 拖动：预览留在本地，松开才向引擎要回执 ----------
  function dragReadout(delta, clientX, clientY) {
    const readout = byId('drag-readout');
    if (!readout) return;
    if (!delta) { readout.hidden = true; return; }
    const rect = wrap.getBoundingClientRect();
    readout.hidden = false;
    readout.textContent = `ΔX ${signedMm(delta.dx)} mm · ΔY ${signedMm(delta.dy)} mm（右/上为正）· 预览未验证`;
    // 绝对定位落在 wrap 的 padding box 里，滚动量要补回来，读数才贴着指针
    readout.style.left = `${clientX - rect.left - wrap.clientLeft + wrap.scrollLeft}px`;
    readout.style.top = `${clientY - rect.top - wrap.clientTop + wrap.scrollTop}px`;
  }

  // 拖动期间只改看得见的那几格：**不碰** publishAgentDetail（它会 POST /api/selection）。
  function renderDragPreview(delta, clientX, clientY) {
    const { text, className } = previewStatusText({ dragging: true });
    const badge = byId('intent-status-badge');
    if (badge) { badge.textContent = text; badge.className = className; }
    const line = byId('intent-displacement');
    if (line) line.textContent = `本次调整：ΔX ${delta.dx} mm, ΔY ${delta.dy} mm`;
    const dx = byId('intent-dx'), dy = byId('intent-dy');
    if (dx) dx.value = delta.dx;
    if (dy) dy.value = delta.dy;
    const minLine = byId('min-status');
    if (minLine) {
      minLine.textContent = minimalStatusText({
        node: state.nodes.get(state.selected),
        snapshot: state.intentSession ? state.intentSession.snapshot() : null,
        dragging: true
      });
    }
    dragReadout(delta, clientX, clientY);
  }

  function endDrag() {
    state.drag = null;
    viewport.classList.remove('dragging');
    dragReadout(null);
  }

  // 纯预览：这里没有 fetch，也没有重建；真实验证只在指针松开后发生。
  function dragMove(event) {
    const drag = state.drag;
    if (event.pointerId !== drag.pointerId) return;
    if (!drag.moved) {
      if (Math.abs(event.clientX - drag.x) + Math.abs(event.clientY - drag.y) <= DRAG_THRESHOLD_PX) return;
      drag.moved = true;
      // 新的位移一出现，上一份回执就不再描述眼前这张图
      state.lastEvaluation = null;
      byId('intent-eval-results').hidden = true;
      viewport.classList.add('dragging');
    }
    const delta = dragDeltaMm(drag.rect, state.scene.canvas_bounds_mm, { x: drag.x, y: drag.y }, { x: event.clientX, y: event.clientY });
    if (delta.dx === drag.delta[0] && delta.dy === drag.delta[1]) return;
    drag.delta = [delta.dx, delta.dy];
    state.intentSession.setDelta(delta.dx, delta.dy);
    renderDragPreview(delta, event.clientX, event.clientY);
    highlights();
  }

  viewport.addEventListener('pointermove', event => {
    if (!state.ready) { if (state.drag) endDrag(); return; }
    if (state.pan) {
      wrap.scrollLeft = state.pan.left - (event.clientX - state.pan.x);
      wrap.scrollTop = state.pan.top - (event.clientY - state.pan.y);
      state.pan.moved ||= Math.abs(event.clientX - state.pan.x) + Math.abs(event.clientY - state.pan.y) > 3;
      rulers(); return;
    }
    if (state.drag) { dragMove(event); return; }
    const hovered = candidates(event)[0]?.id || null;
    if (hovered === state.hover) return;
    state.hover = hovered;
    container.dataset.hoverId = state.hover || '';
    viewport.setAttribute('aria-description', state.hover ? displayTitle(state.nodes.get(state.hover)) : '无对象命中');
    highlights();
  });
  viewport.addEventListener('pointerleave', () => {
    if (state.drag) return;
    state.hover = null; container.dataset.hoverId = ''; highlights();
  });
  viewport.addEventListener('pointerdown', event => {
    if (!state.ready) return;
    viewport.focus({ preventScroll: true });
    if (state.space || event.button === 1) {
      event.preventDefault(); viewport.setPointerCapture(event.pointerId);
      state.pan = { x: event.clientX, y: event.clientY, left: wrap.scrollLeft, top: wrap.scrollTop, moved: false };
      viewport.classList.add('panning');
      return;
    }
    // 只拖"当前选中且可 ghost"的对象：指针按在别处时仍旧走点选 / Alt 轮换那条老路；样式模式不拖动。
    if (isStyleOnly()) return;
    const node = state.nodes.get(state.selected);
    if (event.button !== 0 || event.altKey || !state.intentSession || !canGhostNode(node)) return;
    if (candidates(event)[0]?.id !== state.selected) return;
    viewport.setPointerCapture(event.pointerId);
    state.drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, rect: viewport.getBoundingClientRect(), delta: [0, 0], moved: false };
  });
  viewport.addEventListener('pointerup', event => {
    if (!state.ready) { if (state.drag) endDrag(); return; }
    if (state.pan) { state.pan = null; viewport.classList.remove('panning'); return; }
    const drag = state.drag;
    if (drag) {
      endDrag();
      if (event.pointerId !== drag.pointerId) return; // 另一根手指的抬起：这次拖动不归它收尾
      // 真拖动过：选区不动，松开即验证（同一个 evaluate 流程，不另写一套）
      if (drag.moved) {
        const snap = state.intentSession.snapshot();
        const action = dragPointerAction('pointerup', {
          dragging: true,
          hasDelta: drag.delta[0] !== 0 || drag.delta[1] !== 0,
          canEvaluate: snap.canEvaluate
        });
        if (action === 'evaluate') evaluateCurrentIntent();
        else { updateIntentUI(); highlights(); }
        return;
      }
    }
    // 宿主可能在点击后把焦点收回去，极简模式在选中前再确认一次画布焦点
    if (minimal && document.activeElement !== viewport) viewport.focus({ preventScroll: true });
    if (event.button === 0) select(cycleSelection(candidates(event).map(n => n.id), state.selected, event.altKey));
  });
  viewport.addEventListener('pointercancel', () => {
    state.pan = null; viewport.classList.remove('panning');
    if (state.drag) { endDrag(); updateIntentUI(); highlights(); }
  });
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
      if (state.drag) endDrag();
      cancelIntent(true);
      return;
    }
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      // 极简模式宿主（Tern / WebView2）里 SVG 点击后 activeElement 可能停在 body，方向键仍应生效
      if (!acceptsArrowKeys({
        minimal,
        activeElementIsViewport: document.activeElement === viewport,
        hasDocumentFocus: document.hasFocus(),
        inputActive: ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)
      })) return;
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
      return;
    }
    if (document.activeElement !== viewport) return;
    if (event.code === 'Space') { event.preventDefault(); state.space = true; }
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25); }
    if (event.key === '-') { event.preventDefault(); zoom(0.8); }
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
      status('正在取消本次调整…', 'pending');
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
    status('已取消本次调整，已保留的历史不受影响', 'ok');
  }
  byId('btn-cancel-intent').addEventListener('click', () => {
    cancelIntent(true);
  });

  // 唯一的"松开即验证"路径：按钮点击与拖动松开都走它，回执是唯一的成功证据。
  async function evaluateCurrentIntent() {
    if (!state.intentSession) return;
    const snap = state.intentSession.snapshot();
    if (!snap.intent || !snap.canEvaluate) return;
    state.pendingOperationId = snap.intent.operation_id;
    const token = state.inFlightGuard.start(snap.intent.operation_id, snap.intent.delta_mm);
    state.evaluating = true;
    status('正在重新绘图并检查新位置…', 'pending');
    updateIntentUI();
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
      const verifyText = data.verification_level === 'RENDER_CHECKED' ? '已重新绘图，位置检查通过' : data.verification_level;
      byId('eval-state-text').textContent = `状态：${statusText} · 验证：${verifyText}`;
      fields(byId('eval-fields'), [
        ['目标位移', `Δ [${data.target_delta_mm?.join(', ')}] mm`],
        ['实测位移', `Δ [${data.measured_delta_mm?.map(v => Number(v.toFixed(4))).join(', ')}] mm`],
        ['位移误差', data.error_mm != null ? `${Number(data.error_mm.toFixed(4))} mm` : '无'],
        ['安全检查', (data.checks || []).map(c => {
          const name = { science: '科学内容', qa: '排版安全', target: '目标位置', impact: '其他对象' }[c.check] || '其他检查';
          const outcome = { OK: '通过', PASS: '通过', FAIL: '未通过' }[c.status] || '未确认，请查看详细技术参数';
          return `${name}：${outcome}`;
        }).join('；') || '未返回检查明细']
      ]);
      const acceptable = canAcceptEvaluation(data, currentSnap.intent);
      byId('btn-accept').disabled = !acceptable;
      if (data.frame && isDecisionSuccessful(data)) {
        await loadFrame(data.frame, undefined, false);
      } else {
        if (state.candidateFrame && state.acceptedFrame) {
          await loadFrame(state.acceptedFrame, undefined, false);
        }
        status(acceptable ? '已更新位置预览 · 尚未保留本次调整' : `检查未通过：${data.message || data.status || '位移或安全检查不符合要求'}`, acceptable ? 'ok' : 'error');
      }
    } catch (e) {
      status(`检查请求失败：${e.message}`, 'error');
    } finally {
      state.evaluating = false;
      updateIntentUI();
    }
  }
  byId('btn-evaluate').addEventListener('click', () => { evaluateCurrentIntent(); });

  byId('btn-accept').addEventListener('click', async () => {
    if (!state.intentSession || !state.lastEvaluation) return;
    const snap = state.intentSession.snapshot();
    if (!canAcceptEvaluation(state.lastEvaluation, snap.intent)) {
      status('无法保留：未通过位置安全检查', 'error');
      return;
    }
    const baseline = state.acceptedFrame || state.frame;
    const payload = buildDecisionPayload(baseline, snap.intent.operation_id, 'accept');
    status('正在保留本次调整…', 'pending');
    try {
      const res = await fetch('/api/intents/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!isDecisionSuccessful(data)) {
        status(`保留未通过：${data.message || data.status}`, 'error');
        return;
      }
      state.operationStack.push(snap.intent.operation_id);
      const newFrame = data.accepted_frame || data.frame || state.candidateFrame;
      state.acceptedFrame = newFrame;
      state.candidateFrame = null;
      if (newFrame) await loadFrame(newFrame, undefined, true);
      state.intentSession.cancel();
      state.pendingSaves = addPendingSave(state.pendingSaves, { id: snap.intent.operation_id, target: 'config', params: ['（旧值） → （新值）'], diff: '（源码差异）' });
      renderPendingSaves();
      state.lastEvaluation = null;
      byId('intent-eval-results').hidden = true;
      updateIntentUI();
      highlights();
      status('已保留本次调整（只保留在当前服务中，未保存到文件）', 'ok');
    } catch (e) {
      status(`保留失败：${e.message}`, 'error');
    }
  });

  byId('btn-undo').addEventListener('click', async () => {
    const current = state.acceptedFrame || state.frame;
    const canRebuild = !!(current?.session && current.session.can_evaluate !== false && current.session.source_revision);
    if (!canRebuild) {
      status('这张图只能查看和示范，没有可撤销的已保留调整', 'error');
      return;
    }
    if (!state.operationStack.canUndo()) {
      status('当前没有可撤销的调整', 'pending');
      return;
    }
    const opId = state.operationStack.pop();
    const payload = buildDecisionPayload(current, opId, 'undo');
    status('正在撤销上一步调整…', 'pending');
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
      status('已撤销上一步调整，已恢复之前的状态', 'ok');
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
      status('这张图暂不支持重新绘制，不能切换显示清晰度', 'error');
      return;
    }
    status(`正在切换至 ${dpi} DPI 显示清晰度…`, 'pending');
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
      status(`已切换至 ${dpi} DPI 显示清晰度`, 'ok');
    } catch (e) {
      status(`清晰度切换失败：${e.message}`, 'error');
    }
  }

  byId('btn-dpi-120').addEventListener('click', () => changeQuality(120));
  byId('btn-dpi-240').addEventListener('click', () => changeQuality(240));
  if (byId('btn-dpi-600')) byId('btn-dpi-600').addEventListener('click', () => changeQuality(600));

  root.addEventListener('blur', () => { state.space = false; state.pan = null; viewport.classList.remove('panning'); if (state.drag) endDrag(); });
  root.addEventListener('resize', fit);

  // ---------- G18 样式微调：只读选择 + 预览/确认，几何 UI 不动 ----------
  function styleSetBusy(busy) {
    state.styleBusy = busy;
    for (const id of ['style-preview', 'style-restore', 'style-confirm', 'style-cancel', 'style-value', 'style-target']) {
      const el = byId(id); if (el) el.disabled = busy;
    }
    for (const id of ['btn-evaluate', 'btn-accept', 'btn-apply-delta', 'save-changes']) {
      const el = byId(id); if (el && busy) el.disabled = true;
    }
    if (!busy) updateIntentUI();
  }
  function styleNote(msg, show) {
    const el = byId('style-notice'); if (!el) return;
    el.hidden = !show; if (show && msg) el.textContent = msg;
  }
  // 可读标签 + data-style-state 供测试断言：verifying/validated/saving/saved/failed/cancelled/previewed/idle。
  function styleBadge(text, st) {
    const el = byId('style-status'); if (!el) return;
    el.textContent = text; el.className = 'tag';
    const map = { verifying: 'verifying', validated: 'validated', saving: 'saving', saved: 'saved', failed: 'failed', cancelled: 'cancelled', previewed: 'previewed', idle: 'idle' };
    el.dataset.styleState = map[st] || 'idle';
  }
  function styleSelect() { return byId('style-target'); }
  function styleLabel(t) {
    const labels = { ylabel: 'Y轴标签', xlabel: 'X轴标签', 'x tick labels': 'X轴刻度', 'y tick labels': 'Y轴刻度' };
    return labels[t?.label] || t?.label || t?.target_id || '';
  }
  function frameHasStyle(fr) {
    return !!(fr && fr.style && Array.isArray(fr.style.targets) && fr.style.targets.length);
  }
  function isStyleOnly() {
    const fr = state.acceptedFrame || state.frame || {};
    if (state.styleTargets.length || frameHasStyle(fr)) return true;
    const sess = fr.session;
    return !!(sess && sess.can_evaluate === false);
  }
  function styleDisable(msg) {
    const sec = byId('style-section'); if (sec) sec.hidden = false;
    for (const id of ['style-preview', 'style-restore', 'style-confirm', 'style-cancel', 'style-value', 'style-target']) {
      const el = byId(id); if (el) el.disabled = true;
    }
    styleBadge('样式不可用', 'failed');
    styleNote(msg || '样式数据异常，已拒绝样式编辑', true);
  }
  function refreshStyleFromFrame(frame) {
    const sec = byId('style-section'); if (!sec) return;
    const st = frame && frame.style ? frame.style : null;
    if (st) {
      const finiteNum = v => typeof v === 'number' && Number.isFinite(v);
      // current 必须 finite number；saved 允许 null（尚未保存）或 finite number。
      const bad = typeof st.overlay_sha256 !== 'string' || !(st.overlay_sha256 === '' || /^[0-9a-f]{64}$/.test(st.overlay_sha256))
        || !Array.isArray(st.targets)
        || st.targets.some(t => !t || typeof t.target_id !== 'string' || !t.target_id
          || !finiteNum(t.current_pt) || !(t.saved_pt == null || finiteNum(t.saved_pt))
          || (t.scene_ids != null && !Array.isArray(t.scene_ids)));
      if (bad) {
        state.styleTargets = []; state.styleOverlaySha = null; state.stylePending = null;
        sec.hidden = false; styleDisable('样式数据校验失败，已拒绝样式编辑（正式文件未改动）');
        const tm = byId('style-timings'); if (tm) tm.hidden = true;
        return;
      }
    }
    if (st && st.refresh_required) {
      // Draft/normal commit truth identical: bytes saved, frame refresh
      // failed. Keep targets editable iff a later /api/frame recovers
      // (refreshStyleFromFrame re-runs); until then freeze new edits.
      state.styleRefreshFailed = true;
      state.styleTargets = st && Array.isArray(st.targets) && st.targets.length ? st.targets : [];
      state.stylePending = null;
      if (typeof st.overlay_sha256 === 'string') state.styleOverlaySha = st.overlay_sha256;
      renderStyle();
      styleBadge('文件已保存，但界面刷新失败', 'saved');
      styleNote('文件已保存，但界面刷新失败。请重载页面核对（正式文件已保存，无需重做）。', true);
      return;
    }
    const sec2 = byId('style-section'); if (sec2) sec2.hidden = !st;
    state.styleTargets = st && Array.isArray(st.targets) ? st.targets : [];
    state.styleOverlaySha = st ? (st.overlay_sha256 || '') : '';
    state.styleBaseRev = (st && st.base_frame_revision) || (frame && frame.frame_revision) || null;
    const targets = state.styleTargets;
    const still = targets.some(t => t.target_id === state.styleSelected);
    if (!still) {
      const node = state.nodes.get(state.selected);
      let mapped = null;
      if (node) {
        for (const t of targets) {
          if (Array.isArray(t.scene_ids) && t.scene_ids.includes(node.id)) { mapped = t.target_id; break; }
        }
      }
      state.styleSelected = mapped || targets[0].target_id;
    }
    if (state.stylePending && st && !st.pending && !st.candidate_id) state.stylePending = null;
    renderStyle();
  }
  function styleTarget() {
    return state.styleTargets.find(t => t.target_id === state.styleSelected) || null;
  }
  // exact scene_id 映射（服务端注册身份），无则 null；绝不做邻近/文本猜测。
  function mapStyleToScene(target) {
    if (!target || !Array.isArray(target.scene_ids) || !target.scene_ids.length) return null;
    for (const sid of target.scene_ids) { if (state.nodes.has(sid)) return sid; }
    return null;
  }
  function renderStyle() {
    const sel = styleSelect(); if (!sel) return;
    sel.replaceChildren();
    for (const t of state.styleTargets) {
      const o = document.createElement('option');
      o.value = t.target_id;
      o.textContent = styleLabel(t);
      sel.append(o);
    }
    if (state.styleSelected) sel.value = state.styleSelected;
    const t = styleTarget();
    const input = byId('style-value');
    if (input && t) { input.value = t.current_pt; input.setAttribute('aria-label', `${styleLabel(t)}（${t.property || ''}，当前 ${t.current_pt} pt）`); }
    const p = state.stylePending;
    const pw = byId('style-pending');
    if (pw) pw.hidden = !p;
    if (p) {
      const pt = byId('style-pending-text');
      const pl = styleLabel(state.styleTargets.find(x => x.target_id === p.target_id)) || p.target_id;
      const issues = Number.isFinite(Number(p.issue_count)) ? Number(p.issue_count) : null;
      if (pt) {
        const base = p.new_pt == null
          ? `待确认：${pl} ${p.old_pt} pt → 原始样式（移除覆盖）（影响 ${Array.isArray(p.affected) ? p.affected.length : 0} 个对象）`
          : `待确认：${pl} ${p.old_pt} → ${p.new_pt} pt（影响 ${Array.isArray(p.affected) ? p.affected.length : 0} 个对象）`;
        pt.textContent = (p.is_draft && issues != null)
          ? `本次修改通过局部审计，但原图仍有${issues}项整图问题未通过；保存工作草稿后仍不能合规导出。${base}`
          : base;
      }
      styleBadge(p.is_draft ? '已验证 · 待确认（草稿）' : '已验证 · 待确认', 'validated');
      const cf = byId('style-confirm');
      if (cf) cf.textContent = p.is_draft ? '保存工作草稿' : '确认保存';
    } else if (t && !['verifying', 'saving', 'failed', 'cancelled'].includes(byId('style-status')?.dataset.styleState)) {
      const st = (state.acceptedFrame && state.acceptedFrame.style) || (state.frame && state.frame.style) || {};
      const dIssues = Number.isFinite(Number(st.issue_count)) ? Number(st.issue_count) : null;
      const isDraft = !!st.workspace_draft || !!st.draft;
      const cf = byId('style-confirm');
      if (cf) cf.textContent = '确认保存';
      if (byId('style-status')?.dataset.styleState === 'saved') { /* keep 已保存/草稿 verdict across renders */ }
      else if (isDraft && dIssues != null) styleBadge(`工作草稿 · 整图未通过（${dIssues}项）`, 'saved');
      else styleBadge(t.saved_pt == null ? `当前 ${t.current_pt} pt · 原始样式` : `当前 ${t.current_pt} pt · 已保存`, 'idle');
    }
    const tm = byId('style-timings');
    const tw = byId('style-timing-wrap');
    if (tm) {
      const parts = [];
      if (state.styleClientMs != null) parts.push(['本机渲染耗时', `${Math.round(state.styleClientMs)} ms`]);
      if (state.styleServerMs != null) parts.push(['服务端耗时', `${Math.round(state.styleServerMs)} ms`]);
      if (state.styleOverlaySha) parts.push(['样式版本', String(state.styleOverlaySha).slice(0, 12)]);
      if (parts.length) fields(tm, parts);
      if (tw) tw.hidden = parts.length === 0;
    }
    const rs = byId('style-restore');
    const frozen = !!state.styleRefreshFailed;
    if (frozen) for (const id of ['style-preview', 'style-restore', 'style-confirm', 'style-cancel', 'style-value', 'style-target']) {
      const el = byId(id); if (el) el.disabled = true;
    }
    if (rs && !state.styleBusy && !frozen) rs.disabled = !t || t.saved_pt == null;
  }
  async function styleJson(url, body, withToken) {
    const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    if (withToken) headers['X-Figpact-Ui'] = uiToken();
    const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
    let data = null; try { data = await res.json(); } catch (e) { data = null; }
    return { res, data };
  }
  function styleFail(data, res) {
    const code = data && typeof data.status === 'string' ? data.status : `HTTP ${res.status}`;
    const msg = data && typeof data.message === 'string' && data.message ? `：${data.message}` : '';
    return `${code}${msg}`;
  }
  async function stylePreview(remove) {
    const t = styleTarget(); if (!t || state.styleBusy) return;
    const input = byId('style-value');
    const value = remove ? undefined : Number(input ? input.value : NaN);
    if (!remove && (!Number.isFinite(value) || value < 1 || value > 72)) { styleNote('请输入 1–72 之间的 pt 数值', true); return; }
    const rev = (state.acceptedFrame || state.frame || {}).frame_revision;
    if (!rev) { styleNote('当前帧无效，请刷新', true); return; }
    styleSetBusy(true); styleBadge('验证中…', 'verifying'); styleNote('', false);
    const t0 = performance.now();
    try {
      const body = remove ? { frame_revision: rev, target_id: t.target_id, remove: true }
        : { frame_revision: rev, target_id: t.target_id, value };
      const { res, data } = await styleJson('/api/style/preview', body, false);
      if (data && data.style && data.style.timings_ms) {
        const tm = data.style.timings_ms;
        state.styleServerMs = tm.preview_ms ?? tm.commit_ms ?? tm.rebuild_ms ?? null;
      }
      if (!res.ok || !data || !data.frame) throw new Error(styleFail(data, res));
      if (data.style && data.style.pending) {
        state.stylePending = data.style.pending;
        // 后端 pending 自带 base_frame_revision + expected_sha256；缺失才用包络回退。
        if (state.stylePending.base_frame_revision == null && data.style.base_frame_revision) state.stylePending.base_frame_revision = data.style.base_frame_revision;
        if (state.stylePending.expected_sha256 == null && data.style.overlay_sha256 != null) state.stylePending.expected_sha256 = data.style.overlay_sha256;
      }
      await loadFrame(data.frame, undefined, false);
      state.styleClientMs = Math.round(performance.now() - t0);
      renderStyle();
      styleBadge(state.stylePending ? '已验证 · 待确认' : '已预览', state.stylePending ? 'validated' : 'previewed');
    } catch (e) {
      const msg = String((e && e.message) || '');
      if (/OVERLAY_CONFLICT|STALE_REVISION|UNKNOWN_ID|STYLE_REJECTED|INVALID/.test(msg)) {
        state.stylePending = null;
        try {
          const fr = await (await fetch('/api/frame', { headers: { Accept: 'application/json' } })).json();
          if (fr && fr.schema === 'figpact.inspector/1') await loadFrame(fr, undefined, true);
        } catch (ee) {}
      }
      styleBadge('预览失败', 'failed'); styleNote(`样式预览失败：${msg}`, true);
    }
    finally { styleSetBusy(false); renderStyle(); }
  }
  async function styleCommit() {
    const p = state.stylePending; if (!p || state.styleBusy) return;
    const rev = p.base_frame_revision || state.styleBaseRev
      || (state.acceptedFrame || state.frame || {}).frame_revision;
    const sha = (p.expected_sha256 != null) ? p.expected_sha256
      : (((state.acceptedFrame || state.frame || {}).style || {}).overlay_sha256 ?? state.styleOverlaySha ?? '');
    if (!rev || sha == null) { styleNote('版本信息缺失，请刷新后重试', true); return; }
    const draftBody = p.is_draft
      ? { candidate_id: p.candidate_id, frame_revision: rev, expected_sha256: sha, save_draft: true }
      : { candidate_id: p.candidate_id, frame_revision: rev, expected_sha256: sha };
    styleSetBusy(true); styleBadge('保存中…', 'saving');
    try {
      const { res, data } = await styleJson('/api/style/commit', draftBody, true);
      if (data && data.style && data.style.timings_ms) {
        const tm = data.style.timings_ms;
        state.styleServerMs = tm.commit_ms ?? tm.preview_ms ?? tm.rebuild_ms ?? null;
      }
      if (!res.ok || !data) throw new Error(styleFail(data, res));
      // Commit truth: ov.apply 已写盘（COMMITTED/COMMITTED_DRAFT），frame 为
      // null + refresh_required 只说明服务端刷新新帧失败：文件已保存，作废
      // 无新帧的编辑/选区，提示重载恢复。草稿与正常两路都走同一保护。
      if ((data.status === 'COMMITTED' || data.status === 'COMMITTED_DRAFT') && !data.frame) {
        state.stylePending = null;
        state.styleRefreshFailed = true;
        state.styleTargets = [];
        if (data.style && typeof data.style.overlay_sha256 === 'string') state.styleOverlaySha = data.style.overlay_sha256;
        try { select(null); } catch (e) {}
        try {
          const fr = await (await fetch('/api/frame', { headers: { Accept: 'application/json' } })).json();
          if (fr && fr.schema === 'figpact.inspector/1' && fr.style && !fr.style.refresh_required) {
            state.styleRefreshFailed = false;
            await loadFrame(fr, undefined, true);
          }
        } catch (ee) {}
        styleBadge(data.status === 'COMMITTED_DRAFT' ? '工作草稿已保存，但界面刷新失败' : '文件已保存，但界面刷新失败', 'saved');
        styleNote('文件已保存，但界面刷新失败。请重载页面核对（正式文件已保存，无需重做）。', true);
        return;
      }
      state.stylePending = null;
      let uiError = null;
      try {
        await loadFrame(data.frame, undefined, true);
        if (state.styleSelected) {
          const sid = mapStyleToScene(styleTarget());
          if (sid) select(sid);
        }
        if (data.status === 'COMMITTED_DRAFT') {
          const st = (data.style || {});
          const n = Number.isFinite(Number(st.issue_count)) ? Number(st.issue_count) : null;
          styleBadge(n != null ? `工作草稿已保存 · 整图未通过（${n}项）` : '工作草稿已保存 · 整图未通过', 'saved');
        } else styleBadge('已保存并验证', 'saved');
        styleNote('', false);
      } catch (uiE) { uiError = uiE; }
      if (uiError) {
        // receipt 已 COMMITTED/PASS：正式文件已保存，只报 UI 呈现问题，绝不说未改动。
        styleBadge('已保存 · 显示刷新异常', 'saved');
        styleNote(`已保存并通过验证，但结果显示刷新失败：${uiError && uiError.message ? uiError.message : uiError}。请刷新页面核对。`, true);
      }
    } catch (e) {
      const msg = String((e && e.message) || '');
      if (/OVERLAY_CONFLICT|CANDIDATE_UNKNOWN|STALE_REVISION|FORBIDDEN|DRAFT_REQUIRES_EXPLICIT_SAVE/.test(msg)) {
        state.stylePending = null;
        try {
          const fr = await (await fetch('/api/frame', { headers: { Accept: 'application/json' } })).json();
          if (fr && fr.schema === 'figpact.inspector/1') await loadFrame(fr, undefined, true);
        } catch (ee) {}
      }
      styleBadge('保存失败', 'failed');
      styleNote(/NOT_WRITTEN|DRAFT_REQUIRES/.test(msg) ? `样式保存失败：${msg}（正式文件未改动）` : `样式保存结果未知：${msg}。请刷新页面核对正式文件。`, true);
    }
    finally { styleSetBusy(false); renderStyle(); }
  }
  async function styleCancel() {
    const p = state.stylePending; if (!p || state.styleBusy) return;
    styleSetBusy(true);
    try {
      const { res, data } = await styleJson('/api/style/cancel', { candidate_id: p.candidate_id }, true);
      if (!res.ok) throw new Error(styleFail(data, res));
      state.stylePending = null;
      const fr = await (await fetch('/api/frame', { headers: { Accept: 'application/json' } })).json();
      if (fr && fr.schema === 'figpact.inspector/1') await loadFrame(fr, undefined, true);
      styleBadge('已取消', 'cancelled');
    } catch (e) { styleNote(`取消失败：${e.message}`, true); }
    finally { styleSetBusy(false); renderStyle(); }
  }
  function wireStyle() {
    const sel = styleSelect(); if (!sel || sel.dataset.wired) return;
    sel.dataset.wired = '1';
    sel.addEventListener('change', () => {
      if (state.stylePending) {
        styleNote('有待确认的样式预览，请先确认保存或取消，再切换目标', true);
        sel.value = state.styleSelected;
        return;
      }
      state.styleSelected = sel.value; renderStyle();
    });
    byId('style-preview')?.addEventListener('click', () => stylePreview(false));
    byId('style-restore')?.addEventListener('click', () => stylePreview(true));
    byId('style-confirm')?.addEventListener('click', styleCommit);
    byId('style-cancel')?.addEventListener('click', styleCancel);
  }
  wireStyle();

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
      if (byId('detail-tech-fields')) byId('detail-tech-fields').replaceChildren();
      if (byId('detail-tech-wrap')) byId('detail-tech-wrap').hidden = true;
      byId('calibration-note').hidden = true;
      container.dataset.hoverId = container.dataset.selectedId = '';
      select(null);
    }
    container.dataset.ready = 'false';
    container.dataset.frameState = 'loading';
    status(isNewAccepted ? '正在读取图形数据…' : '正在核对新位置图像与尺寸…', 'pending');
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
        { btn: byId('btn-dpi-120'), dpi: 120, title: '流畅视图 (120 DPI)，仅改变显示' },
        { btn: byId('btn-dpi-240'), dpi: 240, title: '清晰视图 (240 DPI)，仅改变显示' },
        { btn: byId('btn-dpi-600'), dpi: 600, title: '精细视图 (600 DPI)，仅改变显示' }
      ];
      const currentDpi = scene.measurement?.dpi;
      try { const seg = document.querySelector('.segmented-dpi'); if (seg) seg.hidden = frameHasStyle(frame); } catch (e) {}
      for (const item of dpiButtons) {
        if (!item.btn) continue;
        item.btn.disabled = !canRebuild;
        if (!canRebuild) {
          item.btn.title = '当前图件不支持切换显示清晰度';
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
        if (frame.style && Array.isArray(frame.style.targets) && frame.style.targets.length) {
          badge.textContent = 'Style Overlay';
          badge.className = 'tag mode-session';
        } else if (canRebuild) {
          badge.textContent = '可试调 / 不改原文件';
          badge.className = 'tag mode-session';
        } else {
          badge.textContent = '仅查看';
          badge.className = 'tag mode-static';
        }
      }

      // 底栏系统与信息（收折在 details 中）
      fields(byId('state-fields'), [
        ['图形渲染引擎', scene.measurement?.renderer || 'Agg (光栅底层 + 矢量辅助)'],
        ['当前显示清晰度', `${scene.measurement?.dpi || 120} DPI`],
        ['页面物理尺寸', `${Number((scene.canvas_bounds_mm[2] - scene.canvas_bounds_mm[0]).toFixed(2))} × ${Number((scene.canvas_bounds_mm[3] - scene.canvas_bounds_mm[1]).toFixed(2))} mm`],
        ['源码版本摘要', scene.source_revision ? scene.source_revision.slice(0, 16) : '无配置 / 未提供'],
        ['图像校验哈希', frame.frame_revision ? frame.frame_revision.slice(0, 16) : '无']
      ]);
      byId('calibration-note').hidden = false;
      byId('calibration-note').textContent = '标尺显示图片在论文中的尺寸，不是屏幕上的实际长度。线条按中心线测量；文字按外围矩形测量。';

      if (isNewAccepted) {
        byId('frame-revision').textContent = frame.frame_revision.slice(0, 12);
        status('图片已加载 · 尺寸核对一致', 'ok');
        wrap.scrollLeft = wrap.scrollTop = 0;
        fit();
        objectList();
        select(null);
      } else if (state.candidateFrame) {
        byId('frame-revision').textContent = `${state.acceptedFrame?.frame_revision?.slice(0, 12) || ''} (预览: ${frame.frame_revision.slice(0, 8)})`;
        status(frame.style || state.stylePending ? '样式预览 · 尚未保存' : '已更新位置预览 · 尚未保留本次调整', 'pending');
        select(state.selected);
      } else {
        byId('frame-revision').textContent = frame.frame_revision.slice(0, 12);
        select(state.selected);
      }
      updateIntentUI();
      try {
        refreshStyleFromFrame(frame);
      } catch (e) {
        styleDisable(`样式数据异常，已拒绝样式编辑：${e && e.message ? e.message : e}（正式文件未改动）`);
      }
      try {
        if (isStyleOnly()) {
          const isec = byId('intent-section'); if (isec) isec.hidden = true;
          const hint = byId('stage-hint');
          if (hint) hint.textContent = '悬停查看 · 单击选中样式目标 · 右侧样式微调只改字号与线宽';
        } else {
          const hint = byId('stage-hint');
          if (hint && hint.dataset.orig == null) hint.dataset.orig = hint.textContent;
        }
      } catch (e) {}
      try { root.FIGPACT_INSPECTOR_FRAME = frame; } catch (e) {}
      api.currentFrame = () => state.candidateFrame || state.acceptedFrame || state.frame || null;
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
  // G5b：首次发布之前先按 Hub 现值播种（取不到就退化成较大的本地随机起点）。
  ensureSelectionSeeded();
  // G5b：待授权计划条。轮询是为了让客户端刚铸造的计划自动出现；服务器仍是本机回环。
  refreshPlans();
  setInterval(refreshPlans, 3000);
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
  // G7b 保存按钮：先展示差异，确认后才调用
  (function wireSave() {
    const btn = byId('save-changes');
    const conf = byId('save-confirmation');
    const preview = byId('save-diff-preview');
    const confirmBtn = byId('save-confirm');
    const cancelBtn = byId('save-cancel');
    const result = byId('save-result');
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (preview) preview.textContent = state.pendingSaves.map(x => x.diff).join('\n');
      const ct = byId('save-confirmation-text');
      if (ct) ct.textContent = '有待保存修改';
      if (conf) conf.hidden = false;
    });
    if (cancelBtn) cancelBtn.addEventListener('click', () => { if (conf) conf.hidden = true; });
    if (confirmBtn) confirmBtn.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Figpact-Ui': uiToken() }, body: JSON.stringify({}) });
        const data = await res.json();
        if (result) result.textContent = saveResultText(data);
        if (data && data.source_commit_state === 'COMMITTED') {
          state.pendingSaves = [];
          renderPendingSaves();
        }
        if (conf) conf.hidden = true;
      } catch (e) {
        if (result) result.textContent = '写入结果未知，请核对文件（请检查目标文件与 journal）';
      }
    });
  })();
})(globalThis);
