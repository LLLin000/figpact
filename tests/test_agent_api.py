"""Consumer-visible behaviour of the local agent JSON-RPC surface.

Every test here talks to a real `figpact agent` process over stdin/stdout and asserts
only what a client sees: JSON-RPC results and error codes, files on disk, process
lifetime. No wiring, default, source-text or wording assertions.
"""
import base64
import contextlib
import json
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
