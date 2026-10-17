"""G5a 会话 Hub（G5b 追加计划授权）：只读选区、接收几何任务、调用既有试算。

G5a 的协调层：读选区、收几何任务、调既有 ``IntentSession.evaluate``；不另建 Figure、
不另算科学、不另做 QA。任务路由仍**不授予源码写入或发布权限**。状态只在内存、会话级、
不落盘；服务器是单线程 ``HTTPServer``，写入天然串行。

G5b 追加一条**被约束的**源码写入路径（``/api/plans`` 系列）：计划由服务端用
``python_native.plan_layout_edit``（已声明 ``LAYOUT_MM`` 的脚本，单位 mm）或
``authoring.plan_authoring_binding``（无任何绑定的脚本，最小作者化补丁，单位 pt）铸造
（**零字节**写用户源码），只有页面带着服务端
签发、注入 ``/frame.js`` 的会话令牌同意过，且**申请该计划的客户端**在应用时磁盘字节
仍逐文件等于计划里的 ``before_sha256``，才走 ``source_writes.apply_source_change``
落盘并追加 history 的 ``source_change`` 检查点。授权主体（``client_id``）、操作范围
（哪份计划 / 哪些文件 / 哪个 gid）、计划版本（``plan_id`` + before 哈希）与磁盘事实
四者齐备才写；请求 body 里的布尔字段永远不构成授权。两种 ``kind`` 只在**铸造**时分岔，
authorize/apply/cancel 走同一条校验链。

诚实边界：这是**本机单用户**的同意绑定（回环 + 同源 + 页面会话令牌），**不是**多用户
认证。计划与 grant 是内存态、会话级：进程重启即失去所有批准，这是设计意图。

**P0a：写入语义与验证语义是两个字段，互不推导。**
``commit_state``（``COMMITTED_AND_VERIFIED`` 等）是**兼容字段**，名字里的 ``VERIFIED``
只指 journal 与逐文件磁盘字节的核对——它**不是**科学/几何验证结论。写盘成功之后，本模块
另起进程重建一次（``python_native.verify_committed_source``），把结论放进
``figure_verification_state``；写入与否放进 ``source_commit_state``。界面只有在
``source_commit_state='COMMITTED'`` **且** ``figure_verification_state='PASS'`` 时才允许
说"修改已保存并通过验证"；写盘已成事实而验证没过/没跑完，只能说"源码已提交，图形验证
失败/未完成"。验证证据绑定当时脚本的 sha256，源码事后再变一个字节，旧结论即失效。

公开方法返回 ``(payload, http_status)`` 以便 HTTP 路由直接回包，但本模块
不依赖 HTTP，也不依赖 matplotlib。

**P1-b：Agent 上下文（只读）。** ``read_agent_context`` 把选定图元的一次
``scene`` / ``constraints`` / ``impact`` 交给 Agent：全部取自既有真值（帧的 canonical
scene、Hub 的选区通道、会话背后 ``FigureSession`` 的契约声明与归属闭包），不另建真值副本、
不产生候选、不写盘、不改选区。它**同样不是授权**：能改什么、改到什么程度仍由既有通道裁决
（``submit_task`` → ``evaluate``，或计划 → apply → 验证）。ghost 只是预览资格；预览≠验证、
写盘≠科学验证这两条边界见上面 P0a 与 ``docs/AGENT_LAYOUT_PROTOCOL.md``。
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import authoring, python_native, source_writes
from .history import HistoryError, HistoryStore, default_state_home

FORBIDDEN_KINDS = ('source_write', 'publish', 'delete', 'git')
FORBIDDEN_MESSAGE = 'G5a Hub 只允许读取选区、提交几何任务并调用既有试算；不授予源码写入或发布权限'
MAX_TASKS = 50
#: 计划与 grant 的会话级上限：FIFO 淘汰最旧的一条（grant 与计划同生共死）。
MAX_PLANS = 50
#: 计划（与由其结出的 grant）的有效期，默认 15 分钟。
PLAN_TTL = timedelta(minutes=15)
#: 页面会话同意令牌与申请客户端身份的请求头。授权是 header + 服务端令牌，不是 body 布尔字段。
UI_TOKEN_HEADER = 'X-Figpact-Ui'
CLIENT_HEADER = 'X-Figpact-Client'
#: 已声明排版绑定的脚本：改 `LAYOUT_MM` 的**那一个**字面量（单位 mm）。
PLAN_KIND = 'layout_edit'
#: 无任何绑定脚本：走 ``authoring.plan_authoring_binding`` 的最小作者化补丁（单位 pt）。
#: 两种 kind 铸造出的都是**同一种计划**，之后 authorize/apply/cancel 完全同一条校验链。
AUTHORING_KIND = 'authoring_edit'
PLAN_KINDS = (PLAN_KIND, AUTHORING_KIND)
# GET /api/selection 的 stale 判定字段：发布值必须与实时会话一致。
REVISION_FIELDS = (('session_id', '会话'), ('scene_revision', '图帧'), ('source_revision', '源文件'))

#: 只读 Agent 上下文通道（P1-b）的 schema 名：scene / constraints / impact 三部分。
AGENT_CONTEXT_SCHEMA = 'figpact.hub.agent_context/1'
#: ghost（预览轮廓）资格的唯一规则在页面侧；hub 只按它读**既有** Scene 字段，不另立判据。
GHOST_RULE_SOURCE = 'figpact/_inspector/inspector.js:canGhostNode（预览资格，不构成可写结论）'
#: 三部分各自的既有真值来源，随回执一起给：读的人不必猜谁说了算。
CONTEXT_SOURCES = {
    'scene': 'session.snapshot() 的 canonical scene（scene_json：既有 Scene 构建 + Inspector 投影）',
    'selection': 'Hub 的 /api/selection 通道（页面发布的选区）',
    'bindings': 'FigureSession.parameters()：契约声明的参数范围/单位/可变性/作用域/objects',
    'closure': 'FigureSession.owned_closure()：契约 nodes/groups 的权威归属闭包',
    'science': 'IntentSession._science 的 digest（引擎 evaluate 科学冻结用的同一份捕获）',
    'ghost': GHOST_RULE_SOURCE,
}


def _finite_pair(value):
    """两个有限数字的位移 ``[dx, dy]``（毫米）；其它形状（含 NaN/inf/布尔）返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            return None
        out.append(float(item))
    return out


def _canonical_scene(frame):
    """帧里的 canonical scene（既有 Scene 构建 + Inspector 投影）；解析不出来返回 None。"""
    if not isinstance(frame, dict):
        return None
    raw = frame.get('scene_json')
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _ghost_state(node):
    """``(可 ghost, 阻止原因)``：按页面唯一规则读既有 Scene 字段，服务端不另立一套判据。

    规则本体是 ``figpact/_inspector/inspector.js:canGhostNode``（P1-a 的拖动预览）。这里只把
    同一组**既有字段**翻成可读回执：类型 / 清单附着 annotation / gid 含 guide / 未测量 /
    被完全裁掉。ghost 是**预览**资格，**不是**"引擎会受理这次改动"的结论。
    """
    blockers = []
    kind = node.get('type')
    if kind in ('guide', 'curve', 'panel'):
        blockers.append(f'{kind}：不做刚体轮廓预览')
    if node.get('annotation'):
        blockers.append('带清单附着关系的引线：不做独立预览')
    gid = str(node.get('gid') or '')
    if 'guide' in gid:
        blockers.append(f'gid 含 guide（{gid}）')
    if not node.get('measured'):
        blockers.append('未测量：没有可比对的轮廓')
    if node.get('fully_clipped'):
        blockers.append('被完全裁掉：没有可见轮廓')
    return (not blockers), blockers


def _agent_node_entry(node, *, selected):
    """Scene 节点 → 上下文条目：身份/文本/包围盒/可 ghost 性 + 既有判定字段，原样不补。"""
    ghostable, blockers = _ghost_state(node)
    entry = {'gid': node.get('gid'), 'type': node.get('type'), 'text': node.get('text'),
             'bounds_mm': node.get('bounds_mm'), 'measured': bool(node.get('measured')),
             'fully_clipped': bool(node.get('fully_clipped')), 'ghostable': ghostable,
             'scope': node.get('scope'), 'registered': bool(node.get('registered')),
             'parent': node.get('parent'), 'hit_mode': node.get('hit_mode'),
             'science_policy': node.get('science_policy'),
             'controlled_by': [list(path) for path in (node.get('controlled_by') or ())],
             'selected': selected}
    if blockers:
        entry['ghost_blockers'] = blockers
    if node.get('hit_note'):
        entry['hit_note'] = node['hit_note']
    if node.get('linked_guide_gid'):
        entry['linked_guide_gid'] = node['linked_guide_gid']
    if isinstance(node.get('annotation'), dict):
        entry['annotation'] = copy.deepcopy(node['annotation'])
    return entry


def _error(status, message):
    return {'status': status, 'message': message}


def _not_run_verification():
    """没写盘就没图可验：``NOT_RUN`` 是事实，不是失败（也**不是**未验证的通过）。"""
    return {'state': python_native.FIGURE_NOT_RUN, 'measured_mm': None, 'evidence': None,
            'problems': []}


def _refuse(code, message, http_status):
    """写盘路径的拒绝：**磁盘一个字节都没动**，两个状态照实说。

    "拒绝"不等于"验证过的成功"，也不等于"写了但没验"——它连写都没写。把这两个字段
    一并在拒绝里说清楚，调用方才不用从 ``status`` 反推磁盘事实。
    """
    return {**_error(code, message),
            'commit_state': python_native.NOT_WRITTEN,
            'source_commit_state': python_native.SOURCE_NOT_WRITTEN,
            'figure_verification_state': python_native.FIGURE_NOT_RUN,
            'figure_verification': None}, http_status


def _sha256_file(path):
    """磁盘此刻的字节事实；读不出来（含不存在）返回 None——那同样是"与 before 不符"。"""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


class SessionHub:
    """内存态 Hub；不落盘、不写 history、不改用户文件（G5b 授权路径除外，且只在授权后）。"""

    def __init__(self, state_home=None, source=None, ui_token=None):
        self.selection = None
        self.selection_seq = None
        self.hub_revision = 0
        self.tasks = deque(maxlen=MAX_TASKS)
        # G5b：状态目录（journal/blob 落这里；用户源码不在这里）与页面会话令牌。
        self.state_home = Path(state_home).expanduser() if state_home is not None \
            else default_state_home()
        #: 这次源码写入在 history 里的工作区身份（script/config/scope）；未知就不伪造历史。
        self.source = dict(source) if source else {}
        self.ui_token = ui_token
        self._plans: dict[str, dict] = {}
        self._grants: dict[str, dict] = {}

    # 选区：页面 → Hub

    def publish_selection(self, body):
        if not isinstance(body, dict):
            return _error('INVALID_SELECTION', '请求必须是 JSON 对象'), 400
        seq = body.get('selection_seq')
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            return _error('INVALID_SELECTION', 'selection_seq 必须是非负整数'), 400
        if self.selection_seq is not None and seq <= self.selection_seq:
            return _error('INVALID_SELECTION',
                          f'selection_seq 必须严格递增（当前 {self.selection_seq}）'), 400
        selected = body.get('selected')
        if selected is not None and (not isinstance(selected, dict) or not selected.get('gid')):
            return _error('INVALID_SELECTION', 'selected 给了就必须有 gid'), 400
        self.selection = copy.deepcopy(body)
        self.selection_seq = seq
        self.hub_revision += 1
        return {'status': 'OK', 'selection_seq': seq, 'hub_revision': self.hub_revision}, 200

    # 选区：任意本地客户端 ← Hub

    def read_selection(self, session):
        live = self._live(session)
        reason = self._stale_reason(live)
        return {'status': 'OK', 'hub_revision': self.hub_revision,
                'selection': copy.deepcopy(self.selection),
                'stale': reason is not None, 'stale_reason': reason,
                'session_id': live.get('session_id'),
                'scene_revision': live.get('scene_revision'),
                'source_revision': live.get('source_revision'),
                'accepted_operation_ids': list(live.get('accepted_operation_ids') or [])}, 200

    # 任务：Agent → Hub

    def submit_task(self, body, session):
        if not isinstance(body, dict):
            return _error('INVALID_TASK', '请求必须是 JSON 对象'), 400
        task_id = body.get('task_id')
        if not isinstance(task_id, str) or not task_id:
            return _error('INVALID_TASK', 'task_id 必须是非空字符串'), 400
        kind = body.get('kind')
        if kind in FORBIDDEN_KINDS or body.get('source_write') or body.get('publish'):
            return _error('FORBIDDEN', FORBIDDEN_MESSAGE), 403
        if kind == 'layout_request':
            self._record(body, task_status='RECORDED')
            return {'status': 'OK', 'task_id': task_id, 'task_status': 'RECORDED',
                    'hub_revision': self.hub_revision}, 200
        if kind != 'geometry':
            return _error('INVALID_TASK', 'kind 只能是 geometry 或 layout_request'), 400
        if self.selection is None or body.get('selection_seq') != self.selection_seq:
            return _error('STALE_SELECTION', '选区已过期；请先读取当前选区再提交几何任务'), 409
        reason = self._stale_reason(self._live(session))
        if reason is not None:
            return _error('STALE_SELECTION', reason), 409
        selected = self.selection.get('selected') or {}
        gid = selected.get('gid')
        target = body.get('target_gid') or gid
        if not gid or target != gid:
            return _error('STALE_SELECTION', 'target_gid 与当前选区身份不一致'), 409
        delta = body.get('delta_mm', self.selection.get('delta_mm'))
        if delta is None:
            return _error('INVALID_TASK', '几何任务必须给出 delta_mm'), 400
        guide = selected.get('linked_guide_gid')
        # 与页面示范同形的 intent：只平移、科学保护开启、引线跟随仅按科学清单显式关联。
        intent = {'operation_id': body.get('operation_id') or f'hub-{uuid.uuid4()}',
                  'session_id': self.selection.get('session_id'),
                  'scene_revision': self.selection.get('scene_revision'),
                  'source_revision': self.selection.get('source_revision'),
                  'scope': self.selection.get('scope'),
                  'target_gid': target, 'operation': 'translate', 'delta_mm': delta,
                  'tolerance_mm': body.get('tolerance_mm', 0.01),
                  'preserve': {'science': True, 'follow_gids': [guide] if guide else [],
                               'fixed_gids': []},
                  'demonstration': {'display_only': True}}
        result = session.evaluate(intent)
        self._record(body, task_status='EVALUATED', target_gid=target,
                     evaluate_status=(result or {}).get('status'))
        return {'status': 'OK', 'task_id': task_id, 'task_status': 'EVALUATED',
                'hub_revision': self.hub_revision, 'evaluate': result}, 200

    def read_tasks(self):
        return {'status': 'OK', 'hub_revision': self.hub_revision,
                'tasks': [copy.deepcopy(task) for task in self.tasks]}, 200

    # Agent 上下文：任意本地客户端 ← Hub（**只读**；不建第二套真值）

    def read_agent_context(self, session, body=None):
        """只读上下文：``scene`` / ``constraints`` / ``impact``，供 Agent 起草多目标改动。

        输入（``body``，字段全可选）：``gid``（缺省用已发布选区的 GID）、``delta_mm``（候选
        位移，两个毫米数）、``intent``（自然语言意图文本，**只原样回显**，本通道不解释它）。

        三部分全部来自既有真值：``session.snapshot()`` 的 canonical scene（既有 Scene 构建 +
        Inspector 投影）、Hub 的 selection 通道、会话背后 ``FigureSession`` 的契约与
        ``owned_closure``。本方法**不**调用 ``evaluate``（那会铸造候选并改会话状态）、
        **不**写盘、**不**改选区、**不**另算科学或几何，也不在前端之外重推一遍判据。

        这不是审批：能改什么、改到什么程度，仍由既有通道裁决（``submit_task`` → ``evaluate``，
        或计划 → apply → verify）。ghost 只是预览资格；写盘与科学验证仍是两个独立状态。
        """
        if body is not None and not isinstance(body, dict):
            return _error('INVALID_CONTEXT', '请求必须是 JSON 对象（或省略）'), 400
        body = body or {}
        wanted = body.get('gid')
        if wanted is not None and (not isinstance(wanted, str) or not wanted):
            return _error('INVALID_CONTEXT', 'gid 给了就必须是非空字符串'), 400
        delta = None if body.get('delta_mm') is None else _finite_pair(body.get('delta_mm'))
        if body.get('delta_mm') is not None and delta is None:
            return _error('INVALID_CONTEXT', 'delta_mm 必须是两个有限数字 [dx, dy]（毫米）'), 400
        intent_text = body.get('intent')
        if intent_text is not None and not isinstance(intent_text, str):
            return _error('INVALID_CONTEXT', 'intent 必须是字符串'), 400
        try:
            frame = session.snapshot()
        except RuntimeError as error:
            return _error('SESSION_CLOSED', f'会话不可读：{error}'), 409
        scene = _canonical_scene(frame)
        if scene is None:
            return _error('SCENE_UNAVAILABLE', '帧里没有可解析的 canonical scene（scene_json）'), 409
        nodes = [node for node in (scene.get('nodes') or ()) if isinstance(node, dict)]
        registered = [node for node in nodes if node.get('gid')]
        selection = self.selection or {}
        published = selection.get('selected')
        asked = wanted or (published.get('gid') if isinstance(published, dict) else None)
        target = next((node for node in nodes if node.get('gid') == asked), None) if asked else None
        live = self._live(session)
        stale = self._stale_reason(live)
        engine = self._engine(session)
        scope = str((target or {}).get('scope') or selection.get('scope')
                    or scene.get('scope') or '')
        in_scope = [node for node in registered if str(node.get('scope')) == scope]
        outside = {}
        for node in registered:
            if str(node.get('scope')) != scope:
                outside[str(node.get('scope'))] = outside.get(str(node.get('scope')), 0) + 1

        # --- scene：该图元 scope 内的清单 + 当前选中的那条 ---------------------- #
        scene_view = {
            'source': CONTEXT_SOURCES['scene'],
            'scene_revision': frame.get('frame_revision'),
            'scene_sha256': frame.get('scene_sha256'),
            'scope': scope,
            'scope_source': ('target_node' if target is not None
                             else 'selection' if selection.get('scope') else 'frame'),
            'unit': scene.get('unit'),
            'coordinate_reference': scene.get('coordinate_reference'),
            'canvas_bounds_mm': scene.get('canvas_bounds_mm'),
            'image': scene.get('image'),
            'measurement': scene.get('measurement'),
            'ghost_rule': GHOST_RULE_SOURCE,
            'selected': (target or {}).get('gid'),
            'nodes': [_agent_node_entry(node, selected=node is target) for node in in_scope],
            'nodes_outside_scope': outside,
            'diagnostics': list(scene.get('diagnostics') or ()),
        }

        # --- constraints：允许/禁止、坐标空间与硬限、冻结科学指纹、不可微调项 ------ #
        follow = [target['linked_guide_gid']] if target and target.get('linked_guide_gid') else []
        allow = sorted({target['gid'], *follow}) if target is not None else []
        deny = sorted(node['gid'] for node in registered
                      if node['gid'] not in allow and not node.get('structural'))
        bindings = self._agent_bindings(engine, allow)
        hard_limits = {
            'declared_bindings': bindings,
            'delta_requested_mm': delta,
            'canvas_bounds_mm': scene.get('canvas_bounds_mm'),
            'source': CONTEXT_SOURCES['bindings'],
            'rule': '范围与画布硬限由引擎在受理期裁决（OUT_OF_RANGE / GEOMETRY_REJECTED）；'
                    '绑定要成为候选，其声明的 objects 必须整体落在许可集合内'
                    '（objects_within_allow=false 的绑定不服务于本次选择）',
            'note': '本通道只回声明与集合关系，不另立算式',
        }
        if engine is None:
            hard_limits['engine_unavailable'] = (
                'SOURCE_IDENTITY_UNKNOWN：这次会话没有可读的 FigureSession（普通 Figure 会话），'
                '契约声明读不到，不猜范围')
        constraints = {
            'source': {'allow': CONTEXT_SOURCES['selection'],
                       'hard_limits': CONTEXT_SOURCES['bindings'],
                       'frozen_science': CONTEXT_SOURCES['science']},
            'scope': scope,
            'allow_gids': allow,
            'deny_gids': deny,
            'follow_gids': follow,
            'fixed_gids': [],
            'rule': '许可集合 = {选中 GID} ∪ {清单显式关联的引线}；集合外非结构图元的任何几何'
                    '变化都判 IMPACT_MISMATCH（structural 图元由引擎排除在外）',
            'coordinate_space': {
                'unit': scene.get('unit'),
                'reference': scene.get('coordinate_reference'),
                'canvas_bounds_mm': scene.get('canvas_bounds_mm'),
                'calibrated': bool((scene.get('measurement') or {}).get('calibrated')),
                'note': '毫米是渲染器栅格量；本引擎不声称已做物理标定',
            },
            'hard_limits': hard_limits,
            'frozen_science': self._science_facts(session, frame, in_scope),
            'not_independently_tunable': self._untunable(target, in_scope),
        }
        if target is not None and selection.get('scope') \
                and str(selection.get('scope')) != scope:
            constraints['scope_mismatch'] = {
                'selection_scope': selection.get('scope'), 'target_scope': scope,
                'why': '引擎只受理与当前 scope 一致的平移意图；跨 scope 候选会被拒绝'}

        # --- impact：候选改动会牵动谁，以及为什么 ------------------------------ #
        attached = [{'gid': guide, 'relation': 'guide',
                     'why': '清单声明的标签↔引线附着：标签端随动、科学端固定'}
                    for guide in follow]
        target_paths = {tuple(path) for path in ((target or {}).get('controlled_by') or ())}
        co_bound, cross_scope = [], []
        for node in registered:
            if node is target:
                continue
            shared = sorted({tuple(path) for path in (node.get('controlled_by') or ())}
                            & target_paths)
            if not shared:
                continue
            entry = {'gid': node['gid'], 'path': [list(path) for path in shared],
                     'why': '与选中对象同一条声明绑定：该绑定被重建时它们一起动'}
            (cross_scope if str(node.get('scope')) != scope else co_bound).append(entry)
        for binding in bindings:
            scopes = {str(item) for item in (binding.get('scopes') or ())}
            if scopes - {scope}:
                cross_scope.append({
                    'binding': binding.get('path'), 'scopes': sorted(scopes),
                    'why': '该绑定声明的作用域不止本 scope：跨输出版本的候选会被引擎拒绝'
                           '（NEEDS_AUTHORING）'})
        closure = []
        if engine is not None and target is not None:
            try:
                closure = list(engine.owned_closure([target['gid']]))
            except (AttributeError, TypeError):
                closure = []
        impact = {
            'candidate': ({'gid': target['gid'], 'delta_mm': delta, 'intent_text': intent_text}
                          if target is not None and (delta is not None or intent_text) else None),
            'attached': attached,
            'ownership_closure': closure,
            'co_bound': co_bound,
            'cross_scope': cross_scope,
            'unchanged_rule': '许可集合外非结构图元变化一点即 IMPACT_MISMATCH；'
                              'structural 图元由引擎排除在外',
            'rules': [
                '本通道只描述、不审批：改动仍走既有通道（submit_task → evaluate，或计划 → '
                'apply → 验证）。',
                '引擎只受理当前 scope 的明确平移（translate），且只对本帧已测量的稳定 GID；'
                '科学曲线、引线端点与非刚体不被受理为整体平移。',
                '引线跟随只能是清单显式关联的那一条：follow_gids 必须恰好等于 '
                '[linked_guide_gid]，fixed_gids 必须为空。',
                '科学保护不能关闭：即便位移达标，科学载荷指纹变了也一律拒绝（SCIENCE_CHANGED）。',
                '画布边界是硬限：候选造成新的画布越界即 GEOMETRY_REJECTED。',
            ],
            'sources': {'attached': CONTEXT_SOURCES['scene'],
                        'ownership_closure': CONTEXT_SOURCES['closure'],
                        'co_bound': CONTEXT_SOURCES['bindings'],
                        'cross_scope': CONTEXT_SOURCES['bindings']},
        }

        if asked and target is None:
            status, http = 'UNKNOWN_GID', 404
        elif not asked:
            status, http = 'NO_SELECTION', 200
        else:
            status, http = 'OK', 200
        payload = {'status': status, 'schema': AGENT_CONTEXT_SCHEMA,
                   'hub_revision': self.hub_revision, 'selection_seq': self.selection_seq,
                   'session_id': live.get('session_id'),
                   'frame_revision': frame.get('frame_revision'),
                   'scene_sha256': frame.get('scene_sha256'),
                   'source_revision': live.get('source_revision'),
                   'stale': stale is not None, 'stale_reason': stale,
                   'scope': scope, 'target_gid': (target or {}).get('gid'),
                   'intent_text': intent_text,
                   'intent_note': 'intent 只原样回显：本通道不把它解释成任何改动，多目标改动仍由'
                                  ' Agent 起草、由既有通道裁决',
                   'scene': scene_view, 'constraints': constraints, 'impact': impact}
        if status == 'UNKNOWN_GID':
            payload['message'] = f'{asked!r} 不在本帧场景里；scene.nodes 是本帧已知的图元清单'
        return payload, http

    # 上下文内部：读既有对象，不造真值

    @staticmethod
    def _engine(session):
        """会话背后的 ``FigureSession``（契约/归属的唯一真值）；拿不到返回 None，不伪造。"""
        return getattr(session, '_core', None)

    @staticmethod
    def _agent_bindings(engine, allow):
        """与许可集合相关的**声明**参数（契约 parameters）；读不到就不猜，返回 []。"""
        if engine is None or not allow:
            return []
        try:
            records = engine.parameters()
        except (AttributeError, TypeError):
            return []
        wanted = set(allow)
        out = []
        for record in records:
            objects = {str(item) for item in (record.get('objects') or ())}
            if not objects & wanted:
                continue
            out.append({'path': list(record.get('path') or ()), 'key': record.get('key'),
                        'unit': record.get('unit'), 'operation': record.get('operation'),
                        'axis': record.get('axis'), 'scale': record.get('scale'),
                        'mutability': record.get('mutability'), 'min': record.get('min'),
                        'max': record.get('max'), 'scopes': list(record.get('scopes') or ()),
                        'objects': sorted(objects),
                        # 引擎铸造候选的前置条件（objects 必须整体落在许可集合内），
                        # 只做集合比较，不重算任何几何。
                        'objects_within_allow': objects <= wanted})
        return out

    @staticmethod
    def _science_facts(session, frame, nodes):
        """冻结科学载荷的指纹与逐图元策略；拿不到就说拿不到，不伪造一个指纹。"""
        captured = getattr(session, '_science', None)
        digest = captured.get('digest') if isinstance(captured, dict) else None
        facts = {'manifest_declared': bool((frame.get('session') or {}).get('can_evaluate')),
                 'digest': digest,
                 'policy_by_gid': {node['gid']: node.get('science_policy') for node in nodes
                                   if node.get('science_policy')},
                 'source': CONTEXT_SOURCES['science']}
        if digest is None:
            facts['reason'] = ('SCIENCE_CAPTURE_UNAVAILABLE：此会话没有可读的科学载荷捕获'
                               '（普通 Figure 会话或历史只读会话），不伪造指纹')
        return facts

    @staticmethod
    def _untunable(target, nodes):
        """已知不可独立微调项：引线端点、科学曲线本体；选中项本身不可 ghost 时一并说明。"""
        out = []
        for node in nodes:
            annotation = node.get('annotation')
            if isinstance(annotation, dict) and annotation.get('independent_endpoint_editable') is False:
                out.append({'gid': node.get('gid'),
                            'why': '引线端点不可独立微调（清单声明）：只随标签整体平移'})
            elif node.get('type') == 'curve':
                out.append({'gid': node.get('gid'),
                            'why': '科学曲线不是刚体：不被受理为整体平移，只能按声明为 EDITABLE '
                                   '的曲线位移参数整体移动'})
        if target is not None:
            ghostable, blockers = _ghost_state(target)
            if not ghostable:
                out.append({'gid': target.get('gid'),
                            'why': '选中项不能作为刚体轮廓预览（' + '；'.join(blockers)
                                   + '）：这是**预览**资格，引擎是否受理仍以 evaluate 回执为准'})
        return out

    # 计划：Agent → Hub（铸造；零字节写用户源码）

    def create_plan(self, body):
        """定位 → 铸造计划（写 journal/blob 与内存状态）。定位不到就原样透传拒绝，不铸造。

        服务端铸造的是 ``plan_id`` 与这份计划自己的 ``before_sha256``：授权只对**这一版**
        源码有效，之后磁盘上被任何人改过一个字节，应用都会被 ``STALE_SOURCE`` 挡住。

        ``kind='layout_edit'`` 走 ``python_native.plan_layout_edit``（改已声明的 ``LAYOUT_MM``
        字面量，单位 mm）；``kind='authoring_edit'`` 走 ``authoring.plan_authoring_binding``
        （无绑定脚本的最小作者化补丁，单位 pt）。两者都只出计划、零字节写用户源码。
        """
        if not isinstance(body, dict):
            return _error('INVALID_PLAN', '请求必须是 JSON 对象'), 400
        client_id = body.get('client_id')
        if not isinstance(client_id, str) or not client_id:
            return _error('INVALID_PLAN', 'client_id 必须是非空字符串'), 400
        kind = body.get('kind')
        if kind not in PLAN_KINDS:
            return _error('INVALID_PLAN', f'kind 只能是 {" 或 ".join(PLAN_KINDS)}'), 400
        script, gid = body.get('script'), body.get('gid')
        if not isinstance(script, str) or not script or not isinstance(gid, str) or not gid:
            return _error('INVALID_PLAN', 'script 与 gid 必须是非空字符串'), 400
        reason = body.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            return _error('INVALID_PLAN', 'reason 必须说明这次修改为什么发生'), 400
        if kind == AUTHORING_KIND:
            planned = authoring.plan_authoring_binding(
                Path(script), gid, body.get('value_pt'),
                base_offset_pt=body.get('base_offset_pt'),
                state_home=self.state_home, reason=reason)
        else:
            planned = python_native.plan_layout_edit(Path(script), gid, body.get('value'),
                                                     state_home=self.state_home, reason=reason)
        if planned.get('status') != 'OK':
            # 值非法/定位歧义/需要作者级改动：原样透传生成器的拒绝，不铸造计划。
            return planned, 409 if planned.get('status') != 'INVALID' else 400
        journal = planned['journal']
        requested = planned['value_pt'] if kind == AUTHORING_KIND else body['value']
        now = datetime.now(timezone.utc)
        plan = {'plan_id': uuid.uuid4().hex, 'client_id': client_id, 'kind': kind,
                'script': str(Path(script)), 'gid': gid,
                'value': [float(item) for item in requested], 'reason': reason,
                'journal_id': journal['id'],
                'files': [{field: entry[field]
                           for field in ('path', 'before_sha256', 'after_sha256', 'diff')}
                          for entry in journal['files']],
                'created_at': now.isoformat(), 'expires_at': (now + PLAN_TTL).isoformat(),
                'state': 'PENDING',
                # 两个**独立**状态（互不推导）：铸造时源码一个字节没写，图也没验过。
                'source_commit_state': python_native.SOURCE_NOT_WRITTEN,
                'figure_verification_state': python_native.FIGURE_NOT_RUN,
                'figure_verification': None}
        if kind == AUTHORING_KIND:
            # 单位是计划的一部分：pt 与 mm 之间差 2.8 倍，读的人不能靠猜。
            plan['units'] = authoring.OFFSET_UNITS
            plan['base_offset_pt'] = [float(item) for item in planned['base_offset_pt']]
        self._plans[plan['plan_id']] = plan
        while len(self._plans) > MAX_PLANS:
            oldest = next(iter(self._plans))
            del self._plans[oldest]
            self._grants.pop(oldest, None)
        return {'status': 'OK', 'plan': copy.deepcopy(plan)}, 200

    def read_plans(self):
        """任意本地客户端 ← Hub：最近 50 条计划及其状态（含 grant 是否还活着）。

        每条计划带上两个独立状态。``figure_verification_state`` 是**此刻**的答案：验证证据
        绑定了当时那份脚本的 sha256，磁盘字节事后再变一个字节，旧的 ``PASS`` 就不再是当前
        文件的验证结果（``figure_verification_stale`` + 原因，旧证据原样保留在
        ``figure_verification`` 里供审计）。
        """
        plans = []
        for plan_id, plan in self._plans.items():
            public = copy.deepcopy(plan)
            grant = self._grants.get(plan_id)
            public['grant'] = None if grant is None else {
                'plan_id': grant['plan_id'], 'authorized_at': grant['authorized_at'],
                'expires_at': grant['expires_at'], 'single_use': True,
                'used': bool(grant.get('used'))}
            public.update(self._verification_view(public))
            plans.append(public)
        return {'status': 'OK', 'plans': plans}, 200

    # 计划：页面 → Hub（同意）

    def authorize_plan(self, plan_id, token):
        """页面会话同意：header 带服务端注入 ``/frame.js`` 的令牌，缺/错一律 403。

        这不是一个布尔开关：令牌由服务端在**服务这个页面时**签发并注入页面，body 里的
        ``authorized: true`` 之类字段在这里不存在，也就永远不构成授权。
        """
        if not isinstance(token, str) or not token or not isinstance(self.ui_token, str) \
                or not hmac.compare_digest(token, self.ui_token):
            return _error('FORBIDDEN', f'同意必须来自服务端注入 {UI_TOKEN_HEADER} 页面会话令牌的'
                                       ' Inspector 页面；请求体里的布尔字段不是授权'), 403
        plan = self._plans.get(plan_id)
        if plan is None:
            return _error('PLAN_UNKNOWN', f'计划 {plan_id} 不存在'), 409
        if self._expired(plan['expires_at']):
            return _error('PLAN_EXPIRED', f"计划 {plan_id} 已在 {plan['expires_at']} 过期"), 409
        if plan['state'] != 'PENDING':
            return _error('PLAN_NOT_PENDING',
                          f"计划 {plan_id} 当前状态 {plan['state']}，不能再授权"), 409
        now = datetime.now(timezone.utc)
        grant = {'plan_id': plan_id, 'authorized_at': now.isoformat(),
                 'expires_at': plan['expires_at'], 'single_use': True, 'used': False}
        plan['state'] = 'AUTHORIZED'
        self._grants[plan_id] = grant
        return {'status': 'OK', 'grant': copy.deepcopy(grant)}, 200

    # 计划：申请该计划的客户端 → Hub（写盘）

    def apply_plan(self, plan_id, client_id):
        """写盘前的全部校验通过才动手；任一条不过就一个字节都不写。

        校验顺序：计划存在且 ``AUTHORIZED`` → 计划未过期 → 请求方就是申请该计划的
        ``client_id`` → grant 存在、未过期、未使用 → 底层 journal 仍 ``PREPARED`` 且
        before 哈希与计划一致 → **磁盘每个文件仍逐字节等于计划的 ``before_sha256``**。

        写盘是事实之后，回执**两个独立状态，谁也不从谁推导**：

        - ``source_commit_state``（``NOT_WRITTEN`` / ``COMMITTED`` /
          ``RECOVERY_REQUIRED``）：源码是否安全提交；
        - ``figure_verification_state``（``NOT_RUN`` / ``PASS`` / ``FAIL`` / ``ERROR``）：
          写盘**之后**另起进程重建一次得到的图形验证结论，证据（脚本 sha256 / gid /
          scope / 请求与实测位移 / 残差 / 科学指纹）绑在这次提交的版本上；
        - ``commit_state`` 是**兼容字段**，只表达原有写入语义，**不含**科学/几何结论。
        """
        if not isinstance(client_id, str) or not client_id:
            return _refuse('FORBIDDEN',
                           f'写盘必须带 {CLIENT_HEADER} 表明自己是申请该计划的客户端', 403)
        plan = self._plans.get(plan_id)
        if plan is None:
            return _refuse('PLAN_UNKNOWN', f'计划 {plan_id} 不存在', 409)
        if plan['state'] != 'AUTHORIZED':
            code = {'PENDING': 'PLAN_NOT_PENDING', 'CANCELLED': 'PLAN_CANCELLED',
                    'APPLIED': 'PLAN_APPLIED'}.get(plan['state'], 'PLAN_NOT_PENDING')
            return _refuse(code, f"计划 {plan_id} 当前状态 {plan['state']}，不能应用", 409)
        if self._expired(plan['expires_at']):
            return _refuse('PLAN_EXPIRED', f"计划 {plan_id} 已在 {plan['expires_at']} 过期", 409)
        if client_id != plan['client_id']:
            return _refuse('FORBIDDEN', f'计划 {plan_id} 是客户端 {plan["client_id"]} 申请的；'
                                        f'拒绝客户端 {client_id} 应用', 403)
        grant = self._grants.get(plan_id)
        if grant is None:
            return _refuse('GRANT_UNKNOWN', f'计划 {plan_id} 没有可用 grant', 409)
        if grant.get('used'):
            return _refuse('GRANT_ALREADY_USED',
                           f'计划 {plan_id} 的 grant 已经用过（单次使用）', 409)
        if self._expired(grant['expires_at']):
            return _refuse('GRANT_EXPIRED',
                           f"计划 {plan_id} 的 grant 已在 {grant['expires_at']} 过期", 409)
        try:
            journal = source_writes._load_journal(self.state_home, plan['journal_id'])
        except source_writes.SourceWriteError as error:
            return _refuse('JOURNAL_UNKNOWN', str(error), 409)
        planned_before = {entry['path']: entry['before_sha256'] for entry in plan['files']}
        journal_before = {entry['path']: entry['before_sha256'] for entry in journal['files']}
        if journal.get('status') != 'PREPARED' or journal_before != planned_before:
            return _refuse('JOURNAL_NOT_PREPARED',
                           f"journal {plan['journal_id']} 状态 {journal.get('status')}、"
                           'before 哈希与计划不一致，拒绝应用', 409)
        stale = [entry['path'] for entry in plan['files']
                 if _sha256_file(entry['path']) != entry['before_sha256']]
        if stale:
            return _refuse('STALE_SOURCE',
                           f'磁盘字节与计划不符（外部改写）：{", ".join(sorted(stale))}；'
                           '拒绝覆盖，一个字节都不写', 409)
        # 到这儿才是"要写"：grant 立刻记为已用（单次使用），再交给 G3b 的可恢复写入。
        grant['used'] = True
        plan['state'] = 'APPLIED'
        # 写盘**之前**先量基线：位移是"改后减改前"，没有基线就证明不了任何事。量不到也照写，
        # 因为授权与写入不依赖验证——那时验证如实报 ERROR，不许冒充通过。
        baseline = self._baseline_geometry(plan)
        try:
            applied = source_writes.apply_source_change(plan['journal_id'], state_home=self.state_home)
        except source_writes.SourceWriteError as error:
            # 写入前校验失败：磁盘一个字节没动，如实说 NOT_WRITTEN（写入动作执行过这件事
            # 在 journal 里，回执只报磁盘此刻的事实）。
            refused = _refuse(
                'STALE_SOURCE' if str(error).startswith('STALE_SOURCE') else 'NOT_WRITTEN',
                str(error), 409)[0]
            return {**refused, 'plan_id': plan_id, 'journal_id': plan['journal_id']}, 409
        commit_state = python_native._journal_commit_state(applied)
        source_state = python_native.source_commit_state_of(commit_state)
        verification = (self._figure_verification(plan, baseline)
                        if source_state == python_native.SOURCE_COMMITTED
                        else _not_run_verification())
        plan.update({'source_commit_state': source_state,
                     'figure_verification_state': verification['state'],
                     'figure_verification': verification['evidence']})
        checkpoint_id, history_error = (None, None)
        if source_state == python_native.SOURCE_COMMITTED:
            checkpoint_id, history_error = self._append_source_change(plan, applied, verification)
        answer = {'status': 'OK' if source_state == python_native.SOURCE_COMMITTED else commit_state,
                  # 兼容字段：**只**表达写入语义（journal + 逐文件字节核对），已验证的字节
                  # 不包含任何科学/几何结论；新前端读下面两个独立字段，不从它推导。
                  'commit_state': commit_state,
                  'source_commit_state': source_state,
                  'figure_verification_state': verification['state'],
                  'figure_verification': verification['evidence'],
                  'measured_mm': verification['measured_mm'],
                  'problems': verification['problems'],
                  'plan_id': plan_id, 'journal_id': plan['journal_id'], 'state': plan['state'],
                  'checkpoint_id': checkpoint_id}
        if history_error:
            answer['history_error'] = history_error
        return answer, 200 if source_state == python_native.SOURCE_COMMITTED else 409

    # 计划：页面或客户端 → Hub（取消）

    def cancel_plan(self, plan_id):
        """取消＝零写入；已经落盘的计划不可取消（写盘是事实，不能靠状态掩盖）。"""
        plan = self._plans.get(plan_id)
        if plan is None:
            return _error('PLAN_UNKNOWN', f'计划 {plan_id} 不存在'), 409
        if plan['state'] == 'APPLIED':
            return _error('PLAN_APPLIED', f'计划 {plan_id} 已经写盘，不能取消（要走历史恢复）'), 409
        plan['state'] = 'CANCELLED'
        self._grants.pop(plan_id, None)
        return {'status': 'OK', 'plan_id': plan_id, 'state': 'CANCELLED',
                'plan': copy.deepcopy(plan)}, 200

    # 内部

    def _workspace(self):
        """history 的工作区身份（config/scope）；服务端不知道身份时 config 为 None。"""
        return self.source.get('config'), self.source.get('scope') or 'main'

    def _baseline_geometry(self, plan):
        """写盘**之前**在自己的重建探针上量一次（另起进程）；量不到返回 None。

        量不到**不拦写盘**：授权与写入不依赖验证，验证没跑完就如实报 ERROR——把用户
        授权过的写入卡在一个探针上，是拿验证去要挟写入。
        """
        config, scope = self._workspace()
        if not config:
            return None
        try:
            return python_native._measure_geometry(Path(plan['script']), Path(config), scope)
        except python_native.LayoutBindingError:
            return None

    def _figure_verification(self, plan, baseline):
        """写盘已成事实之后的**独立**验证：另起进程重建，证据绑定这次提交的脚本 sha256。"""
        config, scope = self._workspace()
        if not config:
            return {'state': python_native.FIGURE_ERROR, 'measured_mm': None, 'evidence': None,
                    'problems': ['SOURCE_IDENTITY_UNKNOWN：不知道 config/scope，无法独立重建']}
        requested, tolerance = self._requested_mm(plan)
        return python_native.verify_committed_source(
            script=plan['script'], config=config, scope=scope, gid=plan['gid'],
            requested_mm=requested, tolerance_mm=tolerance, baseline=baseline)

    @staticmethod
    def _requested_mm(plan):
        """计划里请求的位移 → ``(毫米, 该用的容差)``。

        ``layout_edit`` 的 ``value`` 本来就是毫米；``authoring_edit`` 的 ``value`` 是 pt
        （调用现场 ``textcoords="offset points"``），1 pt = 25.4/72 mm，容差按
        ``VERIFY_TOL_PT_MM`` 那一档（与 ``tests/test_authoring_writeback.py`` 同一档）。
        """
        if plan.get('units') == authoring.OFFSET_UNITS:
            return [value * 25.4 / 72.0 for value in plan['value']], python_native.VERIFY_TOL_PT_MM
        return [float(value) for value in plan['value']], python_native.VERIFY_TOL_MM

    @staticmethod
    def _verification_view(plan):
        """报告**此刻**的验证状态：证据绑定的不是当前磁盘字节，旧结论就不算数。"""
        state = plan.get('figure_verification_state') or python_native.FIGURE_NOT_RUN
        evidence = plan.get('figure_verification')
        if plan.get('source_commit_state') != python_native.SOURCE_COMMITTED or not evidence:
            return {'figure_verification_state': state, 'figure_verification_stale': False}
        if python_native.verification_is_current(evidence, plan['script']):
            return {'figure_verification_state': state, 'figure_verification_stale': False}
        # 源码在验证之后又变过：旧的 PASS/FAIL 都不是这份磁盘字节的结论。
        return {'figure_verification_state': python_native.FIGURE_NOT_RUN,
                'figure_verification_stale': True,
                'figure_verification_stale_reason': 'SOURCE_CHANGED'}

    def _append_source_change(self, plan, journal, verification):
        """写盘已成事实 → 在 history 追加 ``source_change`` 检查点（返回 (检查点 id, 错误)）。

        history 的工作区身份（script/config/scope）来自会话；身份不明时**不伪造**一个
        工作区，如实回报 ``SOURCE_IDENTITY_UNKNOWN``：检查点缺失是事实，编一个更糟。
        """
        config, scope = self._workspace()
        if not config:
            return None, 'SOURCE_IDENTITY_UNKNOWN'
        store = None
        try:
            store = HistoryStore(plan['script'], config, scope, state_home=self.state_home)
            head = store.head()
            payload = {'kind': 'source_change', 'reason': plan['reason'], 'gid': plan['gid'],
                       'plan_id': plan['plan_id'], 'journal_id': journal['id'],
                       # 兼容字段：只表达写入语义；两个新字段各自独立，见模块文档。
                       'commit_state': python_native.COMMITTED_AND_VERIFIED,
                       'source_commit_state': python_native.SOURCE_COMMITTED,
                       'figure_verification_state': verification['state'],
                       'figure_verification': verification['evidence'],
                       'file_changes': python_native._journal_file_changes(journal)}
            if plan.get('units'):
                # 作者化写回的位移是 pt（offset points）；写进 mm 的字段名会骗读历史的人。
                payload.update({'units': plan['units'], 'requested_pt': plan['value']})
            else:
                payload['requested_mm'] = plan['value']
            checkpoint = store.append_source_change(
                payload,
                expected_head=None if head is None else head['id'],
                expected_file_sha256={entry['path']: entry['after_sha256']
                                      for entry in journal['files']})
            return checkpoint['id'], None
        except (HistoryError, OSError, ValueError) as error:
            return None, f'{type(error).__name__}: {error}'
        finally:
            if store is not None:
                store.close()

    @staticmethod
    def _expired(stamp):
        """过期判定按**事实**：时间戳读不出来（形状非法）也判为过期，不放行。"""
        try:
            when = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when <= datetime.now(timezone.utc)

    def _record(self, body, *, task_status, target_gid=None, evaluate_status=None):
        """只登记成功的任务；被拒的任务不进入 Hub 状态。"""
        self.tasks.append({'task_id': body['task_id'], 'kind': body.get('kind'),
                           'goal': body.get('goal'), 'selection_seq': body.get('selection_seq'),
                           'target_gid': target_gid, 'status': task_status,
                           'evaluate_status': evaluate_status,
                           'created_at': datetime.now(timezone.utc).isoformat()})
        self.hub_revision += 1

    @staticmethod
    def _live(session):
        return (session.snapshot() or {}).get('session') or {}

    def _stale_reason(self, live):
        if self.selection is None:
            return None
        for key, label in REVISION_FIELDS:
            published, current = self.selection.get(key), live.get(key)
            if published != current:
                return f'{label}已变化：选区 {published}，实时会话 {current}'
        return None
