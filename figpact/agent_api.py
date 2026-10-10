"""Local persistent JSON-RPC surface for five agent operations.

Transport: one JSON object per line on stdin/stdout; the process stays alive and
holds exactly one `FigureWorker` per (script, config, scope). Nothing here
reimplements the runtime or the geometry: session/preview results come straight from
`figpact.runtime`, node records from `figpact.scene`. This module owns only two
things it must own itself -- the JSON-RPC lifecycle, and the commit gate.

Commit has two distinct kinds and they are not the same trust level:

* ``draft`` writes the candidate back to the YAML through the comment-preserving
  T4 gate (`figpact.patch.apply_patch_text` + `commit_changes`, SHA-compared).
  It returns ``DRAFT_SAVED``, never a verification.
* ``publication`` re-runs the *whole* declared figure, for *every* scope, in a
  throwaway sandbox (`--strict --probe`), demands every declared artifact, compares
  protected science against the on-disk baseline, and only then installs artifacts
  and the config together. ``STRICT_VERIFIED`` is granted only by that path: never
  from a cached preview, never with a missing artifact, never with a changed
  protected array/pixel/window/assignment/scale meaning.

Replies stay compact by default: long geometry sample runs (polyline samples, pixel
arrays) are replaced by explicit `elided` markers, while IDs, tree, bounds, anchors,
relations, exact controls, QA and measurement all stay. `detail: "full"` returns the
worker payload untouched.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

from figpact import contracts, science as science_mod

OPERATIONS = ('snapshot', 'inspect', 'try_layout', 'render_preview', 'commit', 'status', 'close')
COMMIT_KINDS = ('draft', 'publication')
STRICT_TIMEOUT_S = 900

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SESSION_UNAVAILABLE = -32001
SESSION_CLOSED = -32002
STALE_REVISION = -32003
NO_CANDIDATE = -32004
COMMIT_REJECTED = -32005
WORKER_ERROR = -32006


class AgentError(Exception):
    """A request-level failure that must reach the client as a JSON-RPC error."""

    def __init__(self, code, message, *, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def to_error(self):
        error = {'code': self.code, 'message': self.message}
        if self.data:
            error['data'] = self.data
        return error


def _runtime():
    from figpact import runtime
    return runtime


def _worker_error(error):
    """Runtime failures arrive as JSON-RPC errors; stale/conflict is its own code."""
    if type(error).__name__ in ('StaleRevision', 'RevisionConflict'):
        return AgentError(STALE_REVISION, str(error))
    return AgentError(WORKER_ERROR, str(error))


def source_fingerprint(script, config, *, exclude=(), extra=()):
    """Content of every source and input a candidate depends on.

    Content, not mtime: a touched-but-unchanged file is not a change, an edited data
    file is. Nothing is skipped by extension -- a `.png`/`.pdf`/`.json` next to the
    script can be a scientific input (instrument original, processing metadata) --
    only the exact declared output filenames and bytecode are left out, so publishing
    does not look like a source change while a swapped input still does.

    `extra` are the files the figure *declares* it read. They can live outside the
    script directory (an instrument dump elsewhere on disk), so walking the directory
    is not enough; a declared input that disappeared is a change too, not a no-op.
    """
    script, config = Path(script).resolve(), Path(config).resolve()
    excluded = {str(name) for name in exclude}
    digest = hashlib.sha256(config.read_bytes() if config.is_file() else b'')
    for path in sorted(script.parent.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.name in excluded or path.name.startswith('.figpact-'):
            continue
        digest.update(f'{path.name}:'.encode('utf8'))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    for declared in sorted({str(Path(item).expanduser().resolve()) for item in extra}):
        path = Path(declared)
        if path.name in excluded or path.name.startswith('.figpact-'):
            continue
        digest.update(f'{path}:'.encode('utf8'))
        digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b'MISSING')
    return digest.hexdigest()


def _flatten(paths, prefix=()):
    flat = []
    for key, value in paths.items():
        if isinstance(value, dict) and value:
            flat.extend(_flatten(value, (*prefix, key)))
        else:
            flat.append(list((*prefix, key)))
    return flat


class AgentSession:
    """One figure scope, one persistent worker, one commit gate."""

    def __init__(self, script, config, scope, *, output_dir=None):
        self.script = Path(script).expanduser().resolve()
        self.config = Path(config).expanduser().resolve()
        self.scope = scope
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else self.script.parent
        if not self.script.is_file():
            raise AgentError(SESSION_UNAVAILABLE, f'绘图脚本不存在：{self.script}')
        if not self.config.is_file():
            raise AgentError(SESSION_UNAVAILABLE, f'配置文件不存在：{self.config}')
        try:
            worker_factory = _runtime().FigureWorker
        except Exception as error:  # pragma: no cover - integration failure surface
            raise AgentError(SESSION_UNAVAILABLE, f'运行时不可用：{error}') from error
        self._closed = False
        self._worker = worker_factory(self.script, self.config, self.scope)
        self._baseline_fingerprint = None

    def _baseline_inputs(self):
        """Fingerprint captured when the candidate is created, not at session start.

        Declared outputs are excluded by exact filename, so re-publishing cannot look
        like a source change, while a swapped input with an output-like extension still
        does. Declared science inputs are included even when they live outside the script
        directory. Both the baseline and the commit-time check use this same set.
        """
        if self._baseline_fingerprint is None:
            state = self._call(self._worker.state) or {}
            self._baseline_fingerprint = source_fingerprint(
                self.script, self.config,
                exclude=(state.get('contract') or {}).get('outputs') or (),
                extra=state.get('science_inputs') or ())
        return self._baseline_fingerprint

    # ---------------------------------------------------------------- operations

    def snapshot(self):
        return self._call(self._worker.snapshot)

    def inspect(self, *, ids=None, name=None, type=None, scope=None):
        filters = {k: v for k, v in (('ids', ids), ('name', name), ('type', type), ('scope', scope)) if v is not None}
        return self._call(self._worker.inspect, **filters)

    def try_layout(self, operations, *, revision=None):
        if not isinstance(operations, list) or not operations:
            raise AgentError(INVALID_PARAMS, 'try_layout 需要非空的 operations 记录列表')
        if revision is not None:
            self._require_revision(revision)
        self._baseline_inputs()
        result = self._call(self._worker.try_layout, operations, revision=revision)
        if isinstance(result, dict) and result.get('status') == 'STALE_REVISION':
            raise AgentError(STALE_REVISION, '候选已过期，请重新 snapshot 后重试', data=result)
        return result

    def render_preview(self, *, revision=None):
        if revision is not None:
            self._require_revision(revision)
        result = self._call(self._worker.render_preview, revision=revision) if revision is not None \
            else self._call(self._worker.render_preview)
        return result

    def status(self):
        info = {'scope': self.scope, 'script': str(self.script), 'config': str(self.config),
                'output_dir': str(self.output_dir), 'closed': self._closed,
                'worker': {'alive': None}, 'operations': list(OPERATIONS)}
        if self._closed:
            return info
        info['worker'] = {'alive': bool(self._worker.alive), 'pid': self._worker.pid,
                          'restarts': self._worker.restarts}
        try:
            state = self._worker.state()
        except Exception as error:
            info['error'] = str(error)
            return info
        info.update(revision=state.get('revision'), has_candidate=bool(state.get('has_candidate')),
                    base_config_revision=state.get('base_config_revision'))
        info['candidate_paths'] = [list(p) for p in _flatten(state.get('candidate_patch') or {})]
        contract = state.get('contract') or {}
        info['contract'] = {'source': contract.get('source'),
                            'parameters': len(contract.get('parameters', [])),
                            'relations': len(contract.get('relations', [])),
                            'outputs': list(contract.get('outputs', [])),
                            'validation_error': contract.get('validation_error')}
        return info

    def close(self):
        if self._closed:
            return {'status': 'closed', 'already_closed': True}
        self._closed = True
        try:
            self._worker.close()
        except Exception as error:
            return {'status': 'closed', 'error': str(error)}
        return {'status': 'closed', 'already_closed': False}

    # --------------------------------------------------------------------- commit

    def commit(self, kind, *, revision=None, output_dir=None, confirm=False):
        """Draft save (T4 gate) or publication (independent strict gate)."""
        if kind not in COMMIT_KINDS:
            raise AgentError(INVALID_PARAMS, f'未知的 commit kind：{kind!r}，只支持 {list(COMMIT_KINDS)}')
        if kind == 'publication' and not confirm:
            raise AgentError(INVALID_PARAMS,
                             'publication 会写入正式产物与配置；请带 confirm=true 明确确认',
                             data={'install_target': str(Path(output_dir).expanduser().resolve()) if output_dir
                                   else str(self.output_dir)})
        contract = self._checked_contract()
        self._require_fresh_candidate(revision)
        candidate_patch = self._candidate_patch()
        self._require_candidate_patch(candidate_patch)
        text = self._candidate_text(candidate_patch, contract)
        if kind == 'draft':
            return self._commit_draft(text, candidate_patch)
        return self._commit_publication(text, candidate_patch, contract,
                                        output_dir=Path(output_dir).expanduser().resolve() if output_dir else self.output_dir)

    def _commit_draft(self, text, candidate_patch):
        self._require_unchanged_on_disk()
        try:
            record = _patch().commit_changes(self.config, self._worker.base_config_revision,
                                             {self.config: text.encode('utf-8')})
        except AgentError:
            raise
        except Exception as error:
            raise AgentError(COMMIT_REJECTED, f'草稿保存被拒绝：{error}') from error
        return {'status': 'committed', 'kind': 'draft', 'verification': 'DRAFT_SAVED',
                'config': str(self.config), 'revision': self._worker.revision,
                'changed_paths': [list(p) for p in _flatten(candidate_patch)],
                'files': {str(self.config): record['after'].get(self.config)},
                'notes': ['草稿保存未经过独立严格校验；发布请用 commit kind=publication']}

    def _commit_publication(self, text, candidate_patch, contract, *, output_dir):
        self._require_unchanged_on_disk()
        sandbox = Path(tempfile.mkdtemp(prefix='figpact-agent-strict-'))
        try:
            candidate_yaml = sandbox / 'candidate.yaml'
            candidate_yaml.write_text(text, encoding='utf-8')
            qa_lines, code = self._run_strict(candidate_yaml, sandbox)
            plan = self._plan(candidate_yaml)
            expected = []
            for scope in plan['scopes']:
                for name in plan['outputs'].get(scope, []):
                    if name not in expected:
                        expected.append(name)
            if not expected:
                raise AgentError(COMMIT_REJECTED, '脚本未声明任何发布产物，拒绝发布',
                                 data={'scopes': plan['scopes']})
            missing = [name for name in expected
                       if not (sandbox / name).is_file() or not (sandbox / name).stat().st_size]
            if code != 0:
                raise AgentError(COMMIT_REJECTED, '严格校验未通过，正式产物与配置未改动',
                                 data={'returncode': code, 'qa': qa_lines, 'missing_artifacts': missing})
            if missing:
                raise AgentError(COMMIT_REJECTED, f'严格校验未产出全部声明产物：{missing}',
                                 data={'expected': expected, 'missing': missing, 'returncode': code,
                                       'qa': qa_lines})
            diagnostics = self._science_diagnostics(candidate_yaml, plan['scopes'])
            if diagnostics:
                raise AgentError(COMMIT_REJECTED, '受保护科学内容与基线不一致，正式产物未改动',
                                 data={'diagnostics': diagnostics})
            installed, before = _install_transactional({name: sandbox / name for name in expected}, output_dir)
            try:
                record = _patch().commit_changes(self.config, self._worker.base_config_revision,
                                                 {self.config: text.encode('utf-8')})
            except Exception as error:
                _restore(output_dir, before)
                if isinstance(error, AgentError):
                    raise
                raise AgentError(COMMIT_REJECTED, f'发布期间保存配置被拒绝，产物已回滚：{error}') from error
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        return {'status': 'committed', 'kind': 'publication', 'verification': 'STRICT_VERIFIED',
                'config': str(self.config), 'output_dir': str(output_dir),
                'revision': self._worker.revision, 'scopes': plan['scopes'],
                'artifacts': installed, 'config_fingerprint': record['after'].get(self.config),
                'changed_paths': [list(p) for p in _flatten(candidate_patch)],
                'science': 'protected payload identical to baseline',
                'qa': qa_lines}

    # ------------------------------------------------------------------- helpers

    def _call(self, func, *args, **kwargs):
        if self._closed:
            raise AgentError(SESSION_CLOSED, '会话已关闭，请重新启动 agent 会话')
        try:
            return func(*args, **kwargs)
        except AgentError:
            raise
        except Exception as error:
            raise _worker_error(error) from error

    def _require_revision(self, revision):
        current = self._call(lambda: self._worker.revision)
        if revision != current:
            raise AgentError(STALE_REVISION, '请求的 revision 与当前候选不一致',
                             data={'requested': revision, 'current': current})

    def _candidate_patch(self):
        return self._call(lambda: self._worker.candidate_patch or {})

    def _checked_contract(self):
        contract = self._call(lambda: self._worker.contract) or {}
        if contract.get('validation_error'):
            raise AgentError(INVALID_PARAMS, f'作者契约未通过校验，拒绝提交：{contract["validation_error"]}')
        try:
            return contracts.validate_contract(contract, scope=self.scope)
        except ValueError as error:
            raise AgentError(INVALID_PARAMS, f'作者契约未通过校验，拒绝提交：{error}') from error

    def _require_candidate_patch(self, candidate_patch):
        if not candidate_patch:
            raise AgentError(NO_CANDIDATE, '本次会话没有成功过的 try_layout，没有可提交的候选')

    def _require_fresh_candidate(self, revision):
        if not self._call(lambda: self._worker.has_candidate):
            raise AgentError(NO_CANDIDATE, '本次会话没有成功过的 try_layout，没有可提交的候选')
        if revision is not None:
            self._require_revision(revision)

    def _require_unchanged_on_disk(self):
        if not self.config.is_file():
            raise AgentError(STALE_REVISION, '配置文件已不存在，候选无法提交')
        current = _patch().config_revision(self.config)
        if current != self._call(lambda: self._worker.base_config_revision):
            raise AgentError(STALE_REVISION, '配置文件在候选生成后已被修改，拒绝覆盖磁盘改动',
                             data={'disk_revision': current})
        state = self._call(self._worker.state) or {}
        if source_fingerprint(self.script, self.config,
                              exclude=(state.get('contract') or {}).get('outputs') or (),
                              extra=state.get('science_inputs') or ()) != self._baseline_inputs():
            raise AgentError(STALE_REVISION, '脚本或输入文件在候选生成后发生变化，候选已失效')

    def _candidate_text(self, candidate_patch, contract):
        catalog = contracts.parameter_catalog(contract)
        try:
            return _patch().apply_patch_text(self.config.read_text(encoding='utf-8'), candidate_patch, catalog)
        except Exception as error:
            raise AgentError(COMMIT_REJECTED, f'候选无法写回配置：{error}') from error

    def _run_strict(self, candidate_yaml, sandbox):
        cmd = [sys.executable, '-X', 'utf8', str(self.script), '--config', str(candidate_yaml),
               '--strict', '--probe', str(sandbox)]
        # `--probe` only for scripts that declare it; FIGPACT_PROBE_DIR redirects the rest.
        text = self.script.read_text(encoding='utf-8', errors='replace')
        if '"--probe"' not in text and "'--probe'" not in text:
            cmd.remove('--probe')
            cmd.remove(str(sandbox))
        env = {**os.environ, 'FIGPACT_PROBE_DIR': str(sandbox)}
        try:
            res = subprocess.run(cmd, cwd=str(self.script.parent), capture_output=True, text=True,
                                 encoding='utf-8', env=env, timeout=STRICT_TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            raise AgentError(COMMIT_REJECTED, f'严格校验超时（{STRICT_TIMEOUT_S}s）') from error
        lines = [line.strip() for line in (res.stdout + '\n' + res.stderr).splitlines()
                 if line.strip().startswith('[QA]') or '[QA]' in line]
        return lines[:80], res.returncode

    def _worker_payload(self, command, **payload):
        request = {'command': command, 'script': str(self.script), **payload}
        root = Path(__file__).resolve().parent.parent
        try:
            res = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'figpact.agent_api', '--worker'],
                                 input=json.dumps(request), text=True, encoding='utf-8',
                                 capture_output=True, cwd=str(root), timeout=STRICT_TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            raise AgentError(COMMIT_REJECTED, f'独立校验工作进程超时：{command}') from error
        if res.returncode != 0:
            detail = (res.stderr or res.stdout).strip()
            try:
                message = str(json.loads(detail).get('error') or detail)
            except ValueError:
                message = detail
            raise AgentError(COMMIT_REJECTED, f'独立校验工作进程拒绝发布：{message}',
                             data={'command': command})
        try:
            return json.loads(res.stdout)
        except ValueError as error:
            raise AgentError(INTERNAL_ERROR, f'独立校验工作进程返回非法 JSON：{res.stdout[:200]!r}') from error

    def _plan(self, candidate_yaml):
        return self._worker_payload('plan', config=str(candidate_yaml))

    def _science_diagnostics(self, candidate_yaml, scopes):
        baseline = self._worker_payload('science', config=str(self.config), scopes=scopes)['scopes']
        candidate = self._worker_payload('science', config=str(candidate_yaml), scopes=scopes)['scopes']
        diagnostics = []
        for scope in scopes:
            for item in science_mod.compare_science(baseline.get(scope), candidate.get(scope),
                                                    label=f'（scope {scope}）'):
                diagnostics.append({**item, 'scope': scope})
        return diagnostics


def _patch():
    from figpact import patch
    return patch


def _install_transactional(sources, target_dir):
    """Copy every artifact into place, or put every artifact back."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    before, staged, applied = {}, {}, []
    try:
        for name, src in sources.items():
            dst = target_dir / name
            before[name] = dst.read_bytes() if dst.is_file() else None
            tmp = target_dir / f'.figpact-stage-{os.getpid()}-{name}'
            shutil.copyfile(src, tmp)
            staged[name] = tmp
        for name in sources:
            os.replace(staged[name], target_dir / name)
            applied.append(name)
    except BaseException:
        for name in reversed(applied):
            _restore_one(target_dir / name, before[name])
        raise
    finally:
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)
    return sorted(applied), before


def _restore_one(dst, content):
    if content is None:
        dst.unlink(missing_ok=True)
        return
    tmp = dst.parent / f'.figpact-restore-{os.getpid()}-{dst.name}'
    tmp.write_bytes(content)
    os.replace(tmp, dst)


def _restore(target_dir, before):
    for name, content in before.items():
        _restore_one(Path(target_dir) / name, content)


# ------------------------------------------------------------------ RPC surface

#: Default JSON stays compact: full scene geometry (polyline samples, pixel arrays)
#: is not dumped into every reply. It remains in the worker, and a client that
#: explicitly asks for it gets it unchanged.
SUMMARY_MAX_ITEMS = 64
SAMPLE_KEYS = {'polyline_mm', 'polyline', 'samples', 'verts', 'pixels', 'array'}
ELIDED_HINT = "resend with detail='full'"


def _numeric_samples(value):
    """A long run of numbers (or numeric pairs) is geometry samples, not a catalog."""
    if not isinstance(value, (list, tuple)) or len(value) <= SUMMARY_MAX_ITEMS:
        return False
    for item in value[:8]:
        if isinstance(item, bool):
            return False
        if isinstance(item, (int, float)):
            continue
        if isinstance(item, (list, tuple)) and item and not isinstance(item[0], bool) \
                and all(isinstance(n, (int, float)) for n in item):
            continue
        return False
    return True


def _elided(value):
    marker = {'elided': True, 'hint': ELIDED_HINT}
    if isinstance(value, (list, tuple)):
        marker['length'] = len(value)
        marker['kind'] = 'numeric_samples' if _numeric_samples(value) else 'list'
    elif isinstance(value, dict):
        marker['keys'] = sorted(value)[:8]
    return marker


def _compact(value, key=None):
    if isinstance(value, dict):
        return {name: _compact(item, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        if key in SAMPLE_KEYS or _numeric_samples(value):
            return _elided(value)
        return [_compact(item) for item in value]
    return value


def compact_result(result, detail):
    """`detail='full'` returns the worker payload untouched; anything else is elided."""
    if detail == 'full' or not isinstance(result, dict):
        return result
    compacted = _compact(result)
    compacted.setdefault('detail', 'summary')
    return compacted

def dispatch(session, method, params):
    if not isinstance(params, dict):
        raise AgentError(INVALID_PARAMS, 'params 必须是对象')
    if method not in OPERATIONS:
        raise AgentError(METHOD_NOT_FOUND, f'未知方法：{method}')
    detail = params.get('detail', 'summary')
    if detail not in ('summary', 'full'):
        raise AgentError(INVALID_PARAMS, "detail 只能是 'summary' 或 'full'")
    if method == 'snapshot':
        return compact_result(session.snapshot(), detail)
    if method == 'inspect':
        filters = {k: v for k, v in params.items() if k != 'detail'}
        return compact_result(session.inspect(**filters), detail)
    if method == 'try_layout':
        return compact_result(session.try_layout(params.get('operations'), revision=params.get('revision')), detail)
    if method == 'render_preview':
        return compact_result(session.render_preview(revision=params.get('revision')), detail)
    if method == 'commit':
        return session.commit(params.get('kind'), revision=params.get('revision'),
                              output_dir=params.get('output_dir'), confirm=bool(params.get('confirm')))
    if method == 'status':
        return session.status()
    return session.close()


def _response(request_id, payload):
    return {'jsonrpc': '2.0', 'id': request_id, **payload}


def _handle(session, payload):
    if not isinstance(payload, dict):
        return _response(None, {'error': {'code': INVALID_REQUEST, 'message': '请求必须是 JSON 对象'}})
    request_id = payload.get('id')
    method = payload.get('method')
    if not isinstance(method, str) or not method:
        return _response(request_id, {'error': {'code': INVALID_REQUEST, 'message': 'method 必须是非空字符串'}})
    try:
        result = dispatch(session, method, payload.get('params') if payload.get('params') is not None else {})
        return _response(request_id, {'result': result})
    except AgentError as error:
        return _response(request_id, {'error': error.to_error()})
    except Exception as error:  # never leak a traceback into the protocol
        return _response(request_id, {'error': {'code': INTERNAL_ERROR, 'message': f'{type(error).__name__}: {error}'}})


def serve(script, config, scope, *, output_dir=None, stdin=None, stdout=None):
    """Run the persistent session loop until EOF. stdout carries protocol only."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        session = AgentSession(script, config, scope, output_dir=output_dir)
    except AgentError as error:
        session = None
        startup_error = error.to_error()
    else:
        startup_error = None
    try:
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                _emit(stdout, _response(None, {'error': {'code': PARSE_ERROR, 'message': 'parse error'}}))
                continue
            requests = payload if isinstance(payload, list) else [payload]
            replies = []
            for request in requests:
                if session is None:
                    if isinstance(request, dict) and 'id' in request:
                        replies.append(_response(request.get('id'), {'error': startup_error}))
                    continue
                reply = _handle(session, request)
                if not isinstance(request, dict) or 'id' in request:
                    replies.append(reply)
            if replies:
                _emit(stdout, replies if isinstance(payload, list) else replies[0])
    finally:
        if session is not None:
            session.close()
    return 0


def _emit(stdout, message):
    stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
    stdout.flush()


# --------------------------------------------------------------- worker entry

def _load_script(script, config):
    import matplotlib
    matplotlib.use('Agg')
    script, config = Path(script).resolve(), Path(config).resolve()
    sys.path.insert(0, str(script.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.modules.pop('figure_style', None)
    spec = importlib.util.spec_from_file_location('figpact_agent_plot', script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    argv = sys.argv
    sys.argv = [str(script), '--config', str(config), '--inventory']
    try:
        with redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    finally:
        sys.argv = argv
    return module


def _scopes(module, requested):
    scopes = [str(s) for s in (getattr(module, 'SCOPES', None) or [])]
    if requested:
        unknown = [s for s in requested if s not in scopes]
        if unknown:
            raise AgentError(INVALID_PARAMS, f'脚本未声明 scope：{unknown}', data={'scopes': scopes})
        scopes = [s for s in scopes if s in set(requested)]
    if not scopes:
        raise AgentError(INVALID_PARAMS, '脚本未声明任何 SCOPES，无法独立校验')
    return scopes


def _build(module, config, scope):
    if hasattr(module, 'build_scene'):
        science = module.load_science() if hasattr(module, 'load_science') else None
        loaded = module.load_config(config) if hasattr(module, 'load_config') \
            else yaml.safe_load(Path(config).read_text(encoding='utf-8'))
        return module.build_scene(science, loaded, scope), science
    return module.build_figure_and_registry(scope), None


def _worker_plan(payload):
    module = _load_script(payload['script'], payload['config'])
    scopes = _scopes(module, payload.get('scopes'))
    outputs, problems = {}, {}
    for scope in scopes:
        contract = module.layout_contract(scope) if hasattr(module, 'layout_contract') else {}
        if not isinstance(contract, dict):
            raise AgentError(INVALID_PARAMS, f'layout_contract({scope}) 必须返回映射')
        missing = [name for name in contract.get('outputs', []) if not isinstance(name, str) or not name]
        if missing or not contract.get('outputs'):
            raise AgentError(INVALID_PARAMS, f'scope {scope} 未声明可用的 outputs 列表')
        outputs[scope] = [str(name) for name in contract['outputs']]
        problems[scope] = list(contract.get('problems', []) or [])
    return {'figure_id': getattr(module, 'FIGURE_ID', None), 'scopes': scopes,
            'outputs': outputs, 'contract_problems': problems}


def _worker_science(payload):
    import matplotlib.pyplot as plt
    module = _load_script(payload['script'], payload['config'])
    scopes = _scopes(module, payload.get('scopes'))
    manifests = {}
    for scope in scopes:
        figure = None
        try:
            with redirect_stdout(io.StringIO()):
                (figure, registry), science = _build(module, payload['config'], scope)
                declarations = module.science_manifest(science) if hasattr(module, 'science_manifest') else None
                manifests[scope] = science_mod.capture_science(figure, registry, declarations=declarations)
        finally:
            if figure is not None:
                plt.close(figure)
    return {'scopes': manifests}


def main_worker():
    """Internal entry point: one JSON request on stdin, one JSON reply on stdout."""
    payload = json.load(sys.stdin)
    command = payload.get('command')
    handlers = {'plan': _worker_plan, 'science': _worker_science}
    if command not in handlers:
        print(json.dumps({'error': f'unknown worker command: {command}'}), file=sys.stderr)
        return 2
    try:
        result = handlers[command](payload)
    except AgentError as error:
        print(json.dumps({'error': error.message, 'code': error.code}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as error:
        print(json.dumps({'error': f'{type(error).__name__}: {error}'}, ensure_ascii=False), file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main_worker())
