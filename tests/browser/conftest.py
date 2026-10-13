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
#: 无绑定的作者化夹具：authoring_edit 门禁服务的是它的**副本**，原件同样一个字节都不许动。
NATIVE_SCRIPT = REPO_ROOT / 'examples' / 'python_native' / 'legacy_plain.py'

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
#: 负载下 apply 里那两次 NMR 重建要各花几秒，这条线要留够余量。
HTTP_TIMEOUT_S = 60.0
#: 指针落下后等页面承认命中的预算：hover 是异步的，固定 sleep 在负载下会读到旧值。
HOVER_TIMEOUT_S = 5.0

_LIVE_SERVERS: list['InspectorProcess'] = []

#: Chromium 拒绝连接的端口（``net::ERR_UNSAFE_PORT``）。OS 随机分配的临时端口可能落在
#: 里面（本机上就见过 4045），那时 ``page.goto`` 直接失败——这不是被测行为，换一个端口。
CHROMIUM_BLOCKED_PORTS = frozenset({
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95, 101,
    102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161, 179, 389,
    427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587, 601, 636,
    989, 990, 992, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566,
    6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080})
#: 端口撞上黑名单时的重试上限：每次都会重新起一个子进程（建图秒级），够用就好。
PORT_RETRY_ATTEMPTS = 5


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def wait_for(probe, description, *, timeout=30.0, interval=0.1):
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

    def __init__(self, port, state_home, process, stderr_path, stderr_file, config=NMR_CONFIG):
        self.port = port
        self.state_home = state_home
        self.process = process
        self.stderr_path = stderr_path
        self.stderr_file = stderr_file
        #: 服务端加载的那份配置：history 的工作区身份要用它（与脚本、scope 一起）。
        self.config = config
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

    def journal_path(self, plan: dict) -> Path:
        return self.state_home / 'source-journals' / f"{plan['journal_id']}.json"

    def journal(self, plan: dict) -> dict:
        path = self.journal_path(plan)
        assert path.exists(), f'journal 文件不存在：{path}'
        return json.loads(path.read_text(encoding='utf-8'))

    def journal_status(self, plan: dict) -> str:
        return self.journal(plan).get('status')

    def checkpoints(self, script: Path, *, scope='main') -> list[dict]:
        """按服务端记历史时用的同一身份（脚本 + 服务端配置 + scope）读回检查点。"""
        from figpact.history import HistoryStore

        store = HistoryStore(script, self.config, scope, state_home=self.state_home)
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
        self.stderr_file.close()
        try:
            _LIVE_SERVERS.remove(self)
        except ValueError:
            pass


def _launch(env, command, cwd):
    return subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding='utf-8',
                            errors='replace', env=env)


def launch_server(work_dir, *, command, cwd=REPO_ROOT, config=NMR_CONFIG, _attempt=0):
    """起一个真实 Inspector 子进程：state_home 与 stderr 都落在 ``work_dir`` 下。

    就绪的唯一信号是它自己打印的回环地址；起不来就把两侧输出一并抛出。成功的实例登记进
    ``_LIVE_SERVERS``，失败用例由 ``pytest_runtest_makereport`` 打印它的 stderr 尾部。

    ``work_dir`` 由调用方按用例给（不同脚本 / 不同配置各自一份），这就是层 1 台子复用点。
    端口由 OS 随机分配；若撞上 Chromium 的黑名单（``ERR_UNSAFE_PORT``）就杀掉重起一个。
    """
    work_dir = Path(work_dir)
    state_home = work_dir / 'state'          # 必须落在任何脚本目录之外（HistoryStore 的硬要求）
    state_home.mkdir(parents=True, exist_ok=True)
    stderr_path = work_dir / 'server-stderr.log'
    stderr_file = stderr_path.open('w', encoding='utf-8')
    env = {**os.environ, 'FIGPACT_STATE_HOME': str(state_home), 'PYTHONIOENCODING': 'utf-8'}
    process = _launch(env, command, cwd)
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

    if port in CHROMIUM_BLOCKED_PORTS and _attempt < PORT_RETRY_ATTEMPTS:
        # Chromium 拒连这些端口（ERR_UNSAFE_PORT）：这不是被测行为，换一个再来。
        process.kill()
        process.wait(timeout=15)
        stderr_file.close()
        return launch_server(work_dir, command=command, cwd=cwd, config=config,
                             _attempt=_attempt + 1)

    instance = InspectorProcess(port, state_home, process, stderr_path, stderr_file, config)
    _LIVE_SERVERS.append(instance)
    return instance


@pytest.fixture(scope='session')
def server(tmp_path_factory):
    """真实 nmr 会话子进程 + 临时 state_home；整个会话只起一次（建图秒级）。"""
    assert NMR_SCRIPT.is_file(), f'缺少被服务的例子源码：{NMR_SCRIPT}'
    assert NMR_CONFIG.is_file(), f'缺少被服务的例子配置：{NMR_CONFIG}'
    instance = launch_server(tmp_path_factory.mktemp('figpact-layer1-state'),
                             command=[sys.executable, '-m', 'figpact.inspector_server',
                                      '--example', 'nmr', '--scope', 'main', '--dpi', '600',
                                      '--port', '0'])
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture(scope='session', autouse=True)
def repo_example_untouched():
    """整轮门禁不许碰线上例子源码：写盘路径必须跑在副本上（收尾再核一次字节）。"""
    watched = {path: sha256_file(path) for path in (NMR_SCRIPT, NMR_CONFIG, NATIVE_SCRIPT)}
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
    raw.set_default_timeout(60_000)
    raw.goto(base_url + '/', wait_until='load')
    raw.wait_for_selector(READY_SELECTOR, timeout=180_000)
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
    """把指针压到标签中心、**等到页面自己承认命中这个对象**，再真点一下；返回命中 id。

    hover 是异步的：固定 sleep 在负载下会读到上一个对象的 hover。这里等的是明确状态
    （``data-hover-id`` 变成这个对象），超时就按最后看到的值返回，断言照样会把话说清楚。
    """
    x, y = label_hit_point(page, scene, node)
    page.mouse.move(x, y)
    wait_for(lambda: page.get_attribute('#inspector-root', 'data-hover-id') == node['id'],
             f'指针停在 {node["id"]} 上', timeout=HOVER_TIMEOUT_S, interval=0.05)
    hovered = page.get_attribute('#inspector-root', 'data-hover-id')
    page.mouse.click(x, y)
    return hovered


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """失败时打印 Inspector 子进程 stderr 尾部：服务端那一层的问题不藏在 pytest 里。

    顺手把报告挂在用例上（``item.rep_call`` 之类）：夹具收尾时才知道这个用例是否失败，
    才有机会打印它自己那一层的现场（比如页面 HTML 尾）。
    """
    report = yield
    setattr(item, f'rep_{report.when}', report)
    if report.failed and report.when in ('setup', 'call') and _LIVE_SERVERS:
        text = '\n'.join(f'--- Inspector 子进程 stderr 尾部（端口 {instance.port}）---\n'
                         f'{instance.stderr_tail()}' for instance in _LIVE_SERVERS)
        reporter = item.config.pluginmanager.get_plugin('terminalreporter')
        if reporter is not None:
            reporter.write_line(text)
        else:  # pragma: no cover - 没有终端插件时退回标准输出
            print(text, flush=True)
    return report
