"""Consumer-visible behaviour of the local agent JSON-RPC surface.

Most tests here talk to a real `figpact agent` process over stdin/stdout and assert
only what a client sees: JSON-RPC results and error codes, files on disk, process
lifetime. The publication-safety regressions drive the same code the commit gate
drives -- the internal plan worker (`figpact.agent_api --worker`), and the real
install/config transaction on real files -- because what they exercise (a foreign
scope's declared artifacts, a nested install, an input that moves between validation
and installation) is not reachable through one session's own scope. No wiring,
default, source-text or wording assertions, and no mocks.
"""
import base64
import contextlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
REQUEST_TIMEOUT = 300
MISSING = -32601
INVALID_PARAMS = -32602
SESSION_CLOSED = -32002
STALE_REVISION = -32003
NO_CANDIDATE = -32004
COMMIT_REJECTED = -32005


def fixture_paths(name):
    script = FIXTURES / f'native_{name}.py'
    candidates = sorted(FIXTURES.glob(f'native_{name}*.yaml'))
    assert script.is_file(), f'缺少原生夹具脚本：{script}'
    assert candidates, f'缺少原生夹具配置：native_{name}*.yaml'
    return script, candidates[0]


def contract_payload(script, config):
    """The documented `--inventory` JSON: one object, includes each scope's contract."""
    res = subprocess.run([sys.executable, '-X', 'utf8', str(script), '--config', str(config), '--inventory'],
                         capture_output=True, text=True, encoding='utf-8', cwd=str(script.parent),
                         timeout=REQUEST_TIMEOUT)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def contract_of(script, config, scope):
    """The contract the documented `--inventory` JSON declares for one real scope.

    `scope` is the exact session scope under test: the payload holds one entry per
    declared scope, so guessing one (or taking the first) would test a different figure.
    """
    payload = contract_payload(script, config)
    return payload['scopes'][scope]['contract'], payload


def editable_records(contract):
    return [p for p in contract['parameters'] if p.get('mutability') == 'EDITABLE']


def goal_operation(contract, config, delta=0.3):
    """A declared in-range goal on a control the API can actually honour.

    Only records that declare both an operation the engine implements and the objects
    that operation moves qualify -- a record picked by metadata order can be a control
    nobody wired up. A pure translate is preferred: its millimetre effect is exactly the
    one the author declared, so the geometry-checked path applies.
    """
    records = [r for r in editable_records(contract)
               if r.get('operation') in ('translate', 'rebuild', 'resize') and r.get('objects')]
    assert records, '夹具契约必须至少声明一个带对象绑定的 EDITABLE 参数'
    record = next((r for r in records if r.get('operation') == 'translate'), records[0])
    cursor = yaml.safe_load(Path(config).read_text(encoding='utf-8'))
    for part in record['path']:
        cursor = cursor[part]
    low, high = record.get('min', float('-inf')), record.get('max', float('inf'))
    value = min(max(float(cursor) + delta, low), high)
    if value == float(cursor):
        value = min(max(float(cursor) - delta, low), high)
    assert value != float(cursor), f'参数 {record["path"]} 的声明区间容不下任何位移'
    return {'operation': 'set_parameter', 'path': list(record['path']), 'value': value}, value


def _path_options(value):
    """Every exact path array found anywhere in an options payload, whatever the nesting."""
    found = set()

    def walk(item):
        if not isinstance(item, (list, tuple)) or not item:
            return
        if all(isinstance(part, str) for part in item):
            found.add(tuple(item))
            return
        for sub in item:
            walk(sub)

    walk(value)
    return found


def _long_numeric_lists(value):
    """Every list in the payload that is a run of numbers or numeric pairs, longer than 64."""
    found = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(_long_numeric_lists(item))
    elif isinstance(value, (list, tuple)):
        if len(value) > 64 and all(
                isinstance(x, (int, float)) or (isinstance(x, (list, tuple)) and x and not isinstance(x[0], bool)
                                                and all(isinstance(n, (int, float)) for n in x))
                for x in value[:8]):
            found.append(value)
        for item in value:
            found.extend(_long_numeric_lists(item))
    return found


def _has_elision(value):
    if isinstance(value, dict):
        return value.get('elided') is True or any(_has_elision(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_elision(v) for v in value)
    return False


class Agent:
    """A live `figpact agent` session with a line-protocol client."""

    def __init__(self, script, config, scope, output_dir):
        self.proc = subprocess.Popen(
            [sys.executable, '-X', 'utf8', '-m', 'figpact.cli', 'agent',
             '--script', str(script), '--config', str(config), '--scope', scope,
             '--output-dir', str(output_dir)],
            cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)
        self._out, self._err = queue.Queue(), queue.Queue()
        for stream, sink in ((self.proc.stdout, self._out), (self.proc.stderr, self._err)):
            threading.Thread(target=self._pump, args=(stream, sink), daemon=True).start()
        self._id = 0

    @staticmethod
    def _pump(stream, sink):
        try:
            for line in stream:
                sink.put(line)
        except (ValueError, OSError):
            pass

    def _read(self):
        try:
            return self._out.get(timeout=REQUEST_TIMEOUT)
        except queue.Empty:
            raise AssertionError(f'agent 未在 {REQUEST_TIMEOUT}s 内应答；stderr：\n{self.stderr_tail()}')

    def frame(self, method, params=None):
        self._id += 1
        self.proc.stdin.write(json.dumps(
            {'jsonrpc': '2.0', 'id': self._id, 'method': method, 'params': params or {}}, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()
        line = self._read()
        assert line, f'agent 进程提前退出；stderr：\n{self.stderr_tail()}'
        frame = json.loads(line)
        assert frame.get('jsonrpc') == '2.0' and frame.get('id') == self._id, frame
        return frame

    def call(self, method, params=None):
        frame = self.frame(method, params)
        assert 'error' not in frame, f'{method} 意外报错：{frame["error"]}'
        return frame['result']

    def error(self, method, params=None):
        frame = self.frame(method, params)
        assert 'error' in frame, f'{method} 本应报错，却返回：{frame}'
        return frame['error']

    def stderr_tail(self, limit=25):
        lines = []
        while True:
            try:
                lines.append(self._err.get_nowait())
            except queue.Empty:
                return ''.join(lines[-limit:])

    def close(self):
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise AssertionError(f'agent 在 stdin 关闭后未退出；stderr：\n{self.stderr_tail()}')


@contextlib.contextmanager
def agent_session(tmp_path, name, scope):
    """A live session on the real fixture, with a private config copy and output dir.

    The script stays where it lives (its own imports resolve against the repo root);
    only the YAML under test and the published artifacts are private to the test.
    """
    script, config = fixture_paths(name)
    local_config = tmp_path / config.name
    shutil.copyfile(config, local_config)
    output_dir = tmp_path / f'published-{name}-{scope}'
    output_dir.mkdir()
    agent = Agent(script, local_config, scope, output_dir)
    try:
        yield {'script': script, 'config': local_config, 'scope': scope,
               'output_dir': output_dir, 'agent': agent}
    finally:
        agent.close()


def test_live_process_serves_the_five_operations(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        contract, _ = contract_of(w['script'], w['config'], w['scope'])
        operation, target = goal_operation(contract, w['config'])
        before_text = w['config'].read_text(encoding='utf-8')
        comments = [line for line in before_text.splitlines() if line.lstrip().startswith('#')]

        status = w['agent'].call('status')
        assert set(('snapshot', 'inspect', 'try_layout', 'render_preview', 'commit')) <= set(status['operations'])
        assert status['closed'] is False

        snap = w['agent'].call('snapshot')
        assert snap['scope'] == w['scope'] and snap['unit'] == 'mm'
        assert snap['coordinate_reference'] == 'canvas_bottom_left'
        measurement = snap['measurement']
        assert measurement['renderer_available'] is True and measurement['dpi'] > 0
        assert measurement['font_environment']['available'] is True, \
            '字体环境是测量的一部分：量不到就必须说没量到，不能留个空壳'
        assert w['agent'].call('status')['worker']['alive'] is True, \
            '跑过一次操作的会话必须有一个活着的工作进程'

        addressable = [node for node in snap['nodes'] if node.get('gid')]
        assert addressable, '这是已登记图元的真实图，快照必须给出可按 gid 寻址的节点'
        one = addressable[0]
        seen = w['agent'].call('inspect', {'ids': [one['id']], 'scope': w['scope']})
        assert seen['count'] == 1 and seen['nodes'][0]['id'] == one['id'], 'id 过滤必须精确命中'
        assert seen['nodes'][0]['bounds_mm'] == one['bounds_mm'], \
            '过滤只挑节点，不能改变测出来的几何'

        moved = w['agent'].call('try_layout', {'operations': [operation]})
        assert moved['status'] == 'OK', moved
        revision = moved['revision']

        record = next(r for r in contract['parameters'] if list(r['path']) == operation['path'])
        cursor = yaml.safe_load(before_text)
        for part in operation['path']:
            cursor = cursor[part]
        declared_mm = (target - float(cursor)) * float(record.get('scale', 1.0))
        axis = 1 if record.get('axis') == 'y' else 0
        was = {node['gid']: node['bounds_mm'] for node in snap['nodes'] if node.get('gid')}
        now = {node['gid']: node['bounds_mm'] for node in w['agent'].call('snapshot')['nodes']
               if node.get('gid')}
        for gid in record['objects']:
            shifted = now[gid][axis] - was[gid][axis]
            assert shifted == pytest.approx(declared_mm, abs=1e-3), \
                f'{gid} 未按声明的 {record["axis"]} 轴位移：实测 {shifted} mm，声明 {declared_mm} mm'

        preview = w['agent'].call('render_preview', {'revision': revision})
        assert base64.b64decode(preview['png']).startswith(b'\x89PNG\r\n\x1a\n')

        draft = w['agent'].call('commit', {'kind': 'draft', 'revision': revision})
        assert draft['verification'] == 'DRAFT_SAVED', '草稿保存不是发布验证'
        after_text = w['config'].read_text(encoding='utf-8')
        cursor = yaml.safe_load(after_text)
        for part in operation['path']:
            cursor = cursor[part]
        assert float(cursor) == pytest.approx(target)
        for line in comments:
            assert line in after_text, f'草稿保存弄丢了注释行：{line}'


def test_snapshot_is_compact_by_default_and_full_is_opt_in(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        summary = w['agent'].call('snapshot')
        full = w['agent'].call('snapshot', {'detail': 'full'})

        for payload in (summary, full):
            assert payload['revision'] and payload['scope'] == w['scope']
            assert payload['measurement']['renderer_available'] is True and payload['unit'] == 'mm'
        assert summary['detail'] == 'summary' and 'detail' not in full

        assert _long_numeric_lists(full), '该夹具的节点本来就带折线采样，否则这条断言没有意义'
        assert not _long_numeric_lists(summary), '默认快照不得倾倒折线采样/像素数组'
        assert _has_elision(summary), '被丢弃的几何必须留下明确的 elided 标记，而不是静默消失'
        assert len(json.dumps(summary, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False))


def test_stale_revision_and_unknown_method_are_safe_errors(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        stale = w['agent'].error('try_layout', {'operations': [
            {'operation': 'set_parameter', 'path': ['line_width'], 'value': 1.1}], 'revision': 'deadbeef'})
        assert stale['code'] == STALE_REVISION

        unknown = w['agent'].error('figpact.teleport', {})
        assert unknown['code'] == MISSING and 'Traceback' not in json.dumps(unknown)

        assert w['agent'].error('try_layout', {})['code'] == INVALID_PARAMS

        no_candidate = w['agent'].error('commit', {'kind': 'draft'})
        assert no_candidate['code'] == NO_CANDIDATE
        assert w['agent'].call('status')['has_candidate'] is False


def test_fail_closed_targets_and_atomic_batches(tmp_path):
    with agent_session(tmp_path, 'negatives', 'main') as w:
        contract, _ = contract_of(w['script'], w['config'], w['scope'])
        baseline = w['agent'].call('snapshot')['revision']

        locked = [list(p['path']) for p in contract['parameters'] if p.get('mutability') == 'LOCKED_SCIENCE']
        assert locked, '负例夹具必须声明 LOCKED_SCIENCE 参数，否则锁定内容无从验证'
        result = w['agent'].call('try_layout', {'operations': [
            {'operation': 'set_parameter', 'path': locked[0], 'value': 1.0}]})
        assert result['status'] == 'LOCKED', result

        unknown = w['agent'].call('try_layout', {'operations': [
            {'operation': 'set_parameter', 'path': ['definitely', 'not', 'here'], 'value': 1.0}]})
        assert unknown['status'] == 'UNSUPPORTED_PATH', unknown
        assert unknown['revision'] == baseline

        operation, _ = goal_operation(contract, w['config'])
        mixed = w['agent'].call('try_layout', {'operations': [
            operation, {'operation': 'set_parameter', 'path': ['definitely', 'not', 'here'], 'value': 1.0}]})
        assert mixed['status'] != 'OK'
        assert w['agent'].call('status')['has_candidate'] is False, '失败的批次不得留下部分候选'
        assert w['agent'].call('snapshot')['revision'] == baseline


def test_relation_mapping_outcomes_are_explicit(tmp_path):
    with agent_session(tmp_path, 'negatives', 'main') as w:
        contract, _ = contract_of(w['script'], w['config'], w['scope'])
        missing = [r for r in contract['relations'] if not r.get('controlled_by')]
        many = [r for r in contract['relations'] if len(r.get('controlled_by', [])) > 1]
        assert missing, '负例夹具必须声明一个无映射关系，否则 UNSUPPORTED 无从谈起'
        assert many, '负例夹具必须声明一个多映射关系，否则 AMBIGUOUS 无从谈起'

        absent = w['agent'].call('try_layout', {'operations': [
            {'operation': 'set_relation', 'relation_id': missing[0]['id'], 'target_mm': 2.0}]})
        assert absent['status'] == 'UNSUPPORTED_RELATION', absent

        ambiguous = w['agent'].call('try_layout', {'operations': [
            {'operation': 'set_relation', 'relation_id': many[0]['id'], 'target_mm': 2.0}]})
        assert ambiguous['status'] == 'AMBIGUOUS', ambiguous
        assert _path_options(ambiguous.get('options')) == {tuple(p) for p in many[0]['controlled_by']}, \
            'AMBIGUOUS 必须回传全部可选映射，不得替用户挑一个'
        assert w['agent'].call('status')['has_candidate'] is False


def test_publication_runs_independent_strict_and_installs_all_artifacts(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        contract, payload = contract_of(w['script'], w['config'], w['scope'])
        operation, _ = goal_operation(contract, w['config'])
        before_text = w['config'].read_text(encoding='utf-8')
        before_config = w['config'].read_bytes()
        comments = [line for line in before_text.splitlines() if line.lstrip().startswith('#')]

        moved = w['agent'].call('try_layout', {'operations': [operation]})
        assert moved['status'] == 'OK', moved
        assert base64.b64decode(w['agent'].call('render_preview', {'revision': moved['revision']})['png']) \
            .startswith(b'\x89PNG')

        unconfirmed = w['agent'].error('commit', {'kind': 'publication', 'revision': moved['revision']})
        assert unconfirmed['code'] == INVALID_PARAMS
        assert w['config'].read_bytes() == before_config

        result = w['agent'].call('commit', {'kind': 'publication', 'revision': moved['revision'], 'confirm': True})
        assert result['verification'] == 'STRICT_VERIFIED'
        declared = sorted({name for scope in payload['scopes'] for name in payload['scopes'][scope]['outputs']})
        assert declared, '夹具必须声明发布产物'
        assert sorted(result['artifacts']) == declared, '发布必须覆盖所有 scope 的全部声明产物'
        for name in declared:
            artifact = w['output_dir'] / name
            assert artifact.is_file() and artifact.stat().st_size > 0, f'缺少发布产物 {name}'
        assert not list(w['output_dir'].glob('.figpact-*')), '安装后不得残留暂存文件'
        published_text = w['config'].read_text(encoding='utf-8')
        assert w['config'].read_bytes() != before_config
        for line in comments:
            assert line in published_text, f'发布保存弄丢了注释行：{line}'


def test_own_saves_refresh_inputs_without_allowing_external_overwrites(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        contract, _ = contract_of(w['script'], w['config'], w['scope'])
        operation, target = goal_operation(contract, w['config'])
        for kind in ('draft', 'publication', 'draft'):
            revision = w['agent'].call('snapshot')['revision']
            moved = w['agent'].call('try_layout', {
                'revision': revision, 'operations': [{**operation, 'value': target}]})
            assert moved['status'] == 'OK', moved
            saved = w['agent'].call('commit', {
                'kind': kind, 'revision': moved['revision'], 'confirm': True})
            assert saved['verification'] == ('STRICT_VERIFIED' if kind == 'publication' else 'DRAFT_SAVED')
            cursor = yaml.safe_load(w['config'].read_text(encoding='utf-8'))
            for part in operation['path']:
                cursor = cursor[part]
            assert cursor == pytest.approx(target)
            target += 0.1

        revision = w['agent'].call('snapshot')['revision']
        moved = w['agent'].call('try_layout', {
            'revision': revision, 'operations': [{**operation, 'value': target}]})
        assert moved['status'] == 'OK', moved
        external = w['config'].read_text(encoding='utf-8') + '\n# External edit after candidate\n'
        w['config'].write_text(external, encoding='utf-8')
        error = w['agent'].error('commit', {'kind': 'draft', 'revision': moved['revision']})
        assert error['code'] == STALE_REVISION
        assert w['config'].read_text(encoding='utf-8') == external


def test_native_plot_with_imported_schema_loader_can_publish(tmp_path):
    script, config = fixture_paths('ftir')
    contract, payload = contract_of(script, config, 'main')
    operation, _ = goal_operation(contract, config)
    local_script = tmp_path / script.name
    local_config = local_script.with_suffix('.yaml')
    local_config.write_bytes(config.read_bytes())
    local_script.write_text(
        'import sys\n'
        f'sys.path.insert(0, {str(ROOT)!r})\n'
        'from tests.fixtures.native_ftir import *\n'
        'from figpact.config import load_config\n'
        'if __name__ == "__main__":\n'
        '    import runpy\n'
        f'    runpy.run_path({str(script)!r}, run_name="__main__")\n',
        encoding='utf-8')
    output_dir = tmp_path / 'exports'
    agent = Agent(local_script, local_config, 'main', output_dir)
    try:
        snapshot = agent.call('snapshot')
        moved = agent.call('try_layout', {
            'revision': snapshot['revision'], 'operations': [operation]})
        assert moved['status'] == 'OK' and moved['science_unchanged'] is True, moved
        published = agent.call('commit', {
            'kind': 'publication', 'revision': moved['revision'], 'confirm': True})
        assert published['verification'] == 'STRICT_VERIFIED'
        expected = sorted({name for scope in payload['scopes']
                           for name in payload['scopes'][scope]['outputs']})
        assert sorted(published['artifacts']) == expected
        for name in expected:
            path = output_dir / name
            if path.suffix == '.png':
                assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    finally:
        agent.close()


def test_failed_strict_changes_nothing_even_when_preview_is_clean(tmp_path):
    with agent_session(tmp_path, 'negatives', 'main') as w:
        contract, payload = contract_of(w['script'], w['config'], w['scope'])
        operation, _ = goal_operation(contract, w['config'])
        before_config = w['config'].read_bytes()
        declared = sorted({name for scope in payload['scopes'] for name in payload['scopes'][scope]['outputs']})
        assert declared, '夹具必须声明发布产物'
        stale = w['output_dir'] / declared[0]
        stale.write_bytes(b'previous official artifact')
        before_outputs = {p.name: p.read_bytes() for p in w['output_dir'].iterdir() if p.is_file()}

        moved = w['agent'].call('try_layout', {'operations': [operation]})
        assert moved['status'] == 'OK', moved
        preview = w['agent'].call('render_preview', {'revision': moved['revision']})
        assert not preview.get('qa'), '本负例的预览必须干净，否则证明不了「预览干净也拦得住」'

        error = w['agent'].error('commit', {'kind': 'publication', 'revision': moved['revision'], 'confirm': True})
        assert error['code'] == COMMIT_REJECTED
        assert w['config'].read_bytes() == before_config, '严格校验失败后配置不得改动'
        assert {p.name: p.read_bytes() for p in w['output_dir'].iterdir() if p.is_file()} == before_outputs, \
            '严格校验失败后正式产物必须逐字节不变'


def test_external_config_change_between_candidate_and_commit_is_refused(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        contract, _ = contract_of(w['script'], w['config'], w['scope'])
        operation, _ = goal_operation(contract, w['config'])
        moved = w['agent'].call('try_layout', {'operations': [operation]})
        assert moved['status'] == 'OK'

        external = w['config'].read_text(encoding='utf-8') + '\n# 外部改动\n'
        w['config'].write_text(external, encoding='utf-8')
        assert w['agent'].error('commit', {'kind': 'draft', 'revision': moved['revision']})['code'] == STALE_REVISION
        assert w['config'].read_text(encoding='utf-8') == external, '不得覆盖期间发生的外部改动'


def test_source_fingerprint_covers_declared_inputs_and_skips_outputs(tmp_path):
    from figpact import agent_api

    figure = tmp_path / 'figure'
    figure.mkdir()
    script = figure / 'native_plot.py'
    script.write_text('SCOPES = ("main",)\n', encoding='utf-8')
    config = figure / 'native_plot.yaml'
    config.write_text('canvas_w_mm: 60.0\n', encoding='utf-8')
    artifact = figure / 'native_plot_main.png'
    artifact.write_bytes(b'official artifact')
    sample = tmp_path / 'instrument' / 'sample.CSV'
    sample.parent.mkdir()
    sample.write_text('1,2\n', encoding='utf-8')

    def fingerprint():
        return agent_api.source_fingerprint(script, config, exclude=['native_plot_main.png'],
                                            extra=[str(sample)])

    base = fingerprint()
    artifact.write_bytes(b'republished artifact')
    assert fingerprint() == base, '重发的正式产物不是源变化，不该让候选作废'
    sample.write_text('1,3\n', encoding='utf-8')
    assert fingerprint() != base, '脚本目录之外的声明科学输入必须算进指纹'
    changed = fingerprint()
    sample.unlink()
    assert fingerprint() != changed, '声明过的输入消失是变化，不是静默忽略'

    # 显式声明的科学输入赢过一切排除：哪怕它与产物同名同路径，也照样算源。
    declared_output = agent_api.source_fingerprint(script, config, exclude=['native_plot_main.png'],
                                                   extra=[str(artifact)])
    artifact.write_bytes(b'edited artifact bytes')
    assert agent_api.source_fingerprint(script, config, exclude=['native_plot_main.png'],
                                       extra=[str(artifact)]) != declared_output, \
        '声明的科学输入与产物同名同路径时，输入声明赢，改它必须算源变化'


def test_session_cleanup_and_restart_are_exposed(tmp_path):
    with agent_session(tmp_path, 'ftir', 'main') as w:
        first = w['agent'].call('snapshot')
        running = w['agent'].call('status')
        assert running['closed'] is False and running['worker']['alive'] is True
        assert isinstance(running['worker']['pid'], int), '活着的会话必须报出真实子进程 pid'
        first_pid = running['worker']['pid']

        assert w['agent'].call('close')['status'] == 'closed'
        assert w['agent'].call('status')['closed'] is True
        assert w['agent'].error('snapshot', {})['code'] == SESSION_CLOSED
        assert w['agent'].close() == 0, 'stdin 关闭后工作进程与会话必须一起退出'

        restarted = Agent(w['script'], w['config'], w['scope'], w['output_dir'])
        try:
            reopened = restarted.call('snapshot')
            again = restarted.call('status')
            assert again['closed'] is False and again['worker']['alive'] is True
            assert again['worker']['pid'] != first_pid, '重启必须是新的工作进程，不是复用旧的'
            assert reopened['scope'] == w['scope']
            assert reopened['revision'] == first['revision'], \
                '同一份脚本与配置在新进程里必须得到同一张候选图（重新读源，不吃陈旧缓存）'
        finally:
            restarted.close()


def test_inventory_check_effect_uses_the_real_validator_and_never_fakes_a_pass():
    negatives, negatives_config = fixture_paths('negatives')
    defects = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'figpact.cli', 'inventory',
                              '--script', str(negatives), '--config', str(negatives_config),
                              '--scope', 'main', '--check-effect'],
                             cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
                             timeout=REQUEST_TIMEOUT)
    assert defects.returncode != 0, f'负例夹具的假绑定必须被判为缺陷：\n{defects.stdout}'

    legacy = FIXTURES / 'synth_plot.py'
    if legacy.is_file():
        res = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'figpact.cli', 'inventory',
                              '--script', str(legacy), '--config', str(FIXTURES / 'synth.yaml'),
                              '--check-effect'],
                             cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
                             timeout=REQUEST_TIMEOUT)
        assert res.returncode != 0, (
            '没有原生契约的脚本不能拿到「全部通过」：\n' + res.stdout + res.stderr)


def _capture_science(*, pixels=((0, 1), (2, 3)), text='band A', rotation=0.0, span=(0.2, 0.5),
                     values=(1.0, 2.0), offsets=((0.0, 0.0), (1.0, 1.0)), frame_width=0.2,
                     curve=((0.0, 1.0), (0.0, 1.0)), bar=(0.1, 0.4), display_shift_mm=0.0,
                     layout=('img', 'panel_frame', 'curve', 'pts', 'err', 'peak_label'),
                     guides=('bar',), other_types=(), axes_box=None):
    """One real figure; `layout` nodes claim LAYOUT policy, `guides` are also typed as guides."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    from figpact import GidRegistry, apply_display_shift, science

    fig, ax = plt.subplots(figsize=(3, 2), dpi=72)
    try:
        if axes_box is not None:
            ax.set_position(list(axes_box))
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
        artists = {
            'img': ax.imshow(np.asarray(pixels), extent=(0.0, 1.0, 1.0, 0.0), origin='upper'),
            'window': ax.axvspan(*span),
            'err': LineCollection([[(0, 0), (1, 1)], [(0, 1), (1, 0)]]),
            'pts': ax.scatter([0, 1], [0, 1]),
            'peak_label': ax.text(0.1, 0.9, text),
            'panel_frame': Rectangle((0.0, 0.0), frame_width, 0.1),
        }
        artists['curve'] = ax.plot(list(curve[0]), list(curve[1]))[0]
        artists['bar'] = Line2D(list(bar), [0.5, 0.5], transform=ax.transAxes)
        ax.add_line(artists['bar'])
        artists['peak_label'].set_rotation(rotation)
        artists['pts'].set_offsets(list(offsets))
        if values is not None:
            artists['err'].set_array(np.asarray(values))
        ax.add_collection(artists['err'])
        ax.add_patch(artists['panel_frame'])
        registry = GidRegistry()
        for gid, artist in artists.items():
            registry.register(artist, gid)
        declarations = {'nodes': {
            **{gid: {'science_policy': 'LAYOUT'} for gid in layout},
            **{gid: {'science_policy': 'LAYOUT', 'type': 'guide'} for gid in guides},
            **{gid: {'science_policy': 'LAYOUT', 'type': 'unknown_kind'} for gid in other_types}}}
        if display_shift_mm:
            for gid in ('window', 'err', 'pts', 'peak_label', 'curve', 'bar'):
                apply_display_shift(artists[gid], dx_mm=display_shift_mm, dy_mm=display_shift_mm)
        return science.capture_science(fig, registry, declarations=declarations)
    finally:
        plt.close(fig)


def test_science_blocks_pixel_tampering_even_when_tagged_layout():
    from figpact import science

    baseline = _capture_science()
    assert 'img' in baseline['objects'], '图像像素必须进入保护载荷，即便节点被（错误地）标成 LAYOUT'
    assert 'img' in _capture_science(guides=('bar', 'img'))['objects'], \
        '图像像素即便被标成 guide 也仍然受保护'
    assert science.compare_science(baseline, _capture_science()) == [], '同一份真实图必须指纹一致'
    tampered = science.compare_science(baseline, _capture_science(pixels=((0, 1), (2, 4))))
    assert tampered and tampered[0]['rule_id'] == 'SCIENCE_CHANGED' \
        and 'img' in tampered[0]['object_ids'], '标成 LAYOUT 的图像像素篡改必须被拦住'


def test_science_blocks_text_change_and_allows_rotation():
    from figpact import science

    baseline = _capture_science()
    assert _capture_science(rotation=35.0)['digest'] == baseline['digest'], '旋转是布局，不进内容哈希'
    relabel = science.compare_science(baseline, _capture_science(text='band B'))
    assert relabel and 'peak_label:text' in relabel[0]['object_ids'], '文本内容变化必须被拦住'
    assert _capture_science(guides=('bar', 'peak_label'))['digest'] == baseline['digest'], \
        '文本是内容：标成 LAYOUT 或 guide 都不豁免'


def test_science_blocks_wrongly_tagged_curve_and_scatter_data():
    from figpact import science

    baseline = _capture_science()
    assert 'curve' in baseline['objects'] and 'offsets' in baseline['objects']['pts'], \
        '标成 LAYOUT 的曲线数组与散点 offsets 仍是科学数据'
    curve_change = science.compare_science(baseline, _capture_science(curve=((0.0, 1.0), (0.0, 2.0))))
    assert curve_change and 'curve' in curve_change[0]['object_ids'], '曲线数据被改必须被拦住'
    points_change = science.compare_science(baseline, _capture_science(offsets=((0.0, 0.0), (1.0, 2.0))))
    assert points_change and 'pts' in points_change[0]['object_ids'], \
        '散点 offsets 被改（get_array 为 None）必须被拦住'
    assert _capture_science(display_shift_mm=1.5)['digest'] == baseline['digest'], \
        '图元 transform 平移不改变原始数组，不得算作科学变化'


def test_science_only_a_declared_guide_is_decorative_geometry():
    from figpact import science

    guided = _capture_science()
    assert 'bar' not in guided['objects'], '声明为 guide 的装饰引导线才豁免'
    assert _capture_science(bar=(0.2, 0.6))['digest'] == guided['digest'], \
        '装饰引导线的位置变化不算科学变化'
    policy_only = _capture_science(guides=(), layout=('bar',))
    assert 'bar' in policy_only['objects'], '只有 LAYOUT 策略、没有 guide 类型：仍然受保护'
    moved = science.compare_science(policy_only, _capture_science(guides=(), layout=('bar',),
                                                                  bar=(0.2, 0.6)))
    assert moved and 'bar' in moved[0]['object_ids'], '未声明为 guide 的引导线被改必须被拦住'
    unknown = _capture_science(other_types=('curve',))
    assert 'curve' in unknown['objects'], '未知 type 必须 fail closed，不豁免'
    assert science.compare_science(unknown, _capture_science(other_types=('curve',),
                                                            curve=((0.0, 1.0), (0.0, 2.0)))), \
        '未知 type 的曲线数据被改必须被拦住'


def test_science_blocks_span_window_change_but_ignores_display_shift():
    from figpact import science

    baseline = _capture_science()
    shifted = _capture_science(display_shift_mm=1.0)
    assert shifted['digest'] == baseline['digest'], '纯显示位移不是科学变化（受保护 span 平移 1mm 亦然）'
    widened = science.compare_science(baseline, _capture_science(span=(0.2, 0.8)))
    assert widened and 'window' in widened[0]['object_ids'], '受保护窗口的数据范围变化必须被拦住'


def test_science_keeps_collection_values_apart_from_decorative_layout():
    from figpact import science

    baseline = _capture_science()
    assert 'panel_frame' in baseline['objects'], '只有 LAYOUT 策略的装饰框仍然受保护'
    assert 'values' in baseline['objects']['err'], '集合 value 数组永远是数据'
    frame_change = science.compare_science(baseline, _capture_science(frame_width=0.9))
    assert frame_change and 'panel_frame' in frame_change[0]['object_ids'], \
        '策略标签不能豁免矩形几何'
    values_changed = science.compare_science(baseline, _capture_science(values=(1.0, 5.0)))
    assert values_changed and 'err' in values_changed[0]['object_ids'], '集合 value 变化必须被拦住'
    offsets_changed = science.compare_science(
        baseline, _capture_science(offsets=((0.0, 0.0), (1.5, 1.0))))
    assert offsets_changed and 'pts' in offsets_changed[0]['object_ids'], '散点偏移变化必须被点名'
    plain = _capture_science(values=None)
    assert 'offsets' in plain['objects']['err'], \
        'get_array 为 None 的集合仍按原始 segments/offsets 保护'
    guided = _capture_science(values=(1.0, 2.0), guides=('bar', 'err'))
    assert 'values' in guided['objects']['err'] and 'segments' not in guided['objects']['err'], \
        '声明为 guide 的集合只豁免几何，value 数组仍受保护'


def test_science_ignores_panel_movement_but_not_payload_change():
    from figpact import science

    baseline = _capture_science()
    moved = _capture_science(axes_box=(0.3, 0.25, 0.5, 0.6))
    assert moved['digest'] == baseline['digest'], '面板位移是布局，不是科学变化'
    changed = science.compare_science(moved, _capture_science(axes_box=(0.3, 0.25, 0.5, 0.6),
                                                             span=(0.2, 0.8)))
    assert changed and 'window' in changed[0]['object_ids'], \
        '位移过的图上改受保护窗口的数据范围，仍然必须被拦住'


def _capture_viewport(*, figure_h_mm=50.0, panel_mm=30.0, units_per_mm=0.5, origin=10.0,
                      scale=None, ylim_bottom=None, declared_units=None, declare=True):
    """One real a.u. y axis whose declared linear viewport is the readonly layout reference."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    from figpact import GidRegistry, science

    scale = units_per_mm if scale is None else scale
    bottom = origin if ylim_bottom is None else ylim_bottom
    fig, ax = plt.subplots(figsize=(3.0, figure_h_mm / 25.4), dpi=72)
    try:
        ax.set_gid('fig.main.axes')
        ax.set_position([0.2, 0.2, 0.6, panel_mm / figure_h_mm])
        ax.set_ylim(bottom, bottom + panel_mm * scale)
        (signal,) = ax.plot([0.0, 1.0], [0.0, 1.0])
        registry = GidRegistry()
        registry.register(signal, 'signal')
        declarations = {}
        if declare:
            declarations = {'layout_viewports': {'fig.main.axes': {
                'axis': 'y', 'origin': origin,
                'units_per_mm': units_per_mm if declared_units is None else declared_units}}}
        return science.capture_science(fig, registry, declarations=declarations)
    finally:
        plt.close(fig)


def test_science_declared_viewport_allows_headroom_but_refuses_rescale_and_origin_move():
    from figpact import science

    baseline = _capture_viewport()
    assert baseline['objects']['fig.main.axes:view']['viewport']['verified'] is True, \
        '真实线性 y 视口必须通过声明校验'
    headroom = _capture_viewport(figure_h_mm=60.0, panel_mm=45.0)
    assert headroom['digest'] == baseline['digest'], \
        '声明了线性 y 视口时，加高画布带来的抬头空间不是科学变化'
    rescale = science.compare_science(baseline, _capture_viewport(scale=0.6))
    assert rescale and rescale[0]['rule_id'] == 'SCIENCE_CHANGED', '信号尺度变化必须被拦住'
    origin_move = science.compare_science(baseline, _capture_viewport(ylim_bottom=12.0))
    assert origin_move and origin_move[0]['rule_id'] == 'SCIENCE_CHANGED', '视口原点变化必须被拦住'
    retuned = science.compare_science(baseline, _capture_viewport(declared_units=0.9))
    assert retuned and retuned[0]['rule_id'] == 'SCIENCE_CHANGED', \
        '把声明改成迁就实际尺度同样不得算作不变'


def test_science_locks_windows_without_a_declared_viewport():
    from figpact import science

    locked = _capture_viewport(declare=False)
    assert 'ylim' in locked['objects']['fig.main.axes:view'], '没有声明的窗口按原始 ylim 指纹化'
    taller = _capture_viewport(figure_h_mm=60.0, panel_mm=45.0, declare=False)
    blocked = science.compare_science(locked, taller)
    assert blocked and blocked[0]['rule_id'] == 'SCIENCE_CHANGED', \
        '未声明的窗口即便只是加高画布也必须算作科学变化'


def test_contract_and_science_fail_closed():
    from figpact import contracts, patch, science

    with pytest.raises(ValueError):
        contracts.validate_contract({'parameters': [{'path': ['a_mm'], 'objects': ['x']}],
                                     'relations': []})
    with pytest.raises(ValueError):
        contracts.validate_contract({'parameters': [{'path': ['a_mm'], 'mutability': 'LOCKED_SCIENCE',
                                                     'tolerance': 0.1}], 'relations': []})
    with pytest.raises(ValueError):
        contracts.validate_contract({'parameters': [{'path': ['a_mm'], 'mutability': 'EDITABLE',
                                                     'unit': 'mm', 'operation': 'translate',
                                                     'axis': 'x', 'objects': ['x']}],
                                     'relations': [], 'outputs': ['../outside.png']})
    # expected.axis 只对真正的 translate 目标必填：平移声明没有方向就无从核对。
    with pytest.raises(ValueError):
        contracts.validate_contract({'parameters': [
            {'path': ['a_mm'], 'mutability': 'EDITABLE', 'unit': 'mm', 'operation': 'translate',
             'axis': 'x', 'objects': ['x'],
             'expected': {'kind': 'translate', 'objects': ['x'], 'preserve': []}}], 'relations': []})
    # style 类效果本来就没有方向：缺席或显式 None 都算未声明，不得因此拒掉整张图的契约。
    for style_axis in ({}, {'axis': None}):
        contracts.validate_contract({'parameters': [
            {'path': ['dpi'], 'mutability': 'EDITABLE', 'unit': 'dpi', 'operation': 'rebuild',
             'objects': ['x'],
             'expected': {'kind': 'style', 'objects': ['x'], 'preserve': [], **style_axis}}],
            'relations': []})
    with pytest.raises(ValueError):
        contracts.validate_contract({'parameters': [
            {'path': ['dpi'], 'mutability': 'EDITABLE', 'unit': 'dpi', 'operation': 'rebuild',
             'objects': ['x'],
             'expected': {'kind': 'style', 'objects': ['x'], 'axis': 'z', 'preserve': []}}],
            'relations': []})
    catalog = contracts.parameter_catalog({'parameters': [
        {'path': ['a_mm'], 'key': 'a', 'mutability': 'EDITABLE', 'unit': 'mm',
         'operation': 'translate', 'axis': 'x', 'objects': ['x'], 'min': -1, 'max': 1},
        {'path': ['locked'], 'key': 'l', 'mutability': 'LOCKED_SCIENCE'}], 'relations': []})
    patch.validate_patch({'a_mm': 0.5}, catalog)
    with pytest.raises(ValueError):
        # 锁定参数不得进入可编辑目录，T4 保存门必须拒绝它
        patch.validate_patch({'locked': 1}, catalog)

    unverified = science.compare_science({}, {'digest': 'x'})
    assert unverified and unverified[0]['severity'] == 'blocker' \
        and unverified[0]['rule_id'] == 'SCIENCE_UNVERIFIED', '缺一侧指纹必须判为未验证，不能算相同'
    assert science.compare_science({'digest': 'x', 'objects': {'a': 1}},
                                   {'digest': 'x', 'objects': {'a': 1}}) == []
    changed = science.compare_science({'digest': 'x', 'objects': {'a': 1}},
                                      {'digest': 'y', 'objects': {'a': 2}})
    assert changed and changed[0]['object_ids'] == ['a']


# ──────────────────────────────────────────────────────────────────────────────
# 发布安全：逐作用域契约、嵌套产物事务、发布根越界、安装前的输入复检
# ──────────────────────────────────────────────────────────────────────────────

#: 只声明契约、不画图的探针脚本：'main' 永远合法，'other' 按用例写成要拒绝的样子。
PLAN_PROBE_SOURCE = (
    'SCOPES = ("main", "other")\n'
    'FIGURE_ID = "fig_plan_probe"\n'
    'OTHER_OUTPUTS = {outputs!r}\n'
    'OTHER_PARAMETERS = {parameters}\n'
    '\n'
    '\n'
    'def _contract(scope, outputs, parameters=()):\n'
    '    return {{"scope": scope, "version": 1, "parameters": list(parameters), "relations": [],\n'
    '            "groups": [], "nodes": {{}}, "outputs": list(outputs)}}\n'
    '\n'
    '\n'
    'def layout_contract(scope):\n'
    '    if scope != "other":\n'
    '        return _contract(scope, ["main.png"])\n'
    '    return _contract(scope, OTHER_OUTPUTS, OTHER_PARAMETERS)\n'
)


def plan_worker(script, config):
    """发布门真正调用的内部分析工作进程（`figpact.agent_api --worker`）。"""
    request = {'command': 'plan', 'script': str(script), 'config': str(config)}
    res = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'figpact.agent_api', '--worker'],
                         input=json.dumps(request), text=True, encoding='utf-8',
                         capture_output=True, cwd=str(ROOT), timeout=REQUEST_TIMEOUT)
    if res.returncode == 0:
        return json.loads(res.stdout)
    lines = [line for line in res.stderr.splitlines() if line.strip()]
    return {'error': json.loads(lines[-1])['error']}


def fixture_wrapper(script, definitions=(), *, strict_log=None):
    """原生夹具在临时目录里的一份副本，只加上本用例要声明的那些东西。

    包装脚本导入真实夹具模块（构建器仍是生产那份），并把 `definitions` 原样接在后面。
    `strict_log` 给 `__main__` 块加一行日志：只有脚本被当作严格构建入口执行时这个文件才
    会出现，所以「文件不存在」是「严格入口没启动」的直接证据，不是对实现结构的猜测。
    """
    lines = [
        'import sys\n',
        f'sys.path.insert(0, {str(ROOT)!r})\n',
        'from tests.fixtures.native_ftir import *\n',
        'from figpact.config import load_config\n',
        *definitions,
        'if __name__ == "__main__":\n',
    ]
    if strict_log is not None:
        lines.append(f'    open({str(strict_log)!r}, "a", encoding="utf-8").write("strict entry\\n")\n')
    lines += [
        '    import runpy\n',
        f'    runpy.run_path({str(script)!r}, run_name="__main__")\n',
    ]
    return ''.join(lines)


def outputs_override(scope, names):
    """只把这一个作用域声明的产物换成 `names` 的包装脚本定义。"""
    return [
        '_fixture_contract = layout_contract\n'
        '\n'
        '\n'
        'def layout_contract(scope):\n'
        '    contract = dict(_fixture_contract(scope))\n'
        f'    if scope == {scope!r}:\n'
        f'        contract["outputs"] = list({list(names)!r})\n'
        '    return contract\n',
    ]


def test_plan_validates_every_declared_scope_and_refuses_unsafe_artifacts(tmp_path):
    """发布按全部 scope 装产物：别的作用域契约坏掉或路径越界，任何一张图都不许发。"""
    config = tmp_path / 'plan_probe.yaml'
    config.write_text('canvas_w_mm: 60.0\n', encoding='utf-8')
    cases = [
        (['exports/other.png', 'plain.txt'], '()', True),
        (['../escape.png'], '()', False),
        (['/figpact-escape.png'], '()', False),
        (['C:/figpact-escape.png'], '()', False),
        (['other.png', 5], '()', False),
        (['other:stream.png'], '()', False),
        ([], '()', False),
        (['other.png'], '([{"path": ["a_mm"], "objects": ["x"]}],)', False),
    ]
    for index, (outputs, parameters, accepted) in enumerate(cases):
        script = tmp_path / f'plan_probe_{index}.py'
        script.write_text(PLAN_PROBE_SOURCE.format(outputs=outputs, parameters=parameters),
                          encoding='utf-8')
        payload = plan_worker(script, config)
        label = f'other.outputs={outputs!r} other.parameters={parameters}'
        if accepted:
            assert 'error' not in payload, (label, payload)
            assert payload['scopes'] == ['main', 'other'], (label, payload)
            assert payload['outputs'] == {'main': ['main.png'], 'other': outputs}, (label, payload)
        else:
            assert 'error' in payload, (label, payload)
            assert 'other' in payload['error'], f'{label}：拒绝必须点名出问题的 scope：{payload}'


def test_nested_declared_artifacts_install_and_roll_back(tmp_path):
    """嵌套声明的产物：缺的父目录要建、已存在的要换，任何一步失败整个事务退回原样。"""
    from figpact import agent_api

    staged = tmp_path / 'staged'
    staged.mkdir()
    for name in ('export.png', 'deep.txt', 'blocked.png'):
        (staged / name).write_bytes(f'{name} bytes'.encode('utf-8'))

    # 安装：父目录不存在 + 目标文件已存在，两个名字都是嵌套路径。
    out = tmp_path / 'published'
    (out / 'exports').mkdir(parents=True)
    (out / 'exports' / 'export.png').write_bytes(b'previous official artifact')
    applied, before = agent_api._install_transactional(
        {'exports/export.png': staged / 'export.png', 'deep/dir/deep.txt': staged / 'deep.txt'}, out)
    assert applied == ['deep/dir/deep.txt', 'exports/export.png'], applied
    assert before == {'exports/export.png': b'previous official artifact',
                      'deep/dir/deep.txt': None}, before
    assert (out / 'exports' / 'export.png').read_bytes() == b'export.png bytes'
    assert (out / 'deep' / 'dir' / 'deep.txt').read_bytes() == b'deep.txt bytes'
    assert not list(out.rglob('.figpact-*')), '安装完成后不得残留暂存文件'

    # 回滚：第二个产物是新文件、第三个产物的落点是目录，替换必然失败。
    rollback = tmp_path / 'rollback'
    (rollback / 'exports').mkdir(parents=True)
    (rollback / 'exports' / 'export.png').write_bytes(b'previous official artifact')
    (rollback / 'blocked.png').mkdir()
    with pytest.raises(OSError):
        agent_api._install_transactional(
            {'exports/export.png': staged / 'export.png',
             'late/new/deep.txt': staged / 'deep.txt',
             'blocked.png': staged / 'blocked.png'}, rollback)
    assert (rollback / 'exports' / 'export.png').read_bytes() == b'previous official artifact', \
        '回滚必须还原被替换掉的已存在嵌套产物'
    assert not (rollback / 'late').exists(), '回滚必须撤掉本次安装新建的目录'
    assert not list(rollback.rglob('.figpact-*')), '回滚后不得残留暂存文件'
    assert (rollback / 'blocked.png').is_dir(), '落点是目录时事务失败，但那个目录本身不归安装管'

    # 暂存阶段就失败（源不存在）：暂存文件也要清掉，落点一个字节都不动。
    staging = tmp_path / 'staging-failure'
    (staging / 'exports').mkdir(parents=True)
    (staging / 'exports' / 'export.png').write_bytes(b'previous official artifact')
    with pytest.raises(OSError):
        agent_api._install_transactional({'exports/export.png': staged / 'export.png',
                                          'missing.txt': staged / 'absent.txt'}, staging)
    assert (staging / 'exports' / 'export.png').read_bytes() == b'previous official artifact'
    assert not (staging / 'missing.txt').exists()
    assert not list(staging.rglob('.figpact-*')), '暂存失败也不得留下暂存文件'


def test_install_refuses_destinations_outside_the_output_root(tmp_path):
    """绝对路径、`..`、指向根外的符号链接：解析之后只要出了允许根就拒绝，先于任何写入。"""
    from figpact import agent_api

    source = tmp_path / 'artifact.png'
    source.write_bytes(b'artifact bytes')
    out = tmp_path / 'published'
    out.mkdir()

    escapes = [('../escape.png', tmp_path / 'escape.png'),
               (str(tmp_path / 'absolute.png'), tmp_path / 'absolute.png')]
    if os.name == 'nt':
        escapes.append(('C:/figpact-escape.png', None))
    for name, landed in escapes:
        with pytest.raises(agent_api.AgentError) as excinfo:
            agent_api._install_transactional({name: source}, out)
        assert excinfo.value.code == agent_api.COMMIT_REJECTED, (name, excinfo.value.to_error())
        if landed is not None:
            assert not landed.exists(), f'{name} 不得落到允许根之外'
    assert list(out.iterdir()) == [], '被拒绝的安装不得在允许根里留下任何东西'

    target = tmp_path / 'outside-root'
    target.mkdir()
    try:
        os.symlink(target, out / 'exports', target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip('这个平台/权限建不了目录符号链接，逃逸路径无从验证')
    with pytest.raises(agent_api.AgentError) as excinfo:
        agent_api._install_transactional({'exports/linked.png': source}, out)
    assert excinfo.value.code == agent_api.COMMIT_REJECTED, excinfo.value.to_error()
    assert list(target.iterdir()) == [], '符号链接不得把产物写到允许根之外'


def test_source_fingerprint_uses_path_identity_not_basenames(tmp_path):
    """排除与计入都按解析后的路径身份：同基名的另一份输入仍然是源。"""
    from figpact import agent_api

    figure = tmp_path / 'figure'
    (figure / 'exports').mkdir(parents=True)
    (figure / 'other').mkdir()
    script = figure / 'plot.py'
    script.write_text('SCOPES = ("main",)\n', encoding='utf-8')
    config = figure / 'plot.yaml'
    config.write_text('canvas_w_mm: 60.0\n', encoding='utf-8')
    artifact_shaped_input = figure / 'exports' / 'fig_main.png'
    artifact_shaped_input.write_bytes(b'input bytes')
    twin = figure / 'other' / 'fig_main.png'
    twin.write_bytes(b'other input bytes')
    out = tmp_path / 'published'
    out.mkdir()

    def fingerprint():
        return agent_api.source_fingerprint(script, config, exclude=['fig_main.png'], output_dir=out)

    base = fingerprint()
    (out / 'fig_main.png').write_bytes(b'official artifact')
    assert fingerprint() == base, '发布根下的正式产物按身份排除：重发不算源变化'
    twin.write_bytes(b'edited other input')
    assert fingerprint() != base, '同基名的另一份输入必须仍然算进指纹'
    changed = fingerprint()
    artifact_shaped_input.write_bytes(b'edited declared input')
    assert fingerprint() != changed, '与产物同名的文件按路径身份排除：改源目录里那一份必须算源变化'

    # 源脚本与真实配置永远是源：把它们声明成产物也不能让指纹瞎掉。
    def guarded():
        return agent_api.source_fingerprint(script, config, exclude=[script.name, config.name],
                                            output_dir=figure)

    guarded_base = guarded()
    script.write_text('SCOPES = ("main",)\n# edited\n', encoding='utf-8')
    assert guarded() != guarded_base, '脚本被声明成产物也不得从输入指纹里消失'
    edited = guarded()
    config.write_text('canvas_w_mm: 61.0\n', encoding='utf-8')
    assert guarded() != edited, '真实配置被声明成产物也不得从输入指纹里消失'


def test_source_fingerprint_tracks_nested_artifacts_and_declared_hidden_inputs(tmp_path):
    """嵌套产物按身份排除；显式声明的 `.figpact-*` 输入永远计入，消失也是变化。"""
    from figpact import agent_api

    figure = tmp_path / 'figure'
    figure.mkdir()
    script = figure / 'plot.py'
    script.write_text('SCOPES = ("main",)\n', encoding='utf-8')
    config = figure / 'plot.yaml'
    config.write_text('canvas_w_mm: 60.0\n', encoding='utf-8')
    hidden = figure / '.figpact-instrument-original.png'
    hidden.write_bytes(b'instrument original')
    out = tmp_path / 'published'
    (out / 'exports').mkdir(parents=True)
    artifact = out / 'exports' / 'fig_main.png'
    artifact.write_bytes(b'official artifact')

    def fingerprint():
        return agent_api.source_fingerprint(script, config, exclude=['exports/fig_main.png'],
                                            extra=[str(hidden)], output_dir=out)

    base = fingerprint()
    artifact.write_bytes(b'republished artifact')
    assert fingerprint() == base, '嵌套声明的产物按身份排除：重发不算源变化'
    hidden.write_bytes(b'edited instrument original')
    assert fingerprint() != base, '显式声明的 `.figpact-*` 输入必须照样计入'
    changed = fingerprint()
    hidden.unlink()
    assert fingerprint() != changed, '声明的输入消失仍是变化，不是静默忽略'


@pytest.mark.parametrize('collision', ['declared_science_input', 'real_config'])
def test_publication_refuses_an_artifact_that_would_overwrite_a_protected_file(tmp_path, collision):
    """产物落点与源脚本/配置/科学输入**是同一个文件**：直接拒绝，原件与正式产物都不动。

    冲突认的是解析后的同一个路径；同 basename 换个目录不算冲突（那是允许的）。
    """
    from figpact import agent_api

    script, fixture_config = fixture_paths('ftir')
    local_script = tmp_path / script.name
    local_config = tmp_path / 'native_ftir.yaml'
    local_config.write_bytes(fixture_config.read_bytes())
    if collision == 'real_config':
        output_dir = tmp_path
        artifact = local_config.name
        protected_path = local_config
        added = []
    else:
        output_dir = tmp_path / 'originals'
        output_dir.mkdir()
        artifact = 'fig_ftir_native_main.png'
        protected_path = output_dir / artifact
        protected_path.write_bytes(b'instrument original bytes')
        added = [f'def science_inputs():\n    return ({str(protected_path)!r},)\n']
    local_script.write_text(fixture_wrapper(script, outputs_override('main', [artifact]) + added),
                            encoding='utf-8')
    contract, _ = contract_of(script, fixture_config, 'main')
    operation, _ = goal_operation(contract, fixture_config)
    before = protected_path.read_bytes()

    session = agent_api.AgentSession(local_script, local_config, 'main', output_dir=output_dir)
    try:
        moved = session.try_layout([operation])
        assert moved['status'] == 'OK', moved
        with pytest.raises(agent_api.AgentError) as excinfo:
            session.commit('publication', confirm=True)
    finally:
        session.close()

    assert excinfo.value.code == agent_api.COMMIT_REJECTED, excinfo.value.to_error()
    assert excinfo.value.data.get('would_overwrite') == str(protected_path.resolve()), \
        excinfo.value.to_error()
    assert protected_path.read_bytes() == before, '被源脚本/配置/科学输入占着的文件一个字节都不许动'
    assert not (output_dir / 'fig_ftir_native_compare.png').exists(), '拒绝后不得安装任何产物'


def test_publication_into_a_new_nested_output_root_still_verifies(tmp_path):
    """换一个正式输出根（新目录、路径带空格、嵌套）必须照常发布：候选的依赖集不随安装目标变。"""
    from figpact import agent_api

    script, fixture_config = fixture_paths('ftir')
    local_script = tmp_path / script.name
    local_config = tmp_path / 'native_ftir.yaml'
    local_config.write_bytes(fixture_config.read_bytes())
    local_script.write_text(fixture_wrapper(script), encoding='utf-8')
    session_root = tmp_path / 'session-output'
    session_root.mkdir()
    override = tmp_path / 'published items' / 'v2'
    contract, payload = contract_of(script, fixture_config, 'main')
    operation, _ = goal_operation(contract, fixture_config)

    session = agent_api.AgentSession(local_script, local_config, 'main', output_dir=session_root)
    try:
        moved = session.try_layout([operation])
        assert moved['status'] == 'OK', moved
        published = session.commit('publication', confirm=True, output_dir=override)
    finally:
        session.close()

    assert published['verification'] == 'STRICT_VERIFIED', published
    assert published['output_dir'] == str(override.resolve()), published
    assert published['science'] == 'protected payload identical to baseline', published
    declared = sorted({name for scope in payload['scopes']
                       for name in payload['scopes'][scope]['outputs']})
    assert sorted(published['artifacts']) == declared, published
    for name in declared:
        artifact = override / name
        assert artifact.is_file() and artifact.stat().st_size, f'缺少发布产物 {name}'
    assert list(session_root.iterdir()) == [], '会话自己的输出根在换目标时不得被写入'
    assert local_config.read_bytes() != fixture_config.read_bytes(), '发布必须真的写回配置'


@pytest.mark.parametrize('drift', ['late_input', 'late_script_edit'])
def test_publication_rechecks_the_candidate_inputs_immediately_before_installing(
        tmp_path, monkeypatch, drift):
    """严格校验与科学比对要花时间：它们跑完之后源再变，候选必须作废、一个字节都不落。

    注入点就是门自己的最后一道校验步骤（`_science_diagnostics`）：改动落在「校验通过」
    之后、「安装」之前，正是没有锁能覆盖的那段窗口。
    """
    from figpact import agent_api

    script, fixture_config = fixture_paths('ftir')
    local_script = tmp_path / script.name
    local_config = tmp_path / 'native_ftir.yaml'
    local_config.write_bytes(fixture_config.read_bytes())
    local_script.write_text(fixture_wrapper(script), encoding='utf-8')
    output_dir = tmp_path / 'exports'
    output_dir.mkdir()
    contract, _ = contract_of(script, fixture_config, 'main')
    operation, _ = goal_operation(contract, fixture_config)
    late_input = tmp_path / 'late_input.csv'

    session = agent_api.AgentSession(local_script, local_config, 'main', output_dir=output_dir)
    checked = []
    original = agent_api.AgentSession._science_diagnostics

    def late_change(self, candidate_yaml, scopes):
        diagnostics = original(self, candidate_yaml, scopes)
        checked.append(scopes)
        assert diagnostics == [], f'这条用例必须先通过科学校验才谈得上复检：{diagnostics}'
        if drift == 'late_script_edit':
            local_script.write_text(local_script.read_text(encoding='utf-8') + '# late external edit\n',
                                    encoding='utf-8')
        else:
            late_input.write_text('late external science input\n', encoding='utf-8')
        return diagnostics

    monkeypatch.setattr(agent_api.AgentSession, '_science_diagnostics', late_change)
    try:
        moved = session.try_layout([operation])
        assert moved['status'] == 'OK', moved
        with pytest.raises(agent_api.AgentError) as excinfo:
            session.commit('publication', confirm=True)
    finally:
        session.close()

    assert checked, '必须真的走到严格校验之后、安装之前的那一次输入复检'
    assert excinfo.value.code == agent_api.STALE_REVISION, excinfo.value.to_error()
    assert late_input.is_file() or local_script.read_text(encoding='utf-8').endswith('# late external edit\n'), \
        '注入的晚到改动必须还在盘上（门不回滚外部改动）'
    assert local_config.read_bytes() == fixture_config.read_bytes(), '拒绝后配置不得改动'
    assert list(output_dir.iterdir()) == [], '拒绝后一个正式产物都不许落地'


def test_publication_refuses_an_unusable_foreign_scope_before_starting_strict(tmp_path):
    """别的作用域声明了越界产物：严格构建入口一次都不许启动，正式产物与配置一字节不动。

    探针脚本在被当作 `__main__` 执行（= 严格构建入口）时先写一行日志，所以「日志不存在」
    就是「严格入口没启动」的直接证据，不是对实现内部结构的猜测。
    """
    from figpact import agent_api

    script, fixture_config = fixture_paths('ftir')
    local_script = tmp_path / script.name
    local_config = tmp_path / 'native_ftir.yaml'
    local_config.write_bytes(fixture_config.read_bytes())
    strict_entry = tmp_path / 'strict-entry.log'
    extra_scope = 'escaped'
    local_script.write_text(fixture_wrapper(script, [
        '_fixture_contract = layout_contract\n'
        '\n'
        '\n'
        f'SCOPES = (*SCOPES, {extra_scope!r})\n'
        '\n'
        '\n'
        'def layout_contract(scope):\n'
        f'    if scope == {extra_scope!r}:\n'
        '        return {"scope": scope, "version": 1, "parameters": [], "relations": [],\n'
        '                "groups": [], "nodes": {}, "outputs": ["../escaped.png"]}\n'
        '    return _fixture_contract(scope)\n',
    ], strict_log=strict_entry), encoding='utf-8')
    output_dir = tmp_path / 'exports'
    output_dir.mkdir()
    published = output_dir / 'fig_ftir_native_main.png'
    published.write_bytes(b'previous official artifact')
    contract, _ = contract_of(script, fixture_config, 'main')
    operation, _ = goal_operation(contract, fixture_config)

    session = agent_api.AgentSession(local_script, local_config, 'main', output_dir=output_dir)
    try:
        moved = session.try_layout([operation])
        assert moved['status'] == 'OK', moved
        with pytest.raises(agent_api.AgentError) as excinfo:
            session.commit('publication', confirm=True)
    finally:
        session.close()

    assert excinfo.value.code == agent_api.COMMIT_REJECTED, excinfo.value.to_error()
    assert excinfo.value.data.get('command') == 'plan', excinfo.value.to_error()
    assert 'escaped' in str(excinfo.value), '拒绝必须点名越界的那个作用域'
    assert not strict_entry.exists(), '契约/路径未通过时严格构建入口不得启动'
    assert not (tmp_path / 'escaped.png').exists(), '越界产物不得在沙箱外落地'
    assert published.read_bytes() == b'previous official artifact', '正式产物不得改动'
    assert sorted(p.name for p in output_dir.iterdir()) == [published.name]
    assert local_config.read_bytes() == fixture_config.read_bytes(), '配置不得改动'


def test_approved_path_refuses_a_linked_source_or_destination(tmp_path):
    """被解析到允许根之外的声明产物路径一律拒绝，父目录是符号链接也算；根内嵌套路径照常。"""
    from figpact import agent_api

    sandbox = tmp_path / 'sandbox'
    sandbox.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'stolen.png').write_bytes(b'outside bytes')
    assert agent_api._approved_path(sandbox, 'exports/fig.png', '严格校验产物') \
        == (sandbox / 'exports' / 'fig.png').resolve(), '根内的嵌套相对路径必须照常解析'

    escapes = ['../escape.png', str(outside / 'stolen.png')]
    if os.name == 'nt':
        escapes.append('C:/figpact-escape.png')
    for name in escapes:
        with pytest.raises(agent_api.AgentError) as excinfo:
            agent_api._approved_path(sandbox, name, '严格校验产物')
        assert excinfo.value.code == agent_api.COMMIT_REJECTED, (name, excinfo.value.to_error())

    try:
        os.symlink(outside, sandbox / 'exports', target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip('这个平台/权限建不了目录符号链接，链接逃逸无从验证')
    with pytest.raises(agent_api.AgentError) as excinfo:
        agent_api._approved_path(sandbox, 'exports/stolen.png', '严格校验产物')
    assert excinfo.value.code == agent_api.COMMIT_REJECTED, excinfo.value.to_error()

