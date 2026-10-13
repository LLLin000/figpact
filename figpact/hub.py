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
"""
from __future__ import annotations

import copy
import hashlib
import hmac
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
