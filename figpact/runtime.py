"""持久 JSON-lines 工作进程：一个子进程，一次导入，串行承载会话方法。

协议（stdout 上一行一帧 JSON，绝不夹带绘图脚本的 print）：
    请求  {"id": 1, "method": "try_layout", "kwargs": {...}}
    应答  {"id": 1, "ok": true,  "result": {...}}
          {"id": 1, "ok": false, "error": {"type": "...", "message": "..."}}

工作进程把 `sys.stdout` 接到 stderr，协议帧只写开工时抓住的原始 stdout 管道；
因此用户脚本/库怎么打印都污染不了协议。父进程侧按请求超时；
超时、进程死亡、协议行不是 JSON —— 一律显式报错，**绝不静默成功**。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from figpact.session import (
    ContractError, FigureSession, SessionError, StaleRevision, module_revision,
)

DEFAULT_TIMEOUT = 180.0
_STDERR_TAIL = 40
#: 不需要工作进程里存在会话的请求。
_NO_SESSION_METHODS = ('open', 'close', 'ping')


class FigureWorkerError(RuntimeError):
    """工作进程不可用 / 协议失败 / 远端异常。"""


class WorkerTimeout(FigureWorkerError):
    """请求超时。进程会被杀掉，下次请求自动重启（冷导入重来一遍，如实计数）。"""


_ERROR_TYPES = {
    'StaleRevision': StaleRevision,
    'SessionError': SessionError,
    'ContractError': ContractError,
}


class FigureWorker:
    """把 `FigureSession` 的五个非提交方法放到一个持久子进程里跑。"""

    def __init__(self, script, config, scope, *, contract=None, python=None,
                 timeout=DEFAULT_TIMEOUT, cwd=None):
        self.script = str(Path(script).resolve())
        self.config = str(Path(config).resolve())
        self.scope = scope
        self._contract_override = contract
        self.python = python or sys.executable
        self.timeout = float(timeout)
        self.cwd = str(Path(cwd) if cwd else Path(__file__).resolve().parent.parent)
        self.restarts = 0
        self._spawned_once = False
        self._source_fp = None
        self._science_inputs: list = []
        self._artifact_outputs: list = []
        self._proc = None
        self._stdin_lock = threading.Lock()
        self._cv = threading.Condition()
        self._results: dict[int, dict] = {}
        self._next_id = 0
        self._fatal: str | None = None
        self._stderr_tail: deque = deque(maxlen=_STDERR_TAIL)
        self._threads: list[threading.Thread] = []
        self._opened = False
        self._session_wanted = False
        self._closed = False

    # -- 进程 -------------------------------------------------------------- #

    def _spawn(self):
        if self._closed:
            raise FigureWorkerError('工作进程已关闭')
        env = dict(os.environ)
        env.setdefault('MPLBACKEND', 'Agg')
        self._proc = subprocess.Popen(
            [self.python, '-X', 'utf8', '-u', '-m', 'figpact.runtime'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf8', cwd=self.cwd, env=env, bufsize=1)
        self._fatal = None
        self._results.clear()
        t_out = threading.Thread(target=self._read_stdout, args=(self._proc,), daemon=True)
        t_err = threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True)
        t_out.start()
        t_err.start()
        self._threads = [t_out, t_err]

    def _ensure(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._spawned_once:
            self.restarts += 1
        self._spawned_once = True
        self._spawn()
        self._opened = False

    def _read_stdout(self, proc):
        stream = proc.stdout
        try:
            for line in stream:
                text = line.strip()
                if not text:
                    continue
                try:
                    frame = json.loads(text)
                except ValueError:
                    with self._cv:
                        self._fatal = f'工作进程 stdout 出现非 JSON 行：{text[:200]!r}'
                        self._cv.notify_all()
                    return
                if not isinstance(frame, dict) or 'id' not in frame:
                    with self._cv:
                        self._fatal = f'工作进程应答缺少 id：{text[:200]!r}'
                        self._cv.notify_all()
                    return
                with self._cv:
                    self._results[int(frame['id'])] = frame
                    self._cv.notify_all()
        except Exception as error:  # 管道读失败
            with self._cv:
                self._fatal = f'读取工作进程输出失败：{error}'
                self._cv.notify_all()
        finally:
            with self._cv:
                if self._fatal is None:
                    self._fatal = f'工作进程已退出（returncode={proc.poll()}）'
                self._cv.notify_all()

    def _read_stderr(self, proc):
        try:
            for line in proc.stderr:
                self._stderr_tail.append(line.rstrip('\n'))
        except Exception:
            pass

    def stderr_tail(self, limit: int = 10) -> list[str]:
        return list(self._stderr_tail)[-limit:]

    def _kill(self):
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass
        self._proc = None
        self._opened = False
        with self._cv:
            self._fatal = None
            self._results.clear()

    def close(self):
        if self._closed:
            return
        if self._proc is not None:
            try:
                self._send(self._next_id, 'close', {}, wait=False)
            except Exception:
                pass
            self._kill()
        self._closed = True
        self._session_wanted = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- 请求 -------------------------------------------------------------- #

    def _send(self, rid, method, kwargs, *, wait=True):
        proc = self._proc
        assert proc is not None
        payload = json.dumps({'id': rid, 'method': method, 'kwargs': kwargs}, ensure_ascii=False)
        try:
            proc.stdin.write(payload + '\n')
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise FigureWorkerError(
                f'无法向工作进程发送 {method}：{error}；stderr 尾部：{self.stderr_tail(5)}') from error
        if not wait:
            return None
        deadline = time.monotonic() + self.timeout
        with self._cv:
            while rid not in self._results and self._fatal is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(min(remaining, 0.5))
            frame = self._results.pop(rid, None)
            fatal = self._fatal
        if frame is None:
            self._kill()
            tail = ' | '.join(self.stderr_tail(5))
            if fatal is not None:
                raise FigureWorkerError(f'工作进程不可用：{fatal}；stderr 尾部：{tail}')
            raise WorkerTimeout(f'{method} 在 {self.timeout}s 内没有应答；进程已终止。'
                                f'stderr 尾部：{tail}')
        if not frame.get('ok'):
            error = frame.get('error') or {}
            kind = error.get('type') or 'Error'
            message = error.get('message') or '远端未给出信息'
            cls = _ERROR_TYPES.get(kind, FigureWorkerError)
            raise cls(f'{kind}: {message}')
        return frame.get('result')

    def _fingerprint(self):
        """**模块/引擎**指纹：不含配置字节。

        YAML（配置）变更只让工作者里的会话重基线，不该换进程、更不该冷导入；
        脚本/助手/科学输入/引擎实现改了才换进程。
        """
        return module_revision(self.script, self.config,
                               exclude=self._artifact_outputs, required=self._science_inputs)

    def _refresh_if_source_changed(self):
        """脚本/助手/引擎实现改了 → 换进程（旧模块对象没法安全热替换）。

        换进程返回 True：新进程里还没有会话，调用方必须重新 open，绝不把「没开过会话」
        当成「会话还在」。
        """
        fingerprint = self._fingerprint()
        if self._source_fp is None:
            self._source_fp = fingerprint
            return False
        if fingerprint != self._source_fp:
            self._source_fp = fingerprint
            if self._proc is not None:
                self._kill()
                return True
        return False

    def request(self, method, **kwargs):
        with self._stdin_lock:
            self._refresh_if_source_changed()
            self._ensure()
            if self._session_wanted and not self._opened \
                    and method not in _NO_SESSION_METHODS:
                # 进程刚换过 / 会话随进程一起没了：本次请求前按原参数重建会话。
                self._open_locked()
            self._next_id += 1
            rid = self._next_id
            return self._send(rid, method, kwargs)

    # -- 会话方法 ---------------------------------------------------------- #

    def _open_locked(self, **kwargs):
        """（调用方已持锁）在工作进程里建会话，并记下真实的装载事实。"""
        params = {'script': self.script, 'config': self.config, 'scope': self.scope}
        if self._contract_override is not None:
            params['contract'] = self._contract_override
        params.update(kwargs)
        self._ensure()
        self._next_id += 1
        result = self._send(self._next_id, 'open', params)
        self._opened = True
        self._session_wanted = True
        if isinstance(result, dict):
            self._science_inputs = list(result.get('science_inputs') or [])
            self._artifact_outputs = list(result.get('artifact_outputs') or [])
        self._source_fp = self._fingerprint()
        return result

    def open(self, **kwargs):
        """早开一步：工作者里建好会话（一次导入 + 一次 science 装载）。"""
        with self._stdin_lock:
            self._refresh_if_source_changed()
            return self._open_locked(**kwargs)

    def _session_request(self, method, **kwargs):
        if not self._session_wanted:
            self.open()
        return self.request(method, **kwargs)

    def ping(self):
        return self.request('ping')

    def snapshot(self, **kwargs):
        return self._session_request('snapshot', **kwargs)

    def inspect(self, **kwargs):
        return self._session_request('inspect', **kwargs)

    def try_layout(self, operations, *, revision=None):
        return self._session_request('try_layout', operations=list(operations),
                                     revision=revision)

    def render_preview(self, *, revision=None):
        return self._session_request('render_preview', revision=revision)

    def capture_frame(self, *, revision=None):
        """Worker 权威的同源帧：子进程里实际候选 Figure 的 same-capture PNG+Scene。"""
        return self._session_request('capture_frame', revision=revision)

    def export_frame(self, output_dir, *, revision, frame_revision):
        """导出精确请求的那一帧；revision/frame_revision 过期一律拒绝。"""
        return self._session_request('export_frame', output_dir=str(output_dir),
                                     revision=revision, frame_revision=frame_revision)


    def check_effects(self):
        return self._session_request('check_effects')

    # -- 候选状态（每次读都是一次 IPC；会话关闭/进程死亡一律抛错，不回陈旧值） -- #

    def state(self) -> dict:
        if self._closed:
            raise FigureWorkerError('工作进程已关闭，候选状态不可读')
        return self._session_request('state')

    def _state_field(self, name):
        return self.state()[name]

    @property
    def revision(self) -> str:
        return self._state_field('revision')

    @property
    def base_config_revision(self) -> str:
        return self._state_field('base_config_revision')

    @property
    def candidate_patch(self) -> dict:
        return self._state_field('candidate_patch')

    @property
    def candidate_config(self) -> dict:
        return self._state_field('candidate_config')

    @property
    def has_candidate(self) -> bool:
        return bool(self._state_field('has_candidate'))

    @property
    def contract(self) -> dict:
        return self._state_field('contract')

    @property
    def science_manifest(self):
        return self._state_field('science_manifest')

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self):
        """子进程 pid（父进程视角）；进程不在时 None。"""
        return self._proc.pid if self.alive else None


# --------------------------------------------------------------------------- #
# 工作进程主体
# --------------------------------------------------------------------------- #

def _dispatch(method, kwargs, state):
    if method == 'ping':
        return {'pong': True, 'pid': os.getpid()}
    if method == 'open':
        session = state.get('session')
        if session is not None:
            session.close()
        script = kwargs.get('script') or state.get('script')
        config = kwargs.get('config') or state.get('config')
        scope = kwargs.get('scope') if 'scope' in kwargs else state.get('scope')
        contract = kwargs.get('contract', state.get('contract'))
        if not script or not config or not scope:
            raise SessionError('open 需要 script/config/scope')
        state.update({'script': script, 'config': config, 'scope': scope, 'contract': contract})
        session = FigureSession(script, config, scope, contract=contract)
        state['session'] = session
        return {'scope': scope, 'revision': session.revision,
                'base_config_revision': session.base_config_revision,
                'source_revision': session._source_rev,
                'science_inputs': list(session._science_inputs),
                'artifact_outputs': list(session._outputs),
                'pid': os.getpid()}
    if method == 'close':
        session = state.get('session')
        if session is not None:
            session.close()
            state['session'] = None
        return {'closed': True}
    session = state.get('session')
    if session is None:
        if not state.get('script'):
            raise SessionError(f'{method} 之前必须先 open')
        _dispatch('open', {}, state)
        session = state['session']
    if method == 'snapshot':
        return session.snapshot(**kwargs)
    if method == 'inspect':
        return session.inspect(**kwargs)
    if method == 'try_layout':
        return session.try_layout(kwargs.get('operations') or [], revision=kwargs.get('revision'))
    if method == 'render_preview':
        return session.render_preview(revision=kwargs.get('revision'))
    if method == 'capture_frame':
        return session.capture_frame(revision=kwargs.get('revision'))
    if method == 'export_frame':
        return session.export_frame(kwargs.get('output_dir'), revision=kwargs.get('revision'),
                                    frame_revision=kwargs.get('frame_revision'))
    if method == 'check_effects':
        return session.check_effects()
    if method == 'revision':
        return {'revision': session.revision, 'base_config_revision': session.base_config_revision}
    if method == 'state':
        payload = dict(session.state())
        payload['worker_pid'] = os.getpid()
        return payload
    raise SessionError(f'未知方法：{method}')


def main(argv=None):
    """JSON-lines 服务循环。协议帧走原始 stdout，其它打印一律去 stderr。"""
    out = sys.__stdout__
    err = sys.__stderr__ or sys.stderr
    sys.stdout = err  # 用户代码/库的 print 不可能再污染协议通道
    state: dict = {}

    def write(frame):
        out.write(json.dumps(frame, ensure_ascii=False) + '\n')
        out.flush()

    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            request = json.loads(text)
            rid = request.get('id')
            method = request.get('method')
            kwargs = request.get('kwargs') or {}
        except ValueError as error:
            write({'id': None, 'ok': False,
                   'error': {'type': 'ProtocolError', 'message': f'请求不是合法 JSON：{error}'}})
            continue
        try:
            result = _dispatch(method, kwargs, state)
            write({'id': rid, 'ok': True, 'result': result})
        except Exception as error:
            write({'id': rid, 'ok': False,
                   'error': {'type': type(error).__name__, 'message': str(error)}})
    session = state.get('session')
    if session is not None:
        session.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
