"""G5a 会话 Hub：只读选区、接收几何任务、调用既有试算。

只做协调层：读选区、收几何任务、调既有 ``IntentSession.evaluate``；
**不授予源码写入或发布权限**，不另建 Figure、不另算科学、不另做 QA。
状态只在内存、会话级、不落盘；服务器是单线程 ``HTTPServer``，写入天然串行。

公开方法返回 ``(payload, http_status)`` 以便 HTTP 路由直接回包，但本模块
不依赖 HTTP，也不依赖 matplotlib。
"""
from __future__ import annotations

import copy
import uuid
from collections import deque
from datetime import datetime, timezone

FORBIDDEN_KINDS = ('source_write', 'publish', 'delete', 'git')
FORBIDDEN_MESSAGE = 'G5a Hub 只允许读取选区、提交几何任务并调用既有试算；不授予源码写入或发布权限'
MAX_TASKS = 50
# GET /api/selection 的 stale 判定字段：发布值必须与实时会话一致。
REVISION_FIELDS = (('session_id', '会话'), ('scene_revision', '图帧'), ('source_revision', '源文件'))


def _error(status, message):
    return {'status': status, 'message': message}


class SessionHub:
    """内存态 Hub；不落盘、不写 history、不改用户文件。"""

    def __init__(self):
        self.selection = None
        self.selection_seq = None
        self.hub_revision = 0
        self.tasks = deque(maxlen=MAX_TASKS)

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

    # 内部

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
