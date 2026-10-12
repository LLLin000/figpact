"""层 1 门禁的共享夹具：真实 ``figpact.inspector_server`` 子进程 + 真实 Chromium。

门禁守的是**协议与磁盘事实**，所以夹具只提供三样东西：
  ① 一个真实子进程 ``python -m figpact.inspector_server --example nmr --scope main --dpi 600
     --port 0``：端口从它自己打印的那行解析，状态目录用临时 ``FIGPACT_STATE_HOME``，
     用完 terminate（临时目录由 pytest 回收）；
  ② 一个真实 Chromium 页面（Playwright 自带的 chromium，headless）；
  ③ 一个 ``http.client`` 确定性客户端：不经过浏览器，直接说 HTTP。

失败时 ``pytest_runtest_makereport`` 打印子进程 stderr 尾部——塌在服务端还是页面上一眼可见。
这里只搭台，不做断言；断言全在 ``test_g5b_workflow.py``。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

#: 仓库根由本文件位置推导：不依赖任何绝对路径，也就没有盘符假设。
REPO_ROOT = Path(__file__).resolve().parents[2]
NMR_SCRIPT = REPO_ROOT / 'examples' / 'nmr' / '08 NMR.py'
NMR_CONFIG = REPO_ROOT / 'examples' / 'nmr' / 'nmr.yaml'

#: 子进程就绪的唯一信号：它自己打印的回环地址。
URL_RE = re.compile(r'http://127\.0\.0\.1:(\d+)')
BOOT_TIMEOUT_S = 300.0
#: 页面自己声明「图帧已核对一致」的时刻；之前点击没有意义。
READY_SELECTOR = '#inspector-root[data-ready="true"][data-frame-state="verified"]'
#: 线路上契约的名字（字面量：测试守的是协议本身，不是实现常量）。
UI_HEADER = 'X-Figpact-Ui'
CLIENT_HEADER = 'X-Figpact-Client'
CLIENT_ID = 'layer1-chromium-client'
PLAN_VALUE = [0.0, 4.0]
PLAN_VALUE_TEXT = '[0.0, 4.0]'
#: NONE = 这个请求根本不带该 header；TOKEN = 用页面拿到的那份令牌。
NO_HEADER = object()
PAGE_TOKEN = object()
STDERR_TAIL_LINES = 80
#: 单条请求的超时：服务端是单线程 HTTPServer，页面每 3 秒还会来拉一次计划。
HTTP_TIMEOUT_S = 30.0

_LIVE_SERVERS: list['InspectorProcess'] = []


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def wait_for(probe, description, *, timeout=15.0, interval=0.1):
    """轮询一个事实直到成立；超时把最后看到的样子一并说出来，不吞。"""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        last = probe()
        if last:
            return last, True
        if time.monotonic() >= deadline:
            return last, False
        time.sleep(interval)


class InspectorProcess:
    """真实 Inspector 子进程 + 确定性 HTTP 客户端。"""

    def __init__(self, port, state_home, process, stderr_path):
        self.port = port
        self.state_home = state_home
        self.process = process
        self.stderr_path = stderr_path
        #: 页面令牌由服务端签发、注入 /frame.js；这里按服务端自己的说法读出来（不猜实现）。
        self.ui_token = self.frame_token()

    @property
    def base_url(self) -> str:
        return f'http://127.0.0.1:{self.port}'

    # ---- 线路

    def request(self, method, path, body=None, headers=None):
        """回原始文本：``/frame.js`` 不是 JSON，先把字节事实拿到手。"""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=HTTP_TIMEOUT_S)
        try:
            data, sent = None, dict(headers or {})
            if body is not None:
                data = json.dumps(body)
                sent['Content-Type'] = 'application/json'
            conn.request(method, path, data, sent)
            response = conn.getresponse()
            return response.status, response.read().decode('utf-8')
        finally:
            conn.close()

    def json(self, method, path, body=None, headers=None):
        status, text = self.request(method, path, body, headers)
        return status, (json.loads(text) if text else None)

    def get(self, path):
        return self.json('GET', path)

    # ---- 既有只读路由

    def frame(self) -> dict:
        status, payload = self.get('/api/frame')
        assert status == 200, f'/api/frame HTTP {status}'
        return payload

    def frame_token(self) -> str:
        status, text = self.request('GET', '/frame.js')
        assert status == 200, f'/frame.js HTTP {status}'
        match = re.search(r'window\.FIGPACT_UI_TOKEN=("(?:[^"\\]|\\.)*");', text)
        assert match, '服务端没有把页面会话令牌注入 /frame.js'
        return json.loads(match.group(1))

    def selection(self) -> dict:
        status, payload = self.get('/api/selection')
        assert status == 200, f'/api/selection HTTP {status}'
        return payload

    def plans(self) -> dict:
        _, payload = self.json('GET', '/api/plans')
        return {plan['plan_id']: plan for plan in payload['plans']}

    def plan(self, plan_id: str) -> dict:
        plan = self.plans().get(plan_id)
        assert plan is not None, f'计划 {plan_id} 不在 /api/plans 里'
        return plan

    # ---- 计划路由

    def mint(self, script: Path, gid: str, *, client_id=CLIENT_ID, value=PLAN_VALUE):
        """铸造 layout_edit 计划；被拒就当场断言失败（这里只走顺利路径）。"""
        status, payload = self.json('POST', '/api/plans', {
            'client_id': client_id, 'kind': 'layout_edit', 'script': str(script), 'gid': gid,
            'value': list(value),
            'reason': '层 1 门禁：页面点标签 → 客户端铸造 → 页面授权 → 客户端应用'})
        assert (status, payload['status']) == (200, 'OK'), \
            f'铸造计划被拒：HTTP {status} {payload}'
        return payload['plan']

    def authorize(self, plan_id: str, token=PAGE_TOKEN):
        headers = {} if token is NO_HEADER else {
            UI_HEADER: self.ui_token if token is PAGE_TOKEN else token}
        return self.json('POST', f'/api/plans/{plan_id}/authorize', None, headers)

    def apply(self, plan_id: str, client_id=CLIENT_ID):
        headers = {} if client_id is None else {CLIENT_HEADER: client_id}
        return self.json('POST', f'/api/plans/{plan_id}/apply', None, headers)

    # ---- 磁盘 / 私有状态的事实读取

    def journal(self, plan: dict) -> dict:
        path = self.state_home / 'source-journals' / f"{plan['journal_id']}.json"
        assert path.exists(), f'journal 文件不存在：{path}'
        return json.loads(path.read_text(encoding='utf-8'))

    def journal_status(self, plan: dict) -> str:
        return self.journal(plan).get('status')

    def checkpoints(self, script: Path, *, scope='main') -> list[dict]:
        """按服务端记历史时用的同一身份（脚本 + 服务端配置 + scope）读回检查点。"""
        from figpact.history import HistoryStore

        store = HistoryStore(script, NMR_CONFIG, scope, state_home=self.state_home)
        try:
            return store.source_changes()
        finally:
            store.close()

    # ---- 子进程

    def stderr_tail(self, lines=STDERR_TAIL_LINES) -> str:
        try:
            text = self.stderr_path.read_text(encoding='utf-8', errors='replace')
        except OSError as error:
            return f'（读不到子进程 stderr：{error}）'
        tail = text.splitlines()[-lines:]
        return '\n'.join(tail) if tail else '（子进程 stderr 为空）'

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)


def _launch(env, command, cwd):
    return subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding='utf-8',
                            errors='replace', env=env)


@pytest.fixture(scope='session')
def server(tmp_path_factory):
    """真实 nmr 会话子进程 + 临时 state_home；整个会话只起一次（建图秒级）。"""
    assert NMR_SCRIPT.is_file(), f'缺少被服务的例子源码：{NMR_SCRIPT}'
    assert NMR_CONFIG.is_file(), f'缺少被服务的例子配置：{NMR_CONFIG}'
    work_dir = tmp_path_factory.mktemp('figpact-layer1-state')
    state_home = work_dir / 'state'          # 必须落在任何脚本目录之外（HistoryStore 的硬要求）
    state_home.mkdir()
    stderr_path = work_dir / 'server-stderr.log'
    stderr_file = stderr_path.open('w', encoding='utf-8')
    env = {**os.environ, 'FIGPACT_STATE_HOME': str(state_home), 'PYTHONIOENCODING': 'utf-8'}
    process = _launch(env, [sys.executable, '-m', 'figpact.inspector_server', '--example', 'nmr',
                            '--scope', 'main', '--dpi', '600', '--port', '0'],
                      REPO_ROOT)
    lines: list[str] = []

    def drain():
        # stdout 只在启动时用一次；用一个线程读，主线程才有超时可等。
        for line in process.stdout:  # pragma: no branch - 进程结束时自然收尾
            lines.append(line)

    stderr_lines: list[str] = []

    def drain_stderr():
        for line in process.stderr:
            stderr_lines.append(line)
            stderr_file.write(line)
            stderr_file.flush()

    for target in (drain, drain_stderr):
        threading.Thread(target=target, daemon=True).start()

    deadline = time.monotonic() + BOOT_TIMEOUT_S
    port = None
    while port is None and time.monotonic() < deadline:
        for line in list(lines):
            match = URL_RE.search(line)
            if match:
                port = int(match.group(1))
                break
        if port is None:
            if process.poll() is not None:
                break
            time.sleep(0.05)
    if port is None:
        process.kill()
        process.wait(timeout=15)
        stderr_file.close()
        pytest.fail(f'Inspector 子进程没有打印可连的地址（退出码 {process.returncode}）：\n'
                    f'stdout: {"".join(lines)[-2000:]}\n'
                    f'stderr: {"".join(stderr_lines)[-4000:]}')

    instance = InspectorProcess(port, state_home, process, stderr_path)
    _LIVE_SERVERS.append(instance)
    try:
        yield instance
    finally:
        try:
            _LIVE_SERVERS.remove(instance)
        except ValueError:
            pass
        instance.stop()
        stderr_file.close()


@pytest.fixture(scope='session', autouse=True)
def repo_example_untouched():
    """整轮门禁不许碰线上例子源码：写盘路径必须跑在副本上（收尾再核一次字节）。"""
    watched = {path: sha256_file(path) for path in (NMR_SCRIPT, NMR_CONFIG)}
    yield
    changed = [str(path) for path, digest in watched.items() if sha256_file(path) != digest]
    assert not changed, f'门禁改动了线上例子源码：{changed}'


@pytest.fixture(scope='session')
def nmr_source_bytes():
    """服务端正在服务的那份源码的字节：计划目标必须是它的副本，不是它本身。"""
    return NMR_SCRIPT.read_bytes()


@pytest.fixture(scope='session')
def served_label(server):
    """图中那个「要用指针点中的标签」：服务端场景里最宽的可点标签（按面积降序，确定性）。"""
    scene = json.loads(server.frame()['scene_json'])
    nodes = [node for node in scene['nodes']
             if node.get('gid') and node.get('type') == 'text'
             and node.get('measured') and not node.get('fully_clipped')]
    assert nodes, '服务端场景里没有可选中的文本标签'
    nodes.sort(key=lambda node: (-(node['bounds_mm'][2] - node['bounds_mm'][0])
                                 * (node['bounds_mm'][3] - node['bounds_mm'][1]), node['id']))
    return nodes[0]


@pytest.fixture
def plan_project(tmp_path, nmr_source_bytes, served_label):
    """写盘路径的目标文件：**服务端源码的字节 + 一条显式 LAYOUT_MM 绑定**。

    nmr 例子还没按 G4 约定声明 ``LAYOUT_MM``（源码里就是没有这条绑定），而
    ``examples/nmr`` 的科学内容不许测试改写。所以计划跑在这份副本上：除末尾追加的绑定外，
    与线上源码逐字节相同；gid 用的就是页面点中的那个标签的身份。
    """
    project = tmp_path / 'project'
    project.mkdir()
    script = project / '08 NMR.py'
    tail = ('\nLAYOUT_MM = {%r: [0.0, 0.0]}\n' % served_label['gid']).encode('utf-8')
    baseline = nmr_source_bytes + tail
    script.write_bytes(baseline)

    class Project:
        def __init__(self):
            self.script = script
            self.baseline = baseline

        def reset(self):
            """回到铸造计划前的那份字节（同一用例里铸造多个计划时用）。"""
            script.write_bytes(baseline)
            return script

        def bytes(self):
            return script.read_bytes()

        def sha256(self):
            return sha256_file(script)

    return Project()


@pytest.fixture(scope='session')
def browser():
    playwright = pytest.importorskip('playwright.sync_api',
                                     reason='层 1 门禁需要 playwright（已安装的依赖）')
    with playwright.sync_playwright() as runtime:
        engine = runtime.chromium.launch()
        try:
            yield engine
        finally:
            engine.close()


@pytest.fixture
def page(browser, server):
    """每个用例一个全新浏览器上下文：选区、页面计数器都不跨用例串味。"""
    context, handle = open_page(browser, server.base_url)
    try:
        yield handle
    finally:
        context.close()


class BrowserPage:
    """真页面 + 它自己的控制台错误清单；属性一律透传给 Playwright 的 Page。"""

    def __init__(self, page, errors):
        self._page = page
        self.console_errors = errors

    def __getattr__(self, name):
        return getattr(self._page, name)

    def debug(self) -> str:
        return page_debug(self._page)


def open_page(browser, base_url, *, width=1600, height=1000):
    """打开 Inspector 页面并等到它自己声明「图帧已核对一致」。"""
    context = browser.new_context(viewport={'width': width, 'height': height})
    raw = context.new_page()
    errors: list[str] = []
    raw.on('console', lambda message: errors.append(f'{message.type}: {message.text}')
           if message.type == 'error' else None)
    raw.on('pageerror', lambda error: errors.append(f'pageerror: {error}'))
    raw.set_default_timeout(30_000)
    raw.goto(base_url + '/', wait_until='load')
    raw.wait_for_selector(READY_SELECTOR, timeout=90_000)
    return context, BrowserPage(raw, errors)


def page_debug(page) -> str:
    """页面塌在哪儿：就绪位、状态行、计划容器、HTML 尾部。"""
    try:
        return page.evaluate("""() => {
            const root = document.getElementById('inspector-root');
            const status = document.getElementById('integrity-status');
            const plans = document.getElementById('agent-plans');
            const body = document.body ? document.body.innerHTML : '';
            return [
              `ready=${root && root.dataset.ready} frame=${root && root.dataset.frameState}`
                + ` selected=${root && root.dataset.selectedId} hover=${root && root.dataset.hoverId}`,
              `status=${status ? status.textContent.trim() : '(无状态行)'}`,
              `agent-plans=${plans ? (plans.childElementCount ? plans.outerHTML.slice(0, 1500) : '(空)') : '(不存在)'}`,
              `body tail=${body.slice(-1500)}`
            ].join('\\n');
        }""")
    except Exception as error:  # 页面已经关掉/崩了也要能说出话
        return f'（页面不可读：{type(error).__name__}: {error}）'


def scene_of(page) -> dict:
    """页面自己手里的场景（就是它核对过哈希、画在屏幕上的那一份）。"""
    return page.evaluate('JSON.parse(window.FIGPACT_INSPECTOR_FRAME.scene_json)')


def node_by_gid(scene, gid):
    for node in scene['nodes']:
        if node.get('gid') == gid:
            return node
    raise AssertionError(f'页面场景里没有 gid {gid!r} 的对象')


def label_hit_point(page, scene, node):
    """标签中心在页面上的坐标：页面 screenToMm 的逆映射，倍数取自视口矩形的实际尺寸。"""
    rect = page.evaluate("""() => { const r = document.getElementById('viewport').getBoundingClientRect();
        return {left: r.left, top: r.top, width: r.width, height: r.height}; }""")
    canvas = scene['canvas_bounds_mm']
    bounds = node['bounds_mm']
    x = rect['left'] + ((bounds[0] + bounds[2]) / 2 - canvas[0]) / (canvas[2] - canvas[0]) * rect['width']
    y = rect['top'] + (canvas[3] - (bounds[1] + bounds[3]) / 2) / (canvas[3] - canvas[1]) * rect['height']
    return x, y


def click_label(page, scene, node):
    """把指针压到标签中心、记下页面的命中事实，再真点一下；返回命中 id。"""
    x, y = label_hit_point(page, scene, node)
    page.mouse.move(x, y)
    page.wait_for_timeout(150)
    hovered = page.get_attribute('#inspector-root', 'data-hover-id')
    page.mouse.click(x, y)
    return hovered


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """失败时打印 Inspector 子进程 stderr 尾部：服务端那一层的问题不藏在 pytest 里。"""
    report = yield
    if report.failed and report.when in ('setup', 'call') and _LIVE_SERVERS:
        text = '\n'.join(f'--- Inspector 子进程 stderr 尾部（端口 {instance.port}）---\n'
                         f'{instance.stderr_tail()}' for instance in _LIVE_SERVERS)
        reporter = item.config.pluginmanager.get_plugin('terminalreporter')
        if reporter is not None:
            reporter.write_line(text)
        else:  # pragma: no cover - 没有终端插件时退回标准输出
            print(text, flush=True)
    return report
