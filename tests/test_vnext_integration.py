"""原生夹具上的跨层集成：布局落进真实栅格、科学像素不变、revision 不漂移、严格门是独立的。

这一组用**通用原生夹具**（四联显微图 / 曲线+图像混排），走真实协议与真实渲染：
`figpact.runtime.FigureWorker`（子进程 JSON-lines）、`figpact.session.FigureSession`（热会话）、
`figpact.scene`/`figpact.geometry`（快照与关系测量）、`figpact.science`（受保护载荷）、
`figpact.agent_api.AgentSession`（提交门）。没有 mock、没有 echo、没有源码文本断言。

与 `tests/test_agent_api.py`（API 层协议/错误码/状态枚举/普通严格失败回滚）不重复：
这里只断言**跨层可观测的结果**——渲染出来的栅格真的移动了、受保护像素真的没变、
revision 真的不漂、以及「热会话说 OK、独立严格发布说不行」时提交门必须拒绝且一个字节都不落。
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / 'fixtures'

from figpact import geometry, science as science_mod  # noqa: E402
from figpact import session as session_mod  # noqa: E402
from figpact.patch import config_revision  # noqa: E402
from figpact.runtime import FigureWorker  # noqa: E402

PANELS = FIXTURES / 'native_panels.py'
PANELS_YAML = FIXTURES / 'native_panels.yaml'
MIXED = FIXTURES / 'native_mixed.py'
MIXED_YAML = FIXTURES / 'native_mixed.yaml'
NEGATIVES = FIXTURES / 'native_negatives.py'
NEGATIVES_YAML = FIXTURES / 'native_negatives.yaml'

TOL_GEOM_MM = 1e-6          # 向量几何数学（中心线/包围盒），不是文字栅格化精度
TOL_RASTER_MM = 0.2         # 栅格质心：像素级测量换算出毫米
GAP_START_MM = 6.0
GAP_TARGET_MM = 8.0
#: 负例夹具的标签抬升目标：基线 2.5，声明区间 [2.0, 6.0]。
NEGATIVES_LIFT_MM = 3.5


# ──────────────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────────────
def config_copy(tmp_path: Path, source: Path) -> Path:
    """正式 YAML 的临时副本：任何写盘都落在这份副本上。"""
    target = tmp_path / source.name
    shutil.copyfile(source, target)
    return target


def nodes_of(snapshot: dict) -> dict:
    return {n['gid']: n for n in (snapshot.get('nodes') or []) if n.get('gid')}


def relation_by_id(contract: dict, relation_id: str) -> dict:
    for rel in contract.get('relations') or []:
        if rel.get('id') == relation_id:
            return rel
    raise AssertionError(f'契约里没有关系 {relation_id!r}；实际有 '
                         f'{[r.get("id") for r in contract.get("relations") or []]}')


def measure(rel: dict, nodes: dict, *, tolerance_mm: float = TOL_GEOM_MM) -> dict:
    objects = [nodes[g] for g in rel['objects']]
    return geometry.measure_relation(rel['kind'], objects, axis=rel.get('axis') or 'x',
                                     anchor=rel.get('anchor'), method=None,
                                     tolerance_mm=tolerance_mm)


def raster_centroid_mm(png_b64: str, *, x_window_mm, band_mm, dpi: float) -> float:
    """渲染栅格里的内容横向质心（mm）：窗口内「暗度」按列加权的重心。"""
    image = plt.imread(io.BytesIO(base64.b64decode(png_b64)))
    dark = 1.0 - (image[..., :3].mean(axis=2) if image.ndim == 3 else image)
    height_px, width_px = dark.shape
    per_mm = dpi / 25.4
    x0 = max(0, int(round(x_window_mm[0] * per_mm)))
    x1 = min(width_px, int(round(x_window_mm[1] * per_mm)))
    # 栅格行 0 在顶部：把「从下往上」的毫米带换算成行区间。
    y0 = max(0, int(round(height_px - band_mm[1] * per_mm)))
    y1 = min(height_px, int(round(height_px - band_mm[0] * per_mm)))
    assert x1 > x0 and y1 > y0, '窗口落在画布之外'
    profile = dark[y0:y1, x0:x1].sum(axis=0)
    total = float(profile.sum())
    assert total > 0.0, '窗口内没有任何可见内容，无法测质心'
    index = np.arange(x0, x1, dtype=float)
    return float((profile * index).sum() / total) / per_mm


def build_package(tmp_path: Path, script: Path, extra: str = '') -> tuple[Path, Path]:
    """把夹具（含它的 tests 包）复制到临时目录，并按需追加临时副本专用的声明。

    追加只发生在**副本**上：正式夹具一个字节都不动。
    """
    package = tmp_path / 'pkg'
    fixture_dir = package / 'tests' / 'fixtures'
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (package / 'tests' / '__init__.py').write_text('', encoding='utf-8')
    yaml_name = script.with_suffix('.yaml').name
    for name in ('__init__.py', '_native.py', 'fixture_data.py', script.name, yaml_name):
        shutil.copyfile(FIXTURES / name, fixture_dir / name)
    copied_script = fixture_dir / script.name
    if extra:
        with copied_script.open('a', encoding='utf-8') as handle:
            handle.write('\n\n# ── 临时副本专用（正式夹具没有这些行）──\n' + extra.strip() + '\n')
    return copied_script, package


def run_cli(script: Path, config: Path, *, args: list, cwd: Path, timeout: int = 900):
    return subprocess.run([sys.executable, '-X', 'utf8', str(script), '--config', str(config), *args],
                          cwd=str(cwd), capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, env={**os.environ, 'MPLBACKEND': 'Agg'})


def require_runtime_surface():
    for name in ('declared_science_inputs', 'declared_output_stems', 'source_revision'):
        assert hasattr(session_mod, name), f'运行时没有暴露 {name}，输入 revision 契约不完整'


# ──────────────────────────────────────────────────────────────────────────────
# 1. 四联显微图：毫米缝隙落进真实栅格 + 受保护像素逐字节不变
# ──────────────────────────────────────────────────────────────────────────────
def test_panels_gap_lands_in_raster_and_protected_pixels_unchanged(tmp_path):
    panels = session_mod.load_module(PANELS, PANELS_YAML)
    config_path = config_copy(tmp_path, PANELS_YAML)
    base_config = panels.load_config(PANELS_YAML)
    contract = panels.layout_contract('main')
    gap_x = relation_by_id(contract, 'panels.gap_x_bottom')
    gap_y_left = relation_by_id(contract, 'panels.gap_y_left')

    worker = FigureWorker(PANELS, config_path, 'main')
    try:
        worker.open()
        base_nodes = nodes_of(worker.snapshot())
        base_measured = measure(gap_x, base_nodes)
        assert base_measured['status'] == 'OK', base_measured
        assert base_measured['value_mm'] == pytest.approx(GAP_START_MM, abs=TOL_GEOM_MM)
        base_gap_y = measure(gap_y_left, base_nodes)['value_mm']
        base_preview = worker.render_preview()

        result = worker.try_layout([{'operation': 'set_parameter', 'path': ['gap_x_mm'],
                                     'value': GAP_TARGET_MM}])
        assert result['status'] == 'OK', result
        after_nodes = nodes_of(worker.snapshot())
        after_measured = measure(gap_x, after_nodes)
        assert after_measured['value_mm'] == pytest.approx(GAP_TARGET_MM, abs=TOL_GEOM_MM), after_measured
        # 别的缝隙不许被顺手带走
        assert measure(gap_y_left, after_nodes)['value_mm'] == pytest.approx(base_gap_y, abs=TOL_GEOM_MM)
        candidate = worker.candidate_config
        assert float(candidate['gap_x_mm']) == pytest.approx(GAP_TARGET_MM)
        assert float(candidate['gap_y_mm']) == pytest.approx(float(base_config['gap_y_mm']))
        after_preview = worker.render_preview()
    finally:
        worker.close()

    # 真实栅格：右列整体右移 (8-6) mm，左列不动。
    # 两次分别取随面板移动的同一内容区域；固定交集会截掉不同内容并改变质心。
    margin_left = float(base_config['margin_left_mm'])
    panel_w = float(base_config['panel_w_mm'])
    panel_h = float(base_config['panel_h_mm'])
    margin_bottom = float(base_config['margin_bottom_mm'])
    dpi = float(base_config['render_dpi'])
    b_before_x0 = margin_left + panel_w + GAP_START_MM
    b_after_x0 = margin_left + panel_w + GAP_TARGET_MM
    before_window = (b_before_x0 + 0.5, b_before_x0 + panel_w - 0.5)
    after_window = (b_after_x0 + 0.5, b_after_x0 + panel_w - 0.5)
    band = (margin_bottom + panel_h * 0.2, margin_bottom + panel_h * 0.8)
    a_window = (margin_left + 2.0, margin_left + panel_w - 2.0)

    def centroid(preview, window):
        return raster_centroid_mm(preview['png'], x_window_mm=window, band_mm=band, dpi=dpi)

    b_shift = centroid(after_preview, after_window) - centroid(base_preview, before_window)
    a_shift = centroid(after_preview, a_window) - centroid(base_preview, a_window)
    assert b_shift == pytest.approx(GAP_TARGET_MM - GAP_START_MM, abs=TOL_RASTER_MM), (
        f'右列在栅格里的位移 {b_shift:.4f} mm，期望 {GAP_TARGET_MM - GAP_START_MM:.4f} mm')
    assert a_shift == pytest.approx(0.0, abs=0.05), f'左列不该动，实测 {a_shift:.4f} mm'

    # 受保护像素：绘图数组就是固定种子生成的那一个数组（同一对象、逐字节相等）。
    from tests.fixtures import fixture_data
    science = panels.load_science()
    fig_after, registry_after = panels.build_scene(science, candidate, 'main')
    try:
        for pid in ('a', 'b', 'c', 'd'):
            artist = registry_after.get(f'fig_panels_native.main.image.{pid}')
            assert artist is not None, f'缺面板 {pid} 的显微图'
            protected = np.asarray(fixture_data.micrograph(pid))
            drawn = np.asarray(artist.get_array())
            assert drawn.shape == protected.shape, f'面板 {pid} 形状被改：{drawn.shape}'
            assert np.array_equal(drawn, protected), f'面板 {pid} 像素被改写'
        capture_after = science_mod.capture_science(
            fig_after, registry_after, declarations=panels.science_manifest(science))
    finally:
        plt.close(fig_after)

    fig_before, registry_before = panels.build_scene(science, panels.load_config(PANELS_YAML), 'main')
    try:
        capture_before = science_mod.capture_science(
            fig_before, registry_before, declarations=panels.science_manifest(science))
    finally:
        plt.close(fig_before)
    diagnostics = science_mod.compare_science(capture_before, capture_after, label='（面板缝隙 6→8mm）')
    assert diagnostics == [], diagnostics
    assert capture_after['digest'] == capture_before['digest']


# ──────────────────────────────────────────────────────────────────────────────
# 2. 混排夹具：revision 不漂移、预览确定、科学载荷跨层等值
# ──────────────────────────────────────────────────────────────────────────────
def test_mixed_revision_is_stable_and_science_payload_survives_layout_change(tmp_path):
    session_mod.load_module(MIXED, MIXED_YAML)
    config_path = config_copy(tmp_path, MIXED_YAML)
    operations = [{'operation': 'set_parameter', 'path': ['curve_lift_mm'], 'value': 0.8}]

    worker = FigureWorker(MIXED, config_path, 'main')
    try:
        opened = worker.open()
        base_revision = worker.revision
        assert worker.base_config_revision == config_revision(config_path)
        assert opened['base_config_revision'] == config_revision(config_path)
        base_preview = worker.render_preview()

        first = worker.try_layout(operations)
        assert first['status'] == 'OK', first
        assert first['revision'] == worker.revision
        second = worker.try_layout(operations)
        assert second['status'] == 'OK', second
        assert second['revision'] == first['revision'], '同一组绝对目标必须得到同一个 revision'
        assert worker.candidate_patch == {'curve_lift_mm': 0.8}, worker.candidate_patch
        base_config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        candidate = worker.candidate_config
        differing = sorted(k for k in set(base_config) | set(candidate)
                           if base_config.get(k) != candidate.get(k))
        assert differing == ['curve_lift_mm'], differing
        assert candidate['curve_lift_mm'] == pytest.approx(0.8)

        preview_1 = worker.render_preview()
        preview_2 = worker.render_preview()
        assert preview_1['revision'] == first['revision']
        assert preview_1['png'] == preview_2['png'], '同一 revision 的预览必须逐字节确定'
        assert preview_2['cached'] is True and preview_1['cached'] is False

        # 纯显示位移不改受保护载荷：曲线数组、像素、窗口、声明都必须与基线逐字节一致
        base_objects = base_preview['science']['objects']
        moved_objects = preview_1['science']['objects']
        assert moved_objects['fig_mixed_native.main.curve.a']['x'] == \
            base_objects['fig_mixed_native.main.curve.a']['x'], '显示位移不该改 x 数组'
        assert moved_objects['fig_mixed_native.main.curve.a']['y'] == \
            base_objects['fig_mixed_native.main.curve.a']['y'], '显示位移不该改 y 数组'
        assert moved_objects['fig_mixed_native.main.image']['pixels']['digest'] == \
            base_objects['fig_mixed_native.main.image']['pixels']['digest'], '显示位移不该改显微图像素'
        assert science_mod.compare_science(base_preview['science'], preview_1['science']) == []

        curve_id = 'fig_mixed_native.main.curve.a'
        bounds_before_stale = nodes_of(worker.snapshot())[curve_id]['bounds_mm']
        stale = worker.try_layout([{'operation': 'set_parameter', 'path': ['curve_lift_mm'],
                                    'value': 1.6}], revision='0' * 64)
        assert stale['status'] == 'STALE_REVISION', stale
        assert worker.revision == first['revision']
        assert nodes_of(worker.snapshot())[curve_id]['bounds_mm'] == bounds_before_stale
    finally:
        worker.close()

    fresh = FigureWorker(MIXED, config_path, 'main')
    try:
        fresh.open()
        assert fresh.revision == base_revision, '新进程重开同一份配置必须回到同一个基线 revision'
        assert fresh.has_candidate is False
        assert fresh.candidate_patch == {}
    finally:
        fresh.close()

    # 正式夹具的配置一个字节都没动
    assert config_path.read_bytes() == MIXED_YAML.read_bytes()


# ──────────────────────────────────────────────────────────────────────────────
# 3. 作用域隔离：bare 不画字母、拒收别的作用域与不可编辑的字母旋钮，也不污染 main
# ──────────────────────────────────────────────────────────────────────────────
def test_scope_isolation_bare_has_no_letters(tmp_path):
    mixed = session_mod.load_module(MIXED, MIXED_YAML)
    config_path = config_copy(tmp_path, MIXED_YAML)
    config_bytes = config_path.read_bytes()

    bare_worker = FigureWorker(MIXED, config_path, 'bare')
    try:
        bare_worker.open()
        bare_gids = set(nodes_of(bare_worker.snapshot()))
        assert not [g for g in bare_gids if '.letter.' in g], sorted(g for g in bare_gids if 'letter' in g)

        # bare 没有可编辑的字母内缩绑定：未知路径或外作用域都必须明确拒绝且不改状态。
        out_of_scope = bare_worker.try_layout([{'operation': 'set_parameter',
                                                'path': ['letter_inset_x_mm'], 'value': 3.0}])
        assert out_of_scope['status'] in ('NOT_IN_SCOPE', 'UNSUPPORTED_PATH'), out_of_scope
        # bare 自己声明的字母字号是 FIXED_STYLE：同样拒绝，不生成候选、不留下字母
        fixed_style = bare_worker.try_layout([{'operation': 'set_parameter',
                                               'path': ['letter_font_pt'], 'value': 9.0}])
        assert fixed_style['status'] == 'FIXED_STYLE', fixed_style
        assert bare_worker.has_candidate is False, bare_worker.candidate_patch
        assert bare_worker.candidate_patch == {}
        assert not [g for g in nodes_of(bare_worker.snapshot()) if '.letter.' in g]
    finally:
        bare_worker.close()

    assert config_path.read_bytes() == config_bytes, '拒绝路径不得写回配置'

    main_worker = FigureWorker(MIXED, config_path, 'main')
    try:
        main_worker.open()
        main_gids = set(nodes_of(main_worker.snapshot()))
        assert sorted(g for g in main_gids if '.letter.' in g), 'main 应当真的画出字母'
        assert 'fig_mixed_native.main.image' in main_gids and 'fig_mixed_native.main.curve.a' in main_gids
        # 反向隔离：bare 的两次拒绝没有污染 main，同一条字母参数在 main 里照常可编辑
        moved = main_worker.try_layout([{'operation': 'set_parameter',
                                         'path': ['letter_inset_x_mm'], 'value': 3.0}])
        assert moved['status'] == 'OK', moved
    finally:
        main_worker.close()


# ──────────────────────────────────────────────────────────────────────────────
# 4. 独立严格门是事务：真实的负例夹具必然被拒、一个字节都不落；热会话说 OK 也不行
# ──────────────────────────────────────────────────────────────────────────────
def test_independent_strict_failure_is_transactional(tmp_path):
    """负例夹具的缺陷是写进去的（main 隐藏科学改写 / annotated 文本碰撞）。

    独立严格门必须真的拒绝它；同一份候选在热会话里判 OK，提交门仍然不许落地。
    """
    from figpact import agent_api
    config = config_copy(tmp_path, NEGATIVES_YAML)
    config_bytes = config.read_bytes()

    # 真实 CLI（独立进程、独立严格门）：拒绝发布，沙箱里一个产物都不留
    probe = tmp_path / 'probe'
    probe.mkdir()
    run = run_cli(NEGATIVES, config, args=['--strict', '--probe', str(probe)], cwd=NEGATIVES.parent)
    assert run.returncode != 0, run.stdout
    assert [p.name for p in probe.iterdir()] == [], list(probe.iterdir())

    # 同一份候选在热会话里是 OK 的（会话只测声明落实，不跑夹具自己的科学自检）
    out_dir = tmp_path / 'official'
    out_dir.mkdir()
    sentinel = out_dir / 'fig_negatives_native_main.png'
    sentinel.write_bytes(b'pre-existing-official-bytes')

    session_obj = agent_api.AgentSession(NEGATIVES, config, 'main', output_dir=out_dir)
    try:
        result = session_obj.try_layout([{'operation': 'set_parameter', 'path': ['label_lift_mm'],
                                          'value': NEGATIVES_LIFT_MM}])
        assert result['status'] == 'OK', result
        with pytest.raises(agent_api.AgentError) as excinfo:
            session_obj.commit('publication', confirm=True)
        assert excinfo.value.code == agent_api.COMMIT_REJECTED, excinfo.value.to_error()
        assert excinfo.value.data.get('returncode') not in (0, None), excinfo.value.data
    finally:
        session_obj.close()

    assert sentinel.read_bytes() == b'pre-existing-official-bytes', '严格失败不得覆盖正式产物'
    assert sorted(p.name for p in out_dir.iterdir()) == [sentinel.name]
    assert config.read_bytes() == config_bytes, '严格失败不得写回配置'


# ──────────────────────────────────────────────────────────────────────────────
# 5. 声明的科学输入：扩展名像产物也要算数，精确声明的产物要排除，缺失要报错
# ──────────────────────────────────────────────────────────────────────────────
SCIENCE_INPUTS_PATCH = """
from pathlib import Path as _Path

SCIENCE_INPUTS = (_Path(__file__).with_name("input_micrograph.png"),)


def science_inputs():
    return SCIENCE_INPUTS
"""


def _write_real_png(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(0.6, 0.5), dpi=60)
    ax.imshow(np.arange(30 * 36, dtype=np.uint8).reshape(30, 36), interpolation='nearest')
    ax.set_axis_off()
    fig.savefig(path, format='png')
    plt.close(fig)
    assert path.is_file() and path.stat().st_size > 0


def test_artifact_shaped_science_input_is_required_and_invalidates(tmp_path, monkeypatch):
    require_runtime_surface()
    script, package = build_package(tmp_path, PANELS, SCIENCE_INPUTS_PATCH)
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(
        [str(ROOT)] + ([os.environ['PYTHONPATH']] if os.environ.get('PYTHONPATH') else [])))
    fixture_dir = script.parent
    config = fixture_dir / PANELS_YAML.name
    input_path = fixture_dir / 'input_micrograph.png'
    _write_real_png(input_path)
    artifact = fixture_dir / 'fig_panels_native_main.png'
    artifact.write_bytes(b'declared-official-artifact')

    module = session_mod.load_module(script, config)
    declared = session_mod.declared_science_inputs(module)
    assert [str(Path(p).resolve()) for p in declared] == [str(input_path.resolve())]
    contract = module.layout_contract('main')
    outputs = session_mod.declared_output_stems(contract, script)
    assert str(artifact.resolve()) in {str(Path(p).resolve()) for p in outputs}

    def revision() -> str:
        return session_mod.source_revision(script, config, exclude=outputs, required=declared)

    base = revision()
    artifact.write_bytes(artifact.read_bytes() + b'x')
    assert revision() == base, '精确声明的正式产物被排除，改它的字节不该动输入 revision'
    input_path.write_bytes(input_path.read_bytes() + b'\n')
    assert revision() != base, '声明的科学输入（哪怕扩展名像产物）必须算进输入 revision'

    # 源文件缺失是显式错误，不是被静默丢弃
    input_path.unlink()
    with pytest.raises(session_mod.SessionError):
        session_mod.declared_science_inputs(module)

    # worker 侧：源文件变了 → 热候选作废
    _write_real_png(input_path)
    worker = FigureWorker(script, config, 'main')
    try:
        opened = worker.open()
        state = worker.state()
        if 'science_inputs' in state:
            assert str(input_path.resolve()) in {str(Path(p).resolve())
                                                 for p in state['science_inputs']}
        if 'artifact_outputs' in state:
            assert str(artifact.resolve()) in {str(Path(p).resolve())
                                               for p in state['artifact_outputs']}
        revision_before = state.get('source_revision', opened.get('source_revision'))
        result = worker.try_layout([{'operation': 'set_parameter', 'path': ['gap_x_mm'],
                                     'value': GAP_TARGET_MM}])
        assert result['status'] == 'OK', result
        input_path.write_bytes(input_path.read_bytes() + b'\n')
        worker.render_preview()  # 同步：这一步必须发现源变了
        after = worker.state()
        assert after['has_candidate'] is False, after
        assert revision_before is not None
        assert after['source_revision'] != revision_before, '源文件内容变了，输入 revision 必须变'
    finally:
        worker.close()
