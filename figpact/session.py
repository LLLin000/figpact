"""热会话：一次导入、一次装载科学数据、候选图从基线配置派生。

P2 运行时核心。会话**从不落盘**：严格发布由父模块的 commit 通道把关。

设计要点（对应验收项）：
- 候选永远是「基线配置 + 累积的绝对目标」，不是「在旧图上再叠一次位移」；
  因此重复的绝对值、撤销/重做都不会漂移，同一组目标必然得到同一个 revision。
- 纯显示刚体位移只在**声明**为 translate、且该声明已被真实 YAML 重建扰动证明过
  （见 `_prove_translation`）时，才走不渲染的几何快车道；其余一律warm重建 + 完整 QA。
- 未声明/未分类/锁定/越界/矛盾/歧义一律显式拒绝，不做静默 no-op。
- 声明与实测**不符**（错标尺、错绑定、没接线、牵连未声明对象）是**观测到的事实**，
  不是「测不了」：一律明确拒绝（EFFECT_MISMATCH / NO_EFFECT），绝不退回渲染验证后给 OK。
  只有「同渲染器解析容差证明不了」这一种情况才合法退回渲染，且退回后仍要在**真实重建**
  的候选上核对声明的作用集合、单位换算与关系目标。
- 核心模块 `figpact.contracts` / `figpact.science` / `figpact.scene` 是**前置条件**：
  缺了就报错，绝不降级成「未验证但接受」的候选。
"""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
import json
import math
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from figpact.registry import GidRegistry
from figpact.units import MM_PER_INCH
from figpact.geometry import figure_image_bbox

#: 状态字面量（会话与 CLI/agent_api 的共同词表）。
STATUS_OK = 'OK'
STATUS_STALE = 'STALE_REVISION'
STATUS_UNSUPPORTED_PATH = 'UNSUPPORTED_PATH'
STATUS_UNCLASSIFIED = 'UNCLASSIFIED'
STATUS_NOT_IN_SCOPE = 'NOT_IN_SCOPE'
STATUS_LOCKED = 'LOCKED'
STATUS_FIXED_STYLE = 'FIXED_STYLE'
STATUS_DERIVED = 'DERIVED'
STATUS_OUT_OF_RANGE = 'OUT_OF_RANGE'
STATUS_INVALID_VALUE = 'INVALID_VALUE'
STATUS_CONTRADICTORY = 'CONTRADICTORY'
STATUS_AMBIGUOUS = 'AMBIGUOUS'
STATUS_UNKNOWN_RELATION = 'UNKNOWN_RELATION'
STATUS_UNSUPPORTED_RELATION = 'UNSUPPORTED_RELATION'
#: 声明与**实测**不符：真实重建里观察到的作用集合/轴/物理量/科学指纹与声明不一致。
STATUS_EFFECT_MISMATCH = 'EFFECT_MISMATCH'
#: 声明了却**没有任何可测效果**（没接线、值被忽略、或恰好等于基线的 no-op）。
STATUS_NO_EFFECT = 'NO_EFFECT'
#: 声明的种类无法用同渲染器解析容差证明（缺 axis、对象不可测、扰动量过小……）。
#: 这不是「证明声明没问题」，只是「证明不了」——退回渲染验证，且退回后仍要观测声明落实。
STATUS_UNSUPPORTED_PROOF = 'UNSUPPORTED_PROOF'
#: `_prove_translation` 的分类：只有 `PROVED` 能走几何快车道；
#: `UNSUPPORTED` 是「证明不了」（合法退回渲染验证，但不许据此给成功）；
#: `OBSERVED_*` 是真实重建里**观测到的否证**，必须明确拒绝。
PROOF_PROVED = 'PROVED'
PROOF_UNSUPPORTED = 'UNSUPPORTED'
PROOF_OBSERVED_MISMATCH = 'OBSERVED_MISMATCH'
PROOF_OBSERVED_NO_EFFECT = 'OBSERVED_NO_EFFECT'
STATUS_GEOMETRY_REJECTED = 'GEOMETRY_REJECTED'
STATUS_SCIENCE_VIOLATION = 'SCIENCE_VIOLATION'
STATUS_QA_BLOCKED = 'QA_BLOCKED'
STATUS_BUILD_FAILED = 'BUILD_FAILED'
STATUS_ERROR = 'ERROR'
STATUS_UNDECLARED = 'UNDECLARED_PARAMETER'

VERIFICATION_GEOMETRY = 'GEOMETRY_CHECKED'
VERIFICATION_RENDER = 'RENDER_CHECKED'

#: 几何测量容差（mm），分两种语义，绝不混用：
#: - `TOL_SAME_RENDERER_MM`：**同一构建、同一 DPI、同一字体**下的纯显示位移容差。
#:   ScaledTranslation 把整块显示几何平移 (dx,dy) mm，包围盒/折线是解析位移；
#:   实测（figpact 探针夹具，dpi 100/120/300）折线与同 DPI 文本包络都是 1e-9 级别，
#:   所以这里只留 1 µm 浮点余量。证明物理位移只能用这个。
#: - `TOL_ENVELOPE_MM_PER_PX`：跨构建/跨 DPI 的文本栅格化不确定度，**未标定**，
#:   只用于回答「有没有变」，绝不用于证明位移量。
TOL_SAME_RENDERER_MM = 1e-3
TOL_ENVELOPE_MM_PER_PX = 1.6
#: 证明位移声明所需的最小可测物理增量（mm）。
MIN_PROBE_MM = 0.25
#: 样式数值（字号、线宽……）的比较容差。
_STYLE_TOL = 1e-9

EDITABLE = 'EDITABLE'
LOCKED_SCIENCE = 'LOCKED_SCIENCE'
FIXED_STYLE = 'FIXED_STYLE'
DERIVED = 'DERIVED'
UNCLASSIFIED = 'UNCLASSIFIED'

_OPERATIONS = ('translate', 'rebuild', 'resize')
_SCIENCE_TOL = 1e-9


class SessionError(RuntimeError):
    """会话层错误。"""


class StaleRevision(SessionError):
    """调用方持有的 revision 已经不是当前候选。"""


class ContractError(SessionError):
    """布局契约声明本身不可用（缺字段、重复 path、作用域外）。"""


# --------------------------------------------------------------------------- #
# 源指纹与模块装载
# --------------------------------------------------------------------------- #

def _runtime_noise_path(path) -> bool:
    """运行时可识别的临时物/工作目录/缓存，不参与源身份；按路径身份，不按后缀。"""
    parts = path.parts
    if '__pycache__' in parts or path.suffix.lower() == '.pyc':
        return True
    name = path.name
    if name.startswith('.figpact-') or name.startswith('.tmp_'):
        return True
    for part in parts:
        if '-stage-' in part or part.endswith('-stage') or part.endswith('_stage'):
            return True
    return False


def _file_content_hash(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def script_fingerprint(script, config=None, *, exclude=(), required=()) -> str:
    """脚本目录的**源码内容**指纹（排掉配置本身）。

    身份以文件内容 SHA-256 为准，不使用 size/mtime。只按精确声明的产物路径排除；
    `.png/.json/.pdf` 仍可能是科学输入。运行时临时物与 stage 目录按路径身份排除。
    """
    script = Path(script).resolve()
    config = Path(config).resolve() if config else None
    skip = {Path(p).resolve() for p in exclude} - {Path(p).resolve() for p in required}
    h = hashlib.sha256()
    for p in sorted(script.parent.rglob('*')):
        if not p.is_file() or _runtime_noise_path(p):
            continue
        resolved = p.resolve()
        if resolved in skip:
            continue
        if resolved in {Path(x).resolve() for x in required}:
            pass
        if config is not None and resolved == config and resolved not in skip:
            continue
        digest = _file_content_hash(p)
        h.update(f'{resolved}:{digest}'.encode('utf-8'))
    for p in sorted(required):
        path = Path(p)
        if path.is_file():
            digest = _file_content_hash(path)
            h.update(f'{path.resolve()}:{digest}'.encode('utf-8'))
    for p in sorted(script.parent.rglob('*')):
        pass
    return h.hexdigest()

    return h.hexdigest()

def engine_fingerprint() -> str:
    """引擎自身实现（figpact/*.py）的内容指纹。"""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.rglob('*')):
        if not p.is_file() or _runtime_noise_path(p):
            continue
        digest = _file_content_hash(p)
        h.update(f'{p.resolve()}:{digest}'.encode('utf-8'))
    return h.hexdigest()


def declared_science_inputs(module) -> list[str]:
    """合并两种显式声明；空的 SCIENCE_INPUTS 不能屏蔽 science_inputs()。"""
    sources = [getattr(module, 'SCIENCE_INPUTS', None)]
    hook = getattr(module, 'science_inputs', None)
    if callable(hook):
        sources.append(hook())
    base = Path(getattr(module, '__file__', '.')).resolve().parent
    out, missing = [], []
    for raw in sources:
        if raw is None:
            continue
        if isinstance(raw, (str, Path)):
            raw = [raw]
        for item in raw:
            path = Path(item)
            resolved = (path if path.is_absolute() else base / path).resolve()
            if not resolved.is_file():
                missing.append(str(resolved))
            out.append(str(resolved))
    if missing:
        raise SessionError(f'SCIENCE_INPUTS 声明的科学输入不存在：{missing}（声明即须在场，不许静默丢弃）')
    return sorted(set(out))


def declared_output_stems(contract, script) -> list[str]:
    """契约 outputs（相对产物文件名）解析成绝对路径。"""
    base = Path(script).resolve().parent
    out = []
    for name in (contract or {}).get('outputs') or []:
        path = Path(name)
        out.append(str((path if path.is_absolute() else base / path).resolve()))
    return sorted(set(out))


def module_revision(script, config, *, exclude=(), required=()) -> str:
    """**模块/资产**指纹：脚本目录（排掉配置与声明的产物）+ 声明的科学输入 + 引擎实现。

    配置字节**不在**这里面：YAML 变更只重基线，不重导模块、不重装科学对象。
    脚本/助手/科学输入/引擎实现改了才变——这才是「要不要换进程/重导模块」的依据。
    """
    h = hashlib.sha256()
    h.update(script_fingerprint(script, config, exclude=exclude,
                                required=required).encode('utf-8'))
    h.update(engine_fingerprint().encode('utf-8'))
    return h.hexdigest()


def source_revision(script, config, *, exclude=(), required=()) -> str:
    """配置字节 + 模块/资产指纹的合指纹（对外可见的**总修订**）。

    配置、脚本（或其数据源/声明的科学输入）、引擎实现改动 → 指纹变化 → 缓存失效，
    绝不拿陈旧结果糊弄。只由精确声明的产物路径排除（不是按后缀）。
    """
    config = Path(config).resolve()
    h = hashlib.sha256(config.read_bytes())
    h.update(module_revision(script, config, exclude=exclude, required=required).encode('utf-8'))
    return h.hexdigest()


_LOAD_COUNTER = [0]
#: 真实调用 load_science 的次数（缓存命中不算）：热会话没有偷偷重装科学对象的证据。
_SCIENCE_LOADS = [0]
#: 进程内的模块/科学对象缓存：原生脚本按源码指纹复用，脚本改了立刻重来。
_MODULE_CACHE: dict[str, tuple] = {}
_SCIENCE_CACHE: dict[str, tuple] = {}


def loader_counters() -> dict:
    """进程内的真实装载计数与缓存规模（会话/工作者状态里如实报出来）。"""
    return {'module_loads': _LOAD_COUNTER[0], 'science_loads': _SCIENCE_LOADS[0],
            'module_cache': len(_MODULE_CACHE), 'science_cache': len(_SCIENCE_CACHE)}


def pristine_rc() -> dict:
    """调用时全局 rc 的快照（除 backend 外全部键）：构建期看到的隔离基线。

    构建在与调用时相同的 rc 环境下进行（字体/dpi 不变），`rc_context`
    退出时把全局还原——只隔离副作用，不改变输入。
    只剔 `backend`——它是哨兵对象而非可验证值，进不了 `rc_context`。
    """
    import copy
    import matplotlib as mpl
    return {key: copy.deepcopy(value) for key, value in dict(mpl.rcParams).items()
            if key != 'backend'}


def exec_module_isolated(spec, module, *, argv):
    """装载绘图脚本：导入期的 `figure_style.apply()` 只污染隔离区。

    调用方的全局 rcParams 原样保留；导入期改掉的 rc 记在模块的
    `__figpact_import_rc__` 上（构建期由 `FigureSession._call_builder` 叠加）。
    隔离导入不写字节码缓存：`sys.dont_write_bytecode` 只在此调用内为 True，
    退出（包括异常路径）即恢复——不留 `__pycache__`。
    """
    old_argv = sys.argv
    old_dont_write = sys.dont_write_bytecode
    sys.argv = list(argv)
    sys.dont_write_bytecode = True
    try:
        import matplotlib as mpl
        entry = pristine_rc()
        with mpl.rc_context(rc=entry):
            with redirect_stdout(io.StringIO()):
                spec.loader.exec_module(module)
            # 导入期改掉的 rc（字体/dpi……）是脚本声明的环境：记在模块上，
            # 每次构建重新叠加；全局退出即还原，不外泄。
            overlay = {}
            for key, value in dict(mpl.rcParams).items():
                if key == 'backend':
                    continue
                try:
                    same = key in entry and bool(entry[key] == value)
                except Exception:
                    same = False
                if not same:
                    overlay[key] = copy.deepcopy(value)
            module.__figpact_import_rc__ = overlay
    finally:
        sys.argv = old_argv
        sys.dont_write_bytecode = old_dont_write
    return module


def load_module(script, config, *, module_name=None):
    """按路径装载绘图脚本的**定义**：一次导入，不建 Figure、不打印。

    导入在调用时 rc 快照下隔离执行：脚本导入期的 `figure_style.apply()` 只污染
    隔离区，退出即还原——调用方的全局 rcParams 不会被改掉。
    隔离导入不写字节码缓存（`__pycache__`）：`sys.dont_write_bytecode` 只在导入
    期为 True，退出即恢复；不删调用方既有缓存。
    旧模块会被同目录下的新模块替换掉（源码改动后重载不会串味）。
    """
    script = Path(script).resolve()
    parent = str(script.parent)
    sys.path.insert(0, parent)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    _LOAD_COUNTER[0] += 1
    name = module_name or f'figpact_plot_{_LOAD_COUNTER[0]}'
    stale = [k for k, m in list(sys.modules.items())
             if getattr(m, '__file__', None) and Path(m.__file__).parent == Path(parent)
             and k not in ('__init__', 'figpact')]
    for k in stale:
        sys.modules.pop(k, None)
    sys.modules.pop('figure_style', None)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise SessionError(f'无法为脚本创建 loader：{script}')
    mod = importlib.util.module_from_spec(spec)
    exec_module_isolated(spec, mod,
                         argv=[str(script), '--config', str(Path(config).resolve()),
                               '--inventory'])
    sys.modules[name] = mod
    return mod


def load_module_cached(script, config):
    """装载脚本模块；**只对原生脚本**按源码指纹复用同一个模块对象。

    旧的/未声明原生接缝的脚本每次重新导入：它们的模块级全局可能是从配置读来的，
    复用会串味。原生接缝的约定是「导入不解析 argv、build_scene 从传入 config 重建全部布局全局」。
    """
    script_p = Path(script).resolve()
    key = str(script_p)
    if key in _MODULE_CACHE:
        entry = _MODULE_CACHE[key]
        if entry[0] == script_fingerprint(script_p, config):
            return entry[1]
    module = load_module(script_p, config)
    if callable(getattr(module, 'build_scene', None)):
        # 指纹在**导入之后**才取：脚本导入期写出的文件不会让下一次比较永远不相等。
        _MODULE_CACHE[key] = (script_fingerprint(script_p, config), module)
    return module


def _accepts(func, param: str) -> bool:
    import inspect
    try:
        return param in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# 精确路径读写（与父模块 contracts 的路径语义一致；参数目录/校验由父模块提供）
# --------------------------------------------------------------------------- #

def _core_module(name):
    """核心模块（`contracts` / `science` / `scene`）是**前置条件**，不是可选项。

    集成的引擎一定带这三个模块；缺了就是环境/打包错误，必须报错——
    绝不退回「跳过校验」或「科学未验证」的降级路径，那等于把未经观测的候选
    当成功接受。
    """
    try:
        return importlib.import_module(f'figpact.{name}')
    except Exception as error:  # pragma: no cover - 集成引擎总是带这三个模块
        raise SessionError(
            f'缺少核心模块 figpact.{name}（{error}），无法给出经验证的结论') from error


def get_path(data, path):
    cur = data
    for seg in path:
        if isinstance(cur, dict):
            if seg in cur:
                cur = cur[seg]
                continue
            match = [k for k in cur if str(k) == str(seg)]
            if len(match) != 1:
                raise KeyError(f'路径不存在：{list(path)}')
            cur = cur[match[0]]
        elif isinstance(cur, (list, tuple)) and isinstance(seg, int):
            cur = cur[seg]
        else:
            raise KeyError(f'路径不存在：{list(path)}')
    return cur


def set_path(data, path, value):
    """按精确路径写值；父节点缺失即报错（不擅自造中间层）。"""
    if not path:
        raise ValueError('路径不能为空')
    cur = get_path(data, path[:-1]) if len(path) > 1 else data
    last = path[-1]
    if isinstance(cur, dict):
        match = [k for k in cur if str(k) == str(last)]
        if not match:
            raise KeyError(f'路径不存在：{list(path)}')
        cur[match[0]] = value
    elif isinstance(cur, list) and isinstance(last, int):
        cur[last] = value
    else:
        raise KeyError(f'路径不可写：{list(path)}')
    return data


def _norm_path(path) -> tuple:
    if isinstance(path, (str, bytes)):
        raise ValueError('path 必须是键段列表，不能是点分字符串')
    if not isinstance(path, (list, tuple)) or not path:
        raise ValueError('path 必须是非空键段列表')
    return tuple(str(seg) for seg in path)


def _finite(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{what} 必须是有限数字，得到 {value!r}')
    num = float(value)
    if not math.isfinite(num):
        raise ValueError(f'{what} 不能是 NaN 或 Inf')
    return num


def _pair_of(value):
    """把值读成 `[dx, dy]` 这对有限数字；不是这个形状返回 None。

    这是 2D 布局目标**唯一**允许的序列形状：恰好两个分量、每个都是有限数字
    （bool 不算数字、NaN/Inf 不算）。嵌套序列、映射、任意长度一律不是。
    """
    if isinstance(value, (str, bytes, dict)) or not isinstance(value, (list, tuple)):
        return None
    if len(value) != 2:
        return None
    out = []
    for index, item in enumerate(value):
        try:
            out.append(_finite(item, f'第 {index} 个分量'))
        except ValueError:
            return None
    return out


def _json_native(value):
    """报告里只放 JSON 原生标量。

    numpy 的 `float64` 是 `float` 的子类（能序列化，但类型不干净），`bool_` 连子类都不是
    （`json.dumps` 直接抛 `Object of type bool is not JSON serializable`）。两种都在**产出
    报告的地方**收敛成原生类型——不给序列化器加 `default=` 兜底，那样会把非原生值悄悄变成
    字符串，报告就不是机器可读的数字/布尔了。
    """
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, int):
        return int(value)
    item = getattr(value, 'item', None)  # 其余 numpy 标量（bool_/int64/…）
    if not callable(item):
        return value
    try:
        return _json_native(item())
    except Exception:  # 多元素数组没有裸标量：原样返回，别假装它是数字
        return value


# --------------------------------------------------------------------------- #
# 显示几何测量（mm，画布左下原点）
# --------------------------------------------------------------------------- #

def _rect_mm(fig, scale, height_px, bbox):
    """matplotlib 显示坐标本来就是左下原点，mm = px * scale，不再翻转。

    **显式转成 Python float**：matplotlib 的包围盒坐标是 `numpy.float64`，直接流进报告会让
    「机器可读的 JSON」带上非原生标量（`numpy.bool_` 更是连 `json.dumps` 都过不去）。
    """
    return [float(bbox.x0) * scale, float(bbox.y0) * scale,
            float(bbox.x1) * scale, float(bbox.y1) * scale]


def _points_mm(scale, height_px, xy):
    return [(float(x) * scale, float(y) * scale) for x, y in xy]


def _line_points(line):
    try:
        data = line.get_xydata()
        if len(data) == 0:
            return None
        return line.get_transform().transform(data)
    except Exception:
        return None




def _canvas_bounds(shapes):
    """显示几何里的画布容器包围盒（mm）；没有画布记录返回 None。"""
    for rec in shapes.values():
        if rec.get('kind') == 'canvas':
            return rec.get('bbox_mm')
    return None


def drawn_shapes(fig, registry=None, *, include_frames=False):
    """当前图上**实际画出来**的显示几何（mm）：折线、包络、坐标框、图幅图像。

    注册过的图元按 gid 记名；未注册的按「轴序号 + 类型 + 该类型内序号」记名，
    两次同样结构的构建之间键是稳定可比的。坐标框（axes frame）默认单独归类，
    只用于包含性判断，不参与碰撞；`include_frames` 还会记一条画布（figure 包围盒）
    容器，它是 contain 关系里的 canvas、也是所有可见几何的最终外边界。

    图幅图像（`fig.figimage`，不挂任何坐标轴）按它真实的**未裁切**图幅像素几何记一条，
    量不出来（没有数组 / 偏移不是有限数）**失败关闭**抛错：不用那个恒为空的包围盒冒充几何，
    也不默默跳过 —— 跳过等于告诉包含性与碰撞「这里什么都没有」。

    `get_visible()` 为真**不等于**被画出来：`ax.set_axis_off()` 之后刻度标签与轴标题
    仍是可见属性为真、却一个像素都不画——那些潜伏对象不进测量（否则它们会以
    「未声明几何发生变化」的样子污染扰动证据）。每条记录带 `clipped`，表示该图元
    是否真的被坐标框裁切（裁切边界与「画在坐标框外」是两回事：轴标题/图例/注释
    本来就可以画在框外）。
    """
    fig.canvas.draw()
    try:
        renderer = fig.canvas.get_renderer()
    except Exception as error:
        raise SessionError(f'渲染器不可用，无法测量显示几何：{error}') from error
    if renderer is None:
        raise SessionError('渲染器不可用，无法测量显示几何')

    dpi = float(fig.dpi)
    scale = MM_PER_INCH / dpi
    height_px = float(fig.bbox.height)
    out: dict[str, dict] = {}

    def key(gid, ax_idx, kind, index):
        return f'gid:{gid}' if gid else f'{ax_idx}:{kind}:{index}'

    def add(gid, ax_idx, kind, index, *, bbox=None, points=None, text=None, clipped=False):
        rec = {'gid': gid, 'axes': ax_idx, 'kind': kind, 'dpi': dpi, 'clipped': bool(clipped),
               'bbox_mm': _rect_mm(fig, scale, height_px, bbox) if bbox is not None else None,
               'points_mm': _points_mm(scale, height_px, points) if points is not None else None,
               'text': text}
        if rec['bbox_mm'] is None and points is not None and len(points):
            xs = [p[0] for p in rec['points_mm']]
            ys = [p[1] for p in rec['points_mm']]
            rec['bbox_mm'] = [min(xs), min(ys), max(xs), max(ys)]
        if rec['bbox_mm'] is None:
            return
        out[key(gid, ax_idx, kind, index)] = rec

    if include_frames and fig.patch is not None:
        # 画布（figure patch）是**作者声明的容器**：contain 关系里的 canvas 节点就注册在它身上。
        # 它是所有可见几何的最终外边界，量的直接是 fig.bbox（画布物理包围盒），不需要渲染器。
        canvas_gid = fig.patch.get_gid()
        out[key(canvas_gid, None, 'canvas', 0)] = {
            'gid': canvas_gid, 'axes': None, 'kind': 'canvas', 'dpi': dpi,
            'bbox_mm': _rect_mm(fig, scale, height_px, fig.bbox),
            'points_mm': None, 'text': None, 'container': True}

    for ax_idx, ax in enumerate(fig.axes):
        # 整根轴不画（`ax.set_axis_off()` / `axis.set_visible(False)`）时，刻度标签与轴标题
        # 的 `get_visible()` 仍然是 True，却一个像素都不画：那是潜伏对象，不是显示几何，
        # 不能拿它们的包围盒当「可见变化 / 碰撞」证据。
        axison = bool(getattr(ax, 'axison', True))
        frame = None
        try:
            frame = ax.get_window_extent(renderer)
        except Exception:
            frame = None
        if include_frames and frame is not None:
            # 注册过的坐标轴（面板）按**它自己的 gid** 记名：面板的可见包围盒必须可测，
            # 否则「面板整体刚体平移」这类声明只能靠猜，没法实测。
            frame_gid = ax.get_gid()
            out[key(frame_gid, ax_idx, 'frame', 0)] = {
                'gid': frame_gid, 'axes': ax_idx, 'kind': 'frame', 'dpi': dpi,
                'bbox_mm': _rect_mm(fig, scale, height_px, frame),
                'points_mm': None, 'text': None, 'container': True}
        for i, line in enumerate(ax.lines):
            if not line.get_visible():
                continue
            pts = _line_points(line)
            add(line.get_gid(), ax_idx, 'polyline', i, points=pts,
                clipped=line.get_clip_on())
        for i, patch in enumerate(ax.patches):
            if not patch.get_visible():
                continue
            try:
                bb = patch.get_window_extent(renderer)
            except Exception:
                continue
            add(patch.get_gid(), ax_idx, 'patch_envelope', i, bbox=bb,
                clipped=patch.get_clip_on())
        for i, coll in enumerate(ax.collections):
            if not coll.get_visible():
                continue
            try:
                bb = coll.get_window_extent(renderer)
            except Exception:
                continue
            add(coll.get_gid(), ax_idx, 'collection_envelope', i, bbox=bb,
                clipped=coll.get_clip_on())
        for i, im in enumerate(ax.images):
            if not im.get_visible():
                continue
            try:
                bb = im.get_window_extent(renderer)
            except Exception:
                continue
            add(im.get_gid(), ax_idx, 'image_envelope', i, bbox=bb,
                clipped=im.get_clip_on())
        for i, txt in enumerate(ax.texts):
            if not txt.get_visible() or not txt.get_text().strip():
                continue
            try:
                bb = txt.get_window_extent(renderer)
            except Exception:
                continue
            add(txt.get_gid(), ax_idx, 'text_envelope', i, bbox=bb, text=txt.get_text(),
                clipped=txt.get_clip_on())
        labels = [('xlabel', ax.xaxis.label, ax.xaxis), ('ylabel', ax.yaxis.label, ax.yaxis),
                  ('title', ax.title, None)]
        if ax.get_legend() is not None:
            labels.append(('legend', ax.get_legend(), None))
        for name, art, axis in labels:
            if art is None or not art.get_visible():
                continue
            if axis is not None and not (axison and axis.get_visible()):
                continue
            text = art.get_text() if hasattr(art, 'get_text') else name
            if hasattr(art, 'get_text') and not str(text).strip():
                continue
            try:
                bb = art.get_window_extent(renderer)
            except Exception:
                continue
            add(art.get_gid(), ax_idx, f'{name}_envelope', 0, bbox=bb, text=str(text)[:40],
                clipped=art.get_clip_on())
        for axis_name, axis in (('xtick', ax.xaxis), ('ytick', ax.yaxis)):
            if not axison or not axis.get_visible():
                continue
            for i, tick in enumerate(axis.get_major_ticks()):
                for part, art in (('label1', tick.label1), ('label2', tick.label2)):
                    if art is None or not art.get_visible() or not str(art.get_text()).strip():
                        continue
                    try:
                        bb = art.get_window_extent(renderer)
                    except Exception:
                        continue
                    add(art.get_gid(), ax_idx, f'{axis_name}_{part}_envelope', i, bbox=bb,
                        text=str(art.get_text())[:20])
    for i, image in enumerate(getattr(fig, 'images', [])):
        if not image.get_visible():
            continue
        # 图幅图像没有自己的 get_window_extent、也不挂在任何坐标框上：按真实未裁切几何记一条。
        # 量不出来就失败关闭，绝不用那个恒为空的包围盒冒充，也不默默跳过。
        bbox = figure_image_bbox(image)
        if bbox is None:
            raise SessionError(
                f'可见的图幅图像（fig.figimage 第 {i} 个）真实显示几何量不出来：'
                f'没有数组或偏移不是有限数，拒绝把不可测的可见图像当成安全几何')
        add(image.get_gid(), None, 'figure_image_envelope', i, bbox=bbox)
    for i, txt in enumerate(fig.texts):
        if not txt.get_visible() or not txt.get_text().strip():
            continue
        try:
            bb = txt.get_window_extent(renderer)
        except Exception:
            continue
        add(txt.get_gid(), None, 'figure_text_envelope', i, bbox=bb, text=txt.get_text()[:40])
    return out


def _shape_shift(before, after):
    """单个形状从 before 到 after 的位移（mm）与**该比较**适用的容差。

    同一个构建/DPI 下位置与尺寸都不变的成对比较（纯显示位移）用解析容差
    `TOL_SAME_RENDERER_MM`；尺寸本身变了的比较（跨 DPI/跨字体）用未标定的栅格容差，
    那种容差只能说明「变了」，不能用来证明位移量。
    """
    kind = before['kind']
    b0, b1 = before['bbox_mm'], after['bbox_mm']
    same_size = (abs((b1[2] - b1[0]) - (b0[2] - b0[0])) <= TOL_SAME_RENDERER_MM
                 and abs((b1[3] - b1[1]) - (b0[3] - b0[1])) <= TOL_SAME_RENDERER_MM)
    tol = (TOL_SAME_RENDERER_MM if same_size
           else TOL_ENVELOPE_MM_PER_PX * MM_PER_INCH / max(before.get('dpi', 100.0), 1.0))
    if kind == 'polyline' and before['points_mm'] and after['points_mm'] \
            and len(before['points_mm']) == len(after['points_mm']):
        n = len(before['points_mm'])
        dx = sum(b[0] - a[0] for a, b in zip(before['points_mm'], after['points_mm'])) / n
        dy = sum(b[1] - a[1] for a, b in zip(before['points_mm'], after['points_mm'])) / n
        return dx, dy, tol, 'polyline_points'
    cx0, cy0 = (b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2
    cx1, cy1 = (b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2
    return cx1 - cx0, cy1 - cy0, tol, 'envelope_center'


def shape_delta(before, after):
    """两个同名形状的位移与尺寸变化（mm）+ 容差。

    `tol_mm` 是**该成对比较**适用的容差（尺寸没变时就是解析容差）；
    `tight_mm` 是无条件可用的解析容差，证明物理位移只用它；
    `size_stable` 表示这次比较里形状尺寸有没有变（变了的就不是刚体平移）。
    """
    dx, dy, tol, method = _shape_shift(before, after)
    b0, b1 = before['bbox_mm'], after['bbox_mm']
    dw = float((b1[2] - b1[0]) - (b0[2] - b0[0]))
    dh = float((b1[3] - b1[1]) - (b0[3] - b0[1]))
    size_stable = bool(abs(dw) <= TOL_SAME_RENDERER_MM and abs(dh) <= TOL_SAME_RENDERER_MM)
    return {'dx_mm': float(dx), 'dy_mm': float(dy), 'dw_mm': dw, 'dh_mm': dh,
            'tol_mm': float(tol), 'tight_mm': TOL_SAME_RENDERER_MM,
            'size_stable': size_stable, 'method': method}


def _config_diff(before, after, prefix=()):
    """两次构建之间配置字典的差异（只报实际变化/新增/消失的叶键）。"""
    out = {}
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after), key=str):
            here = (*prefix, str(key))
            if key not in before:
                out['.'.join(here)] = {'to': after[key]}
            elif key not in after:
                out['.'.join(here)] = {'from': before[key]}
            else:
                out.update(_config_diff(before[key], after[key], here))
        return out
    if before != after:
        out['.'.join(prefix)] = {'from': before, 'to': after}
    return out


def _shapes_differ(before, after):
    """两个同名形状是否发生了超过测量容差的变化。"""
    if before is None or after is None:
        return True
    delta = shape_delta(before, after)
    tol = delta['tol_mm']
    return max(abs(delta['dx_mm']), abs(delta['dy_mm']),
               abs(delta['dw_mm']), abs(delta['dh_mm'])) > tol


def _axes_owner_gids(shapes) -> dict:
    """轴序号 → 注册在这根轴上的 gid（框架 entry 现在按注册 gid 记名）。"""
    out = {}
    for key, rec in shapes.items():
        if rec.get('container') and key.startswith('gid:'):
            out[rec.get('axes')] = key.split(':', 1)[1]
    return out


def _owned_keys(shapes, owned) -> set:
    """声明对象 + 后代，以及在**属于它们的那根坐标轴**上的未注册可见几何。

    未注册的图元（画在面板里的东西）没有 gid，只能按「画在哪根轴」归属；
    轴自己的框架 entry 带注册 gid，所以这条归属链是可查的事实，不是几何猜测。
    """
    out = {f'gid:{gid}' for gid in owned}
    axes_owner = _axes_owner_gids(shapes)
    for key, rec in shapes.items():
        if key in out or key.startswith('gid:'):
            continue
        owner = axes_owner.get(rec.get('axes'))
        if owner is not None and owner in owned:
            out.add(key)
    return out


def _rigid_delta(before_shape, after_shape, axis, expected_mm, tol, what):
    """一个形状相对基线的位移是否等于声明的刚体物理量。

    返回 `(问题列表, 实测增量, 沿轴位移)`；同一构建/同一 DPI 下的显示位移是解析量，
    所以这里只用 `TOL_SAME_RENDERER_MM`，绝不拿栅格不确定度当精度。
    """
    entry = shape_delta(before_shape, after_shape)
    along, across = ((entry['dx_mm'], entry['dy_mm']) if axis == 'x'
                     else (entry['dy_mm'], entry['dx_mm']))
    if not entry['size_stable']:
        return ([f'{what} 的包围盒尺寸同时变了 ({round(entry["dw_mm"], 4)}, '
                 f'{round(entry["dh_mm"], 4)}) mm，不是声明中的刚体平移'], entry, along)
    if abs(across) > tol:
        return ([f'{what} 出现了非声明轴（{axis}）位移 {round(across, 6)} mm'], entry, along)
    if abs(along - expected_mm) > tol:
        return ([f'{what} 实测位移 {round(along, 6)} mm 与声明物理量 '
                 f'{round(expected_mm, 6)} mm 不符（同渲染器解析容差 {tol} mm）'], entry, along)
    return [], entry, along


def _changed_shape_keys(before, after):
    """两次构建之间发生可测变化（位移**或**尺寸）的形状键集合。"""
    changed = set(before) ^ set(after)
    for key in set(before) & set(after):
        delta = shape_delta(before[key], after[key])
        tol = delta['tol_mm']
        if (abs(delta['dx_mm']) > tol or abs(delta['dy_mm']) > tol
                or abs(delta['dw_mm']) > tol or abs(delta['dh_mm']) > tol):
            changed.add(key)
    return changed


def _changed_style_gids(before, after):
    """样式字典里有可测变化的 gid 集合。"""
    out = set()
    for gid in set(before) | set(after):
        left, right = before.get(gid) or {}, after.get(gid) or {}
        for prop in set(left) | set(right):
            was, now = left.get(prop), right.get(prop)
            if isinstance(was, float) and isinstance(now, float):
                if abs(was - now) <= _STYLE_TOL:
                    continue
            elif was == now:
                continue
            out.add(gid)
            break
    return out


# --- 碰撞/间隔原语（保守：包络间距下界，折线间距为线段间距） --------------------- #

def _segments(points):
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segs_intersect(p1, p2, p3, p4):
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    def on(p, q, r):
        return (min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and
                min(p[1], r[1]) <= q[1] <= max(p[1], r[1]))
    if d1 == 0 and on(p3, p1, p4):
        return True
    if d2 == 0 and on(p3, p2, p4):
        return True
    if d3 == 0 and on(p1, p3, p2):
        return True
    if d4 == 0 and on(p1, p4, p2):
        return True
    return False


def _point_seg_distance(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _seg_seg_distance(a, b, c, d):
    if segs_intersect(a, b, c, d):
        return 0.0
    return min(_point_seg_distance(a, c, d), _point_seg_distance(b, c, d),
               _point_seg_distance(c, a, b), _point_seg_distance(d, a, b))


def rect_gap(r1, r2):
    """两个矩形的带符号间隔（mm）：负值表示重叠。"""
    dx = max(r2[0] - r1[2], r1[0] - r2[2])
    dy = max(r2[1] - r1[3], r1[1] - r2[3])
    if dx >= 0 and dy >= 0:
        return math.hypot(dx, dy)
    if dx >= 0:
        return dx
    if dy >= 0:
        return dy
    return max(dx, dy)


def _point_in_rect(p, r):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


def _seg_rect_hit(a, b, r):
    if _point_in_rect(a, r) or _point_in_rect(b, r):
        return True
    corners = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]), (r[0], r[1])]
    return any(segs_intersect(a, b, corners[i], corners[i + 1]) for i in range(4))


def _poly_rect_gap(points, r):
    if any(_point_in_rect(p, r) for p in points):
        return 0.0
    for a, b in _segments(points):
        if _seg_rect_hit(a, b, r):
            return 0.0
    corners = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]), (r[0], r[1])]
    best = math.inf
    for a, b in _segments(points):
        for i in range(4):
            best = min(best, _seg_seg_distance(a, b, corners[i], corners[i + 1]))
    return best


def _poly_poly_gap(pa, pb):
    # 复用已验证的精确分段几何内核；不要在会话里再做 Python O(n*m) 扫描。
    import numpy as np
    from figpact.geometry import _segment_set_distance, _segments as line_segments
    a, b = np.asarray(pa, dtype=float), np.asarray(pb, dtype=float)
    return _segment_set_distance(line_segments(a), line_segments(b))[0]


def shape_gap(a, b, bbox_gate_mm=2.0):
    """两个显示几何之间的间隔（mm）与方法标签。

    - 折线 × 折线：精确线段间距（`polyline_segments`）
    - 折线 × 包络：线段与包络矩形的精确间距（`polyline_vs_envelope`）
    - 包络 × 包络：矩形下界（`bbox_conservative`，形状可能在角上分开，故只作保守下界）
    """
    ra, rb = a['bbox_mm'], b['bbox_mm']
    if rect_gap(ra, rb) > bbox_gate_mm:
        return rect_gap(ra, rb), 'bbox_pruned'
    pa, pb = a.get('points_mm'), b.get('points_mm')
    if pa and pb:
        return _poly_poly_gap(pa, pb), 'polyline_segments'
    if pa and b['kind'] != 'polyline':
        return _poly_rect_gap(pa, rb), 'polyline_vs_envelope'
    if pb and a['kind'] != 'polyline':
        return _poly_rect_gap(pb, ra), 'polyline_vs_envelope'
    return rect_gap(ra, rb), 'bbox_conservative'


def _collision_text(entry):
    """碰撞证据的可读描述（含基线上同一对的测量，说明是不是新问题）。"""
    base = entry.get('baseline_gap_mm')
    tail = '' if base is None else f'，基线同一对 {base} mm'
    return (f'{entry["pair"][0]} × {entry["pair"][1]}'
            f'（{entry["method"]}，{entry["gap_mm"]} mm{tail}）')


def _shift_points(points, dx, dy):
    return [(x + dx, y + dy) for x, y in points]


def _shift_shape(shape, dx, dy):
    moved = dict(shape)
    r = shape['bbox_mm']
    moved['bbox_mm'] = [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]
    if shape.get('points_mm'):
        moved['points_mm'] = _shift_points(shape['points_mm'], dx, dy)
    return moved


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #

class FigureSession:
    """一个 (script, config, scope) 的热会话。不提交、不发布。"""

    def __init__(self, script, config, scope, *, contract=None):
        self.script = Path(script).resolve()
        self.config = Path(config).resolve()
        self.scope = scope
        self._tmpdir = None
        self._owners = None
        self._module = None
        self._scene = None
        self._module_rev = None
        self._science = None
        self.science_manifest = None
        self._contract_override = contract
        self.contract = {}
        self.base_config_revision = None
        self._base_config = None
        self._source_rev = None
        self._goals: dict[tuple, float] = {}
        self._proofs: dict[str, dict] = {}
        self._preview_cache: dict[str, dict] = {}
        self._frame_cache: dict | None = None
        self._frame_cache_key: tuple | None = None
        self._frame_cache_shapes: dict | None = None
        self._baseline = None
        self._fig = None
        self._reg = None
        self._built_revision = None
        self._closed = False
        self.diagnostics: list[str] = []
        self.last_config_writeback: dict = {}
        self.last_user_output: str = ''
        self._reload()

    # -- 生命周期 ---------------------------------------------------------- #

    def _reload(self, *, module=True):
        """（重新）建立会话状态。

        `module=False` 是**配置变更后的重基线**：只重读 YAML、重建基线、作废候选/证明/
        预览缓存。模块对象与已装载的科学对象直接复用——源码指纹没变就没有理由重导模块
        或重装科学数据（那是冷启动的代价，配置变更不该付）。
        """
        if module:
            self._module = load_module_cached(self.script, self.config)
            # 核心场景模块是前置条件：缺了就没有场景语义，任何编辑都不许被接受。
            self._scene = _core_module('scene')
        declared_scopes = getattr(self._module, 'SCOPES', None)
        if declared_scopes is not None and self.scope not in tuple(declared_scopes):
            raise SessionError(f'未知 scope：{self.scope!r}；脚本声明的作用域是 '
                               f'{list(declared_scopes)}')
        self.base_config_revision = hashlib.sha256(self.config.read_bytes()).hexdigest()
        raw = yaml.safe_load(self.config.read_text(encoding='utf8'))
        if not isinstance(raw, dict):
            raise SessionError(f'配置顶层必须是映射：{self.config.name}')
        prepare = getattr(self._module, 'prepare_config', None)
        if callable(prepare):
            raw = prepare(copy.deepcopy(raw))
            if not isinstance(raw, dict):
                raise SessionError('prepare_config 必须返回独立的配置映射')
        self._base_config = raw
        self._goals.clear()
        self._proofs.clear()
        self._preview_cache.clear()
        self._frame_cache = None
        self._frame_cache_key = None
        self._frame_cache_shapes = None
        self._baseline = None
        self._close_built()
        mod = self._module
        self._science_inputs = declared_science_inputs(self._module)
        if self._contract_override is not None:
            raw_contract = self._contract_override
        else:
            hook = getattr(mod, 'layout_contract', None)
            raw_contract = hook(self.scope) if callable(hook) else None
        self._outputs = declared_output_stems(raw_contract, self.script)
        self._source_rev = source_revision(self.script, self.config,
                                           exclude=self._outputs, required=self._science_inputs)
        self._module_rev = module_revision(self.script, self.config,
                                           exclude=self._outputs,
                                           required=self._science_inputs)
        self.science_manifest = None
        if callable(getattr(mod, 'build_scene', None)):
            loader = getattr(mod, 'load_science', None)
            if not callable(loader):
                raise SessionError('脚本声明了 build_scene 却没有 load_science')
            cached = _SCIENCE_CACHE.get(str(self.script))
            fingerprint = script_fingerprint(self.script, self.config,
                                             exclude=self._outputs, required=self._science_inputs)
            if cached is not None and cached[0] == fingerprint:
                self._science, self.science_manifest = cached[1], cached[2]
            else:
                _SCIENCE_LOADS[0] += 1
                self._science = loader()
                manifest_hook = getattr(mod, 'science_manifest', None)
                if callable(manifest_hook):
                    self.science_manifest = manifest_hook(self._science)
                _SCIENCE_CACHE[str(self.script)] = (fingerprint, self._science,
                                                    self.science_manifest)
        self._baseline = self._capture_baseline()
        self.contract = self._prepare_contract(raw_contract, self._baseline['gids'])
        self._owners = None

    def _sync(self):
        """磁盘上变了就同步，绝不拿陈旧缓存冒充结果。

        - 脚本/科学输入/引擎实现变了 → **整会话重载**（重新导入模块、必要时重装科学对象）。
        - 只有配置（YAML）变了 → **重基线**：模块与科学对象照旧复用。
        """
        if self._closed:
            raise SessionError('会话已关闭')
        if module_revision(self.script, self.config, exclude=self._outputs,
                           required=self._science_inputs) != self._module_rev:
            self._reload()
            return True
        if hashlib.sha256(self.config.read_bytes()).hexdigest() != self.base_config_revision:
            self._reload(module=False)
            return True
        return False

    def close(self):
        if self._closed:
            return
        self._close_built()
        self._frame_cache = None
        self._frame_cache_key = None
        self._frame_cache_shapes = None
        self._closed = True
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def _close_built(self):
        if self._fig is not None:
            import matplotlib.pyplot as plt
            plt.close(self._fig)
        self._fig = None
        self._reg = None
        self._built_revision = None

    # -- 契约 -------------------------------------------------------------- #

    def _prepare_contract(self, raw, object_ids=None):
        if raw is None:
            return {'parameters': [], 'nodes': {}, 'groups': [], 'relations': [], 'outputs': [],
                    'source': 'absent'}
        if not isinstance(raw, dict):
            raise ContractError('layout_contract 必须返回字典')
        contracts = _core_module('contracts')
        validate = getattr(contracts, 'validate_contract', None)
        if not callable(validate):
            raise ContractError('figpact.contracts 没有 validate_contract：布局契约无法校验')
        try:
            # 一次校验，带上真实注册表对象：悬空对象引用**不许**降级重试后被接受。
            validated = validate(raw, scope=self.scope, object_ids=object_ids)
        except Exception as error:
            raise ContractError(f'布局契约未通过校验：{error}') from error
        if isinstance(validated, dict):
            raw = validated
        out = {'parameters': [], 'nodes': raw.get('nodes') or {}, 'groups': raw.get('groups') or [],
               'relations': raw.get('relations') or [], 'outputs': raw.get('outputs') or [],
               'source': 'validated', 'validation_error': None}
        seen: dict[tuple, str] = {}
        for entry in raw.get('parameters') or []:
            if not isinstance(entry, dict):
                raise ContractError(f'参数记录必须是映射：{entry!r}')
            try:
                path = _norm_path(entry.get('path'))
            except ValueError as error:
                raise ContractError(f'参数 {entry.get("key")!r} 的 path 不可用：{error}') from error
            scopes = entry.get('scopes')
            if scopes is not None and self.scope not in scopes:
                out.setdefault('out_of_scope', []).append({'key': entry.get('key'), 'path': list(path),
                                                           'scopes': list(scopes)})
                continue
            if path in seen:
                raise ContractError(f'参数路径重复声明：{list(path)}')
            seen[path] = entry.get('key')
            out['parameters'].append(entry)
        return out

    def parameters(self):
        return list(self.contract.get('parameters') or [])

    def _param_of_path(self, path: tuple):
        """返回 (record, status)：唯一匹配则 record 非空；否则给出拒绝理由。"""
        matches = [e for e in self.parameters() if _norm_path(e['path']) == path]
        if len(matches) > 1:
            return None, STATUS_AMBIGUOUS
        if matches:
            return matches[0], None
        out_of_scope = [e for e in (self.contract.get('out_of_scope') or [])
                        if _norm_path(e['path']) == path]
        if out_of_scope:
            return None, STATUS_NOT_IN_SCOPE
        return None, STATUS_UNSUPPORTED_PATH

    def _param_mutability(self, rec):
        value = rec.get('mutability')
        return value if value in (EDITABLE, LOCKED_SCIENCE, FIXED_STYLE, DERIVED) else UNCLASSIFIED

    # -- 归属（控制对象 → 后代闭包） --------------------------------------- #

    def _ownership(self) -> dict:
        """子 gid → 父 gid 的**权威归属**：来自作者声明的 nodes/groups，绝不从包围盒猜。

        节点自己的 `parent` 声明优先于「是某个组的成员」这类容器关系。
        """
        if self._owners is not None:
            return self._owners
        owners: dict[str, str] = {}
        for group in self.contract.get('groups') or []:
            if not isinstance(group, dict):
                continue
            gid, parent = group.get('id'), group.get('parent')
            if isinstance(gid, str) and gid:
                if isinstance(parent, str) and parent:
                    owners.setdefault(gid, parent)
                for member in group.get('members') or []:
                    if isinstance(member, str) and member:
                        owners.setdefault(member, gid)
        for gid, meta in (self.contract.get('nodes') or {}).items():
            if not isinstance(gid, str) or not gid or not isinstance(meta, dict):
                continue
            parent = meta.get('parent')
            if isinstance(parent, str) and parent:
                owners[gid] = parent
        self._owners = owners
        return owners

    def owned_closure(self, gids) -> list:
        """给定控制对象，返回它自己 + 全部后代 gid（父子链闭包）。

        「面板整体平移」这类声明的作用集合是**面板及其内容**，作者不必把所有后代
        再抄进 objects；但不在闭包里的对象（无关兄弟）动一下就是新问题。
        """
        owners = self._ownership()
        out = {gid for gid in gids if gid}
        frontier = list(out)
        while frontier:
            parent = frontier.pop()
            for child, owner in owners.items():
                if owner == parent and child not in out:
                    out.add(child)
                    frontier.append(child)
        return sorted(out)

    def _contain_relations(self) -> dict:
        """作者声明的 `contain` 关系 → {被容纳对象 gid: [容器 gid, ...]}。

        `objects[0]` 是容器、其余是要落在它里面的对象（与父模块
        `figpact.geometry.measure_relation('contain')` 的语义一致）：这是**作者写过的**
        包含声明，不是从归属/包围盒猜出来的。
        """
        out: dict[str, list[str]] = {}
        for rel in self.contract.get('relations') or []:
            if not isinstance(rel, dict) or rel.get('kind') != 'contain':
                continue
            objects = [gid for gid in (rel.get('objects') or [])
                       if isinstance(gid, str) and gid]
            if len(objects) < 2:
                continue
            for member in objects[1:]:
                out.setdefault(member, [])
                if objects[0] not in out[member]:
                    out[member].append(objects[0])
        return out

    def _container_gids(self, gid) -> list:
        """一个对象要落在哪些**声明的**容器里：沿作者声明的归属链上溯取最近的一层。

        后代跟着祖先一起受约束（容器装得下父对象，也就装得下它的内容）；归属链上
        没有任何 `contain` 声明就不返回容器——不给它安排一条作者没写过的包含关系。
        """
        if not isinstance(gid, str) or not gid:
            return []
        declared, owners = self._contain_relations(), self._ownership()
        node, seen = gid, set()
        while node and node not in seen:
            seen.add(node)
            if node in declared:
                return list(declared[node])
            node = owners.get(node)
        return []

    # -- 构建 -------------------------------------------------------------- #

    def _call_builder(self, config_dict, config_path):
        """构建候选：**把配置拷贝交给脚本**，脚本的就地回写不会被当成候选输入。

        构图在调用时 rc 快照下隔离执行，并叠加脚本导入期的 rc 改动（字体/dpi……）——
        两者都是脚本声明的构建环境；脚本的样式重放只进隔离区，退出即还原，不外泄。
        """
        import matplotlib as mpl
        mod = self._module
        working = copy.deepcopy(config_dict)
        builder = getattr(mod, 'build_scene', None)
        buffer = io.StringIO()
        ambient = pristine_rc()
        overlay = getattr(mod, '__figpact_import_rc__', None)
        if overlay:
            ambient.update(copy.deepcopy(overlay))
        with mpl.rc_context(rc=ambient):
            with redirect_stdout(buffer):
                if callable(builder):
                    fig, reg = builder(self._science, working, self.scope)
                else:
                    legacy = getattr(mod, 'build_figure_and_registry', None)
                    if not callable(legacy):
                        raise SessionError('脚本既没有 build_scene 也没有 build_figure_and_registry')
                    if _accepts(legacy, 'config'):
                        fig, reg = legacy(self.scope, config=working)
                    else:
                        if config_path is not None and hasattr(mod, 'CONFIG_PATH'):
                            mod.CONFIG_PATH = Path(config_path)
                        fig, reg = legacy(self.scope)
        self.last_user_output = buffer.getvalue()[:4000]
        writeback = _config_diff(config_dict, working)
        self.last_config_writeback = writeback
        if writeback:
            self.diagnostics.append(
                f'build_scene 就地回写了 {sorted(writeback)}（未并入候选；候选仍由配置 + 声明目标派生）')
        if reg is None or not isinstance(reg, GidRegistry):
            reg = GidRegistry()
        return fig, reg

    def _write_candidate_yaml(self, config_dict):
        if self._tmpdir is None:
            self._tmpdir = tempfile.TemporaryDirectory(prefix='figpact-session-')
        path = Path(self._tmpdir.name) / f'candidate-{self._candidate_hash(config_dict)[:12]}.yaml'
        path.write_text(yaml.safe_dump(config_dict, sort_keys=False, allow_unicode=True), encoding='utf8')
        return path

    def _candidate_hash(self, config_dict):
        blob = json.dumps({'scope': self.scope, 'config': config_dict},
                          sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode('utf8')).hexdigest()

    def build_candidate(self, config_dict):
        """用真实（临时）YAML 构建候选图，返回 (fig, registry)。"""
        path = self._write_candidate_yaml(config_dict)
        return self._call_builder(config_dict, path)

    def build_from_yaml(self, path):
        """从一份真实存在的 YAML 文件重建候选（扰动效果验证用）。"""
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding='utf8'))
        if not isinstance(data, dict):
            raise SessionError(f'YAML 顶层必须是映射：{path.name}')
        return self._call_builder(data, path)

    # -- 基线 -------------------------------------------------------------- #

    def _capture_baseline(self):
        fig, reg = self._call_builder(self._base_config, self.config)
        try:
            shapes = drawn_shapes(fig, reg, include_frames=True)
            styles = self._styles(fig, reg)
            science = self._capture_science(fig, reg)
            qa_payload = self._qa(fig)
            png = self._png_digest(fig)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return {'config': copy.deepcopy(self._base_config), 'shapes': shapes, 'styles': styles,
                'science': science, 'qa': qa_payload, 'png_digest': png,
                'gids': sorted(reg.all())}

    @staticmethod
    def _png_digest(fig):
        """基线的栅格指纹：给渲染验证回答「这次重建到底有没有改变产物」。"""
        import matplotlib as mpl
        buf = io.BytesIO()
        with mpl.rc_context({'savefig.bbox': None}):
            fig.savefig(buf, format='png', dpi=fig.dpi, bbox_inches=None)
        return hashlib.sha256(buf.getvalue()).hexdigest()

    def _capture_science(self, fig, reg):
        """科学指纹：父模块 figpact.science 是核心前置条件，缺了就不给结论。"""
        science_mod = _core_module('science')
        hook = getattr(science_mod, 'capture_science', None)
        if not callable(hook):
            raise SessionError('figpact.science 没有 capture_science：科学等值无法观测')
        captured = hook(fig, reg, declarations=self.science_manifest)
        if not isinstance(captured, dict):
            raise SessionError('capture_science 必须返回映射，得到 '
                               f'{type(captured).__name__}')
        return {'verified': True, 'digest': captured.get('digest'),
                'objects': captured.get('objects'), 'captured': captured}

    def _compare_science(self, before, after):
        """科学等值比较；核心模块缺失是前置条件错误，不是「未验证但通过」。"""
        if not before.get('verified') or not after.get('verified'):
            raise SessionError('科学指纹未经验证，拒绝给出结论')
        if before.get('digest') == after.get('digest'):
            return True, []
        science_mod = _core_module('science')
        hook = getattr(science_mod, 'compare_science', None)
        if not callable(hook):
            raise SessionError('figpact.science 没有 compare_science：科学差异无法解释')
        return False, list(hook(before.get('captured'), after.get('captured')) or [])

    def _styles(self, fig, reg):
        out = {}
        for gid, art in reg.all().items():
            entry = {}
            for prop, getter in (('fontsize', 'get_fontsize'), ('linewidth', 'get_linewidth'),
                                 ('color', 'get_color'), ('alpha', 'get_alpha'),
                                 ('markersize', 'get_markersize'), ('text', 'get_text'),
                                 ('visible', 'get_visible')):
                fn = getattr(art, getter, None)
                if not callable(fn):
                    continue
                try:
                    value = fn()
                except Exception:
                    continue
                if isinstance(value, str) and len(value) > 60:
                    value = value[:60]
                entry[prop] = _json_native(value)
            if art is fig or art is fig.patch:
                entry['renderer_dpi'] = float(fig.dpi)
            out[gid] = entry
        return out

    def _qa(self, fig):
        mod = self._module
        hook = getattr(mod, 'preview_qa', None)
        if callable(hook):
            with redirect_stdout(io.StringIO()):
                problems = list(hook(fig, self.scope))
            return {'qa': problems, 'qa_kind': 'preview_qa'}
        from figpact.qa import blocking_problems
        with redirect_stdout(io.StringIO()):
            problems = list(blocking_problems(fig))
        return {'qa': problems, 'qa_kind': 'blocking_problems'}

    @staticmethod
    def _qa_keys(problems):
        from figpact import qa as qa_mod
        keys = []
        for problem in problems:
            try:
                keys.append(json.dumps(qa_mod.diagnostic_key_of(problem), ensure_ascii=False))
            except Exception:
                keys.append(str(problem))
        return keys

    # -- 候选目标 ---------------------------------------------------------- #

    @property
    def candidate_patch(self):
        patch: dict = {}
        for path, value in sorted(self._goals.items()):
            cur = patch
            segs = list(path)
            for seg in segs[:-1]:
                nxt = cur.get(seg)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[seg] = nxt
                cur = nxt
            cur[segs[-1]] = value
        return patch

    @property
    def candidate_config(self):
        cfg = copy.deepcopy(self._base_config)
        for path, value in sorted(self._goals.items()):
            set_path(cfg, path, value)
        return cfg

    @property
    def revision(self):
        if not self._goals:
            return self._candidate_hash(self._base_config)
        return self._candidate_hash(self.candidate_config)

    # -- 操作分类 ---------------------------------------------------------- #

    def _classify(self, operations):
        """把一批操作解析成 (resolved, failure)。

        `pending` 是「已有目标 + 本批已接受目标」的工作集：关系目标必须对**当前候选**
        反解（例如净空 1.5 mm 已被另一条独立位移推到 1.9 mm，目标 2.0 就要解 1.6，
        而不是照抄 2.0）。任何一步失败都不改状态。
        """
        if isinstance(operations, (dict, str)):
            operations = [operations]
        if not isinstance(operations, (list, tuple)) or not operations:
            raise ValueError('operations 必须是非空列表')
        resolved, pending, seen_values, seen_relations = [], dict(self._goals), {}, {}
        reset = any(isinstance(raw, dict) and raw.get('operation') == 'reset' for raw in operations)
        if reset:
            pending = {}
        for raw in operations:
            if not isinstance(raw, dict):
                return None, self._fail(STATUS_INVALID_VALUE, '操作记录必须是映射', raw=repr(raw))
            op = raw.get('operation')
            if op == 'reset':
                resolved.append({'kind': 'reset'})
                continue
            if op == 'set_parameter':
                try:
                    path = _norm_path(raw.get('path'))
                except ValueError as error:
                    return None, self._fail(STATUS_INVALID_VALUE, str(error))
                rec, status = self._param_of_path(path)
                value, failure = self._normalize_value(rec or {}, path, raw.get('value'))
                if failure is not None:
                    return None, failure
                if rec is None:
                    return None, self._fail(status, self._path_reason(status, path), path=list(path))
                failure = self._check_parameter(rec, path, value)
                if failure is not None:
                    return None, failure
                if path in seen_values and seen_values[path] != value:
                    return None, self._fail(
                        STATUS_CONTRADICTORY, f'{list(path)} 在同一批里被要求两个值', path=list(path))
                seen_values[path] = value
                pending[path] = value
                resolved.append({'kind': 'parameter', 'record': raw, 'param': rec,
                                 'path': path, 'value': value})
                continue
            if op == 'set_relation':
                relation_id = raw.get('relation_id') or raw.get('id')
                target = raw.get('target_mm')
                rel = next((r for r in (self.contract.get('relations') or [])
                            if r.get('id') == relation_id), None)
                if rel is None:
                    return None, self._fail(STATUS_UNKNOWN_RELATION,
                                            f'契约里没有关系 {relation_id!r}', path=[str(relation_id)])
                try:
                    target = _finite(target, f'关系 {relation_id} 的目标')
                except ValueError as error:
                    return None, self._fail(STATUS_INVALID_VALUE, str(error))
                if relation_id in seen_relations and seen_relations[relation_id] != target:
                    return None, self._fail(
                        STATUS_CONTRADICTORY,
                        f'关系 {relation_id} 在同一批里被要求两个目标 '
                        f'（{seen_relations[relation_id]} 与 {target} mm）', path=[str(relation_id)])
                seen_relations[relation_id] = target
                plan = self._plan_relation(rel, target, pending)
                if isinstance(plan, dict) and plan.get('status'):
                    return None, plan
                for entry in plan:
                    value = entry['value']
                    if entry['path'] in seen_values and seen_values[entry['path']] != value:
                        return None, self._fail(
                            STATUS_CONTRADICTORY,
                            f'{list(entry["path"])} 在同一批里被要求两个值（关系目标互相矛盾）',
                            path=list(entry['path']))
                    seen_values[entry['path']] = value
                    pending[entry['path']] = value
                    resolved.append({'kind': 'relation', 'record': raw, 'param': entry['param'],
                                     'path': entry['path'], 'value': value,
                                     'relation': rel, 'target_mm': target,
                                     'base_value': entry['base_value']})
                continue
            return None, self._fail(STATUS_INVALID_VALUE, f'未知操作 {op!r}', raw=repr(raw))
        return resolved, None

    def _pair_target(self, rec, path) -> bool:
        """这个参数是不是**已经声明了的 2D 位移**（值本身是一对 `[dx, dy]`）。

        两个判据都来自既有事实，不新造科学标签、也不看未知键：**当前归一化的基线**
        在这条精确路径上本来就是一对有限数字（作者写在 YAML 里的形状），且声明的
        `operation` 是 `rebuild`（真实重建）。普通标量路径永远拿不到序列值的通行证。
        """
        if rec.get('operation') != 'rebuild':
            return False
        try:
            return _pair_of(get_path(self._base_config, path)) is not None
        except (KeyError, ValueError):
            return False

    def _normalize_value(self, rec, path, raw):
        """操作值 → 存储值；失败返回 `(None, failure)`。

        **声明了的 2D 位移**（基线里本来就是一对、operation 是 rebuild）只收一对
        `[dx, dy]`：逐分量有限（`_pair_of` 负责）、逐分量用同一条声明区间。
        普通标量路径只收有限数字，报错文案不变。其余形状一律 INVALID_VALUE——
        序列不许漏到标量路径上，标量也不许打进 2D 路径。
        """
        if self._pair_target(rec, path):
            pair = _pair_of(raw)
            if pair is None:
                return None, self._fail(
                    STATUS_INVALID_VALUE,
                    f'{list(path)} 声明为 2D 位移（基线里就是一对 [dx, dy]），'
                    f'目标必须是恰好两个有限数字，得到 {raw!r}', path=list(path))
            for index, comp in enumerate(pair):
                if not self._in_range(rec, comp):
                    return None, self._fail(
                        STATUS_OUT_OF_RANGE,
                        f'{list(path)} = {raw!r} 的第 {index} 个分量 {comp} 超出声明范围 '
                        f'[{rec.get("min")}, {rec.get("max")}]', path=list(path))
            return pair, None
        try:
            return _finite(raw, f'{list(path)} 的值'), None
        except ValueError as error:
            return None, self._fail(STATUS_INVALID_VALUE, str(error), path=list(path))

    def _check_parameter(self, rec, path, value):
        """单个参数目标的可编辑性/类型/区间检查；通过返回 None。"""
        kind = self._param_mutability(rec)
        if kind == UNCLASSIFIED:
            return self._fail(STATUS_UNCLASSIFIED, f'{list(path)} 未声明可变性，拒绝改动', path=list(path))
        if kind == LOCKED_SCIENCE:
            return self._fail(STATUS_LOCKED, f'{list(path)} 锁定科学内容', path=list(path))
        if kind in (FIXED_STYLE, DERIVED):
            return self._fail(kind, f'{list(path)} 声明为 {kind}，不可编辑', path=list(path))
        if rec.get('operation') not in _OPERATIONS:
            return self._fail(
                STATUS_UNCLASSIFIED, f'{list(path)} 未声明 operation（translate/rebuild/resize）',
                path=list(path))
        if not self._in_range(rec, value):
            return self._fail(
                STATUS_OUT_OF_RANGE,
                f'{list(path)} = {value} 超出声明范围 [{rec.get("min")}, {rec.get("max")}]',
                path=list(path))
        try:
            get_path(self._base_config, path)
        except KeyError:
            return self._fail(STATUS_UNSUPPORTED_PATH,
                              f'{list(path)} 在配置里不存在（悬空引用）', path=list(path))
        return None

    def _path_reason(self, status, path):
        if status == STATUS_NOT_IN_SCOPE:
            return f'{list(path)} 不属于作用域 {self.scope}'
        if status == STATUS_AMBIGUOUS:
            return f'{list(path)} 在契约里被多条记录命中，无法判定'
        return f'{list(path)} 未在布局契约里声明'

    def _in_range(self, rec, value):
        if isinstance(value, (list, tuple)):
            # 2D 目标：**每个分量**都用同一条声明区间（作者不必为 dx/dy 各写一套）。
            return all(self._in_range(rec, comp) for comp in value)
        lo, hi = rec.get('min'), rec.get('max')
        if lo is None and hi is None:
            return True
        if lo is not None and value < float(lo):
            return False
        if hi is not None and value > float(hi):
            return False
        return True

    def _fail(self, status, message, **extra):
        return {'status': status, 'message': message, **extra}

    def _refuse(self, status, message, *, checks=(), affected=(), relation_ids=(), diagnostics=()):
        """明确拒绝：有 status、没有成功等级、没有 PNG。

        用于「观测到的声明不符 / 没有效果 / 测不了」——这些一律不许降级成
        RENDER_CHECKED 的成功结论。
        """
        return {'status': status, 'verification': None, 'message': message,
                'checks': list(checks), 'affected_objects': list(affected),
                'relations': list(relation_ids), 'diagnostics': list(diagnostics),
                'science_unchanged': None, 'png': None}

    def _refuse_proofs(self, failures, affected, relation_ids):
        """声明被真实重建扰动**否证**：拒绝，不问渲染 QA 要通行证。"""
        first = failures[0]
        checks = [{'check': 'translation_proof', 'status': 'FAIL',
                   'parameter': f.get('key'), 'path': f.get('path'),
                   'detail': f.get('reason'), 'measured': f.get('measured')}
                  for f in failures]
        detail = '；'.join(f'{f.get("path")}: {f.get("reason")}' for f in failures)
        return self._refuse(
            first.get('status') or STATUS_EFFECT_MISMATCH,
            f'声明未通过真实重建扰动验证：{detail}', checks=checks,
            affected=affected, relation_ids=relation_ids,
            diagnostics=['实测的绑定行为与声明不符/没有可测效果：不退回渲染验证，也不给成功结论',
                         '修好 YAML 绑定或声明中的 scale/axis/objects 后重试，或把该目标改成 '
                         'operation=rebuild 走渲染验证'])

    def _plan_relation(self, rel, target_mm, pending):
        """把关系目标反解成参数目标（对**当前候选**几何，不是基线）。

        例：净空参数已是 1.5 mm、又有一条独立的位移把上曲线推了 0.4 mm，
        候选净空就是 1.9 mm；目标 2.0 mm 要解出参数 1.6，而不是照抄 2.0。
        反解不了（多映射、两端同动、包络重叠、非平移目标在场）一律 UNSUPPORTED。
        """
        axis = rel.get('axis') or 'x'
        controlled = list(rel.get('controlled_by') or [])
        if not controlled:
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              f'关系 {rel.get("id")} 没有 controlled_by 映射（无可编辑映射即不支持）')
        if len(controlled) != 1:
            return self._fail(STATUS_AMBIGUOUS,
                              f'关系 {rel.get("id")} 有 {len(controlled)} 条 controlled_by 映射，'
                              f'没有求解器也不替作者挑一条',
                              options=[list(p) for p in controlled])
        norm = _norm_path(controlled[0])
        rec, status = self._param_of_path(norm)
        if rec is None:
            return self._fail(status, self._path_reason(status, norm), path=list(norm))
        mutability = self._param_mutability(rec)
        if mutability != EDITABLE:
            return self._fail(mutability if mutability != UNCLASSIFIED else STATUS_UNCLASSIFIED,
                              f'关系 {rel.get("id")} 依赖不可编辑参数 {list(norm)}')
        if rec.get('operation') != 'translate':
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              f'关系 {rel.get("id")} 依赖非 translate 参数 {list(norm)}')
        if (rec.get('axis') or axis) != axis:
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              f'关系 {rel.get("id")} 与参数 {list(norm)} 的轴不一致')
        shapes = self._predicted_shapes(pending)
        if shapes is None:
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              '当前候选含无法预测的非平移目标，关系不能在不渲染的情况下反解')
        value, direction, method, fixed_gid, moving_gid = self._relation_geometry(rel, shapes)
        if value is None:
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              f'关系 {rel.get("id")} 当前值无法测量：{method}')
        objects = list(rec.get('objects') or [])
        if moving_gid not in objects:
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              f'关系 {rel.get("id")} 的移动节点 {moving_gid} 不在参数 '
                              f'{list(norm)} 的声明对象里')
        if fixed_gid in objects:
            return self._fail(STATUS_UNSUPPORTED_RELATION,
                              f'关系 {rel.get("id")} 的固定节点 {fixed_gid} 也被同一参数移动，'
                              f'两端同动无法反解')
        current = pending.get(norm)
        if current is None:
            current = _finite(get_path(self._base_config, norm), f'{list(norm)} 的当前值')
        scale = float(rec.get('scale', 1.0) or 1.0) or 1.0
        delta_mm = (target_mm - value) * direction
        wanted = float(current) + delta_mm / scale
        if not self._in_range(rec, wanted):
            return self._fail(STATUS_OUT_OF_RANGE,
                              f'关系 {rel.get("id")} 目标 {target_mm} mm（当前候选 {round(value, 4)} mm，'
                              f'{method}）需要 {list(norm)} = {round(wanted, 4)}，超出声明范围 '
                              f'[{rec.get("min")}, {rec.get("max")}]')
        return [{'param': rec, 'path': norm, 'value': wanted, 'base_value': float(current),
                 'current_mm': value, 'method': method, 'direction': direction,
                 'fixed': fixed_gid, 'moving': moving_gid}]

    @staticmethod
    def _relation_node(shape):
        """把本会话实测的显示几何包成父模块 geometry 认的快照节点。

        `bounds_mm` 是 mm 包围盒，`polyline_mm` 是已显示的折线顶点：父模块的
        `measure_relation` 要的就是这两样，语义才和场景快照完全一致。
        """
        return {'id': shape.get('gid'),
                'bounds_mm': list(shape.get('bbox_mm') or []),
                'polyline_mm': list(shape.get('points_mm') or []) or None,
                'measured': shape.get('bbox_mm') is not None,
                'fully_clipped': False}

    def _relation_measurement(self, rel, shapes):
        """用**父模块 figpact.geometry.measure_relation 的语义**量一条关系。

        返回 `(value_mm, method, reason)`：`reason` 非空表示量不了。align 是**同侧锚点展幅**
        （非负），gap 是边到边带符号间隙，宽高/容纳/分布各有自己的定义——会话不另立一套
        符号约定，否则同一个关系在场景和执行器里会是两个数。
        """
        kind = rel.get('kind') or 'gap'
        axis = rel.get('axis') or 'x'
        objects = list(rel.get('objects') or [])
        if len(objects) < 2:
            return None, None, '需要至少两个对象'
        missing = [gid for gid in objects if f'gid:{gid}' not in shapes]
        if missing:
            return None, None, f'{missing} 不在已测显示几何里'
        geometry = _core_module('geometry')
        nodes = [self._relation_node(shapes[f'gid:{gid}']) for gid in objects]
        try:
            result = geometry.measure_relation(kind, nodes, axis=axis,
                                               anchor=rel.get('anchor'),
                                               method=rel.get('method'))
        except Exception as error:
            return None, None, f'父模块测量抛错：{error}'
        if not isinstance(result, dict) or result.get('status') != 'OK' \
                or result.get('value_mm') is None:
            notes = '；'.join(str(n) for n in (result or {}).get('notes') or ())
            status = (result or {}).get('status') or 'UNMEASURED'
            return None, result.get('method') if isinstance(result, dict) else None, \
                f'父模块测量未通过（{status}）：{notes}'
        return float(result['value_mm']), str(result.get('method')), None

    def _relation_geometry(self, rel, shapes):
        """在给定几何上量一条关系，并给出**求解用**的带符号导数。

        返回 (value_mm, direction, method, fixed_gid, moving_gid)：`direction` 是
        「移动节点沿轴正向移动 1mm，测量值增加多少」，用同一套权威测量对 +1mm 位移做
        数值微分得到——align 的展幅在移动对象位于下侧时导数为 -1，位于上侧时为 +1，
        gap 的边到边间隙同理，全部交给 `measure_relation` 的定义说，不靠猜符号。
        量不了、或关系对移动节点不敏感（|导数| < 0.5）一律返回 (None, ...) 由调用方拒绝。
        """
        objects = list(rel.get('objects') or [])
        move = list(rel.get('move') or [])
        if len(objects) < 2:
            return None, None, '需要至少两个对象', None, None
        if move:
            fixed = [o for o in objects if o not in move]
            moving = [o for o in objects if o in move]
        else:
            fixed, moving = objects[:-1], objects[-1:]
        if len(fixed) != 1 or len(moving) != 1:
            return None, None, (f'需要一个固定节点和一个移动节点'
                                f'（固定 {fixed}，移动 {moving}）'), None, None
        fixed_gid, moving_gid = fixed[0], moving[0]
        axis = rel.get('axis') or 'x'
        if axis not in ('x', 'y'):
            return None, None, f'关系 {rel.get("id")} 的轴 {axis!r} 不支持反解', fixed_gid, moving_gid
        value, method, reason = self._relation_measurement(rel, shapes)
        if value is None:
            return None, None, reason, fixed_gid, moving_gid
        probe_mm = 1.0
        shifted = dict(shapes)
        shifted[f'gid:{moving_gid}'] = _shift_shape(
            shapes[f'gid:{moving_gid}'], probe_mm if axis == 'x' else 0.0,
            probe_mm if axis == 'y' else 0.0)
        probed, _, probe_reason = self._relation_measurement(rel, shifted)
        if probed is None:
            return None, None, f'关系对移动节点的位移不可判定：{probe_reason}', fixed_gid, moving_gid
        direction = (probed - value) / probe_mm
        if abs(direction) < 0.5:
            return (None, None,
                    f'关系 {rel.get("id")} 对 {moving_gid} 沿 {axis} 正向移动不敏感'
                    f'（∂值/∂位移 ≈ {round(direction, 6)}），不能反解',
                    fixed_gid, moving_gid)
        return value, direction, method, fixed_gid, moving_gid

    def _predicted_shapes(self, pending):
        """基线显示几何 + 目标（只允许 translate）推导出的候选几何；推不出返回 None。"""
        shapes = {key: dict(rec) for key, rec in self._baseline['shapes'].items()}
        offsets: dict[str, tuple] = {}
        for path, value in sorted(pending.items()):
            rec, status = self._param_of_path(path)
            if rec is None or rec.get('operation') != 'translate':
                return None
            axis = rec.get('axis')
            if axis not in ('x', 'y'):
                return None
            try:
                base_value = _finite(get_path(self._base_config, path), f'{list(path)} 的基线值')
            except (KeyError, ValueError):
                return None
            delta = (float(value) - base_value) * float(rec.get('scale', 1.0) or 1.0)
            # 平移的作用集合是**声明对象 + 后代闭包**（面板整体动，里面的图元跟着动）；
            # 每个 gid 只累加一次它所属控制对象的位移（子对象自己也有声明时相加）。
            for gid in self.owned_closure(rec.get('objects') or []):
                key = f'gid:{gid}'
                if key not in shapes:
                    if gid in (rec.get('objects') or []):
                        return None
                    continue
                dx, dy = offsets.get(key, (0.0, 0.0))
                offsets[key] = (dx + (delta if axis == 'x' else 0.0),
                                dy + (delta if axis == 'y' else 0.0))
        for key, (dx, dy) in offsets.items():
            if dx or dy:
                shapes[key] = _shift_shape(shapes[key], dx, dy)
        # 属于被平移坐标轴的**未注册**可见几何（刻度标签之类）同样跟着走：它们没有 gid，
        # 只能按「画在哪根轴」归属；不跟着平移就会拿它们当静止几何，对着错位比碰撞。
        axes_offsets = {}
        for key, (dx, dy) in offsets.items():
            rec = shapes.get(key)
            if key.startswith('gid:') and rec is not None and rec.get('container'):
                axes_offsets[rec.get('axes')] = (dx, dy)
        for key, rec in list(shapes.items()):
            if key.startswith('gid:'):
                continue
            if rec.get('kind') == 'figure_image_envelope':
                # 图幅图像的位置是脚本写死的图幅像素偏移：它不挂在任何坐标轴上，也不随画布/
                # 面板容器平移；只按自己声明的 gid 位移（那条路径在上面的 offsets 里）。
                continue
            offset = axes_offsets.get(rec.get('axes'))
            if offset and (offset[0] or offset[1]):
                shapes[key] = _shift_shape(shapes[key], offset[0], offset[1])
        return shapes

    # -- try_layout -------------------------------------------------------- #

    def try_layout(self, operations, *, revision=None):
        """一批绝对目标。失败不改状态；成功返回候选与验证等级。"""
        self._sync()
        if revision is not None and revision != self.revision:
            return self._fail(STATUS_STALE, f'revision 已过期（当前 {self.revision}）',
                              revision=self.revision, operations=list(operations)
                              if isinstance(operations, (list, tuple)) else [operations])
        resolved, failure = self._classify(operations)
        if failure is not None:
            failure.update(revision=self.revision, verification=None, changes=[],
                           affected_objects=[], relations=[], diagnostics=[],
                           science_unchanged=None)
            return failure
        goals = dict(self._goals)
        if any(item['kind'] == 'reset' for item in resolved):
            goals = {}
        changes = []
        for item in resolved:
            if item['kind'] == 'reset':
                continue
            previous = goals.get(item['path'])
            base_value = get_path(self._base_config, item['path'])
            goals[item['path']] = item['value']
            changes.append({'path': list(item['path']), 'key': item['param'].get('key'),
                            'from': base_value if previous is None else previous,
                            'to': item['value'], 'unit': item['param'].get('unit'),
                            'operation': item['param'].get('operation'),
                            'source': 'parameter' if item['kind'] == 'parameter' else 'relation'})
        previous_goals = self._goals
        self._goals = goals
        try:
            result = self._verify_layout(resolved, changes)
        except Exception:
            self._goals = previous_goals
            raise
        if result.get('status') not in (STATUS_OK,):
            self._goals = previous_goals
            result.setdefault('revision', self.revision)
            return result
        # 候选身份变了：上一帧缓存作废（reset 与新目标一样），下一次捕获重画。
        self._frame_cache = None
        self._frame_cache_key = None
        self._frame_cache_shapes = None
        result.update(revision=self.revision, changes=changes, goals=len(goals))
        return result

    def _verify_layout(self, resolved, changes):
        """候选 = 全部累积目标（不只本批）：等级判定必须看整张候选图。"""
        relation_ops = [(item['relation'], float(item['target_mm']))
                        for item in resolved if item['kind'] == 'relation']
        relation_ids = [rel.get('id') for rel, _ in relation_ops]
        goals = []
        for path, value in sorted(self._goals.items()):
            rec, status = self._param_of_path(path)
            if rec is None:
                return self._refuse(
                    STATUS_EFFECT_MISMATCH,
                    f'目标 {list(path)} 找不到声明记录（{status}），拒绝给出成功结论',
                    relation_ids=relation_ids,
                    diagnostics=['候选目标与当前布局契约不自洽；重载会话后重试'])
            goals.append({'path': path, 'value': value, 'param': rec})
        affected = []
        for goal in goals:
            for gid in goal['param'].get('objects') or []:
                if gid not in affected:
                    affected.append(gid)
        if not goals:
            return self._geometry_verify([], {}, affected, relation_ops, changes)
        if {goal['param'].get('operation') for goal in goals} != {'translate'}:
            return self._render_verify(affected, relation_ops, goals, changes)
        proofs, refused, unproved = {}, [], []
        for goal in goals:
            key = goal['param'].get('key') or str(goal['path'])
            proof = self._proofs.get(key)
            if proof is None:
                proof = self._prove_translation(goal['param'])
                self._proofs[key] = proof
            if proof.get('class') == PROOF_PROVED:
                proofs[goal['path']] = proof
            elif proof.get('class') == PROOF_UNSUPPORTED:
                unproved.append(proof)
            else:
                refused.append(proof)
        if refused:
            # 观测到的声明不符 / 没有效果：**明确拒绝**。退回渲染只会拿 QA 当挡箭牌，
            # 把「声明 2 mm 实际只动了 0.2 mm」粉饰成成功。
            return self._refuse_proofs(refused, affected, relation_ids)
        if unproved:
            render = self._render_verify(affected, relation_ops, goals, changes)
            render['diagnostics'] = list(render.get('diagnostics') or []) + [
                f'参数 {p.get("path")} 的 translate 声明无法用同渲染器解析容差证明'
                f'（{p.get("reason")}），改走真实重建 + 渲染验证' for p in unproved]
            return render
        return self._geometry_verify(goals, proofs, affected, relation_ops, changes)

    # -- 快车道：几何验证 --------------------------------------------------- #

    def _geometry_verify(self, goals, proofs, affected, relation_ops, changes):
        base_shapes = self._baseline['shapes']
        checks, diagnostics = [], []
        relation_ids = [rel.get('id') for rel, _ in relation_ops]
        candidates = self._predicted_shapes(self._goals)
        if candidates is None:
            return self._render_verify(affected, relation_ops, goals, changes,
                                       note='候选几何无法从基线 + 平移目标推导（对象缺失或轴未声明）')
        containment_keys = [key for key in sorted(candidates)
                            if key.startswith('gid:')
                            and _shapes_differ(base_shapes.get(key), candidates[key])]
        moved_keys = [key for key in containment_keys if not candidates[key].get('container')]
        moved_names = [key.split(':', 1)[1] for key in moved_keys]
        if not moved_names:
            checks.append({'check': 'degenerate', 'status': 'OK',
                           'detail': '目标等于基线值，候选与基线重合'})
        # 包含性：**只按作者声明的 `contain` 关系 + 实际裁切边界**判定。
        # 归属（nodes/groups 里的 parent）不是包含：坐标轴标题/图例/注释挂在面板下面，
        # 却本来就可以画在坐标框外（严格 QA 的 check_out_of_frame 也只盯注册折线与图例的裁切）。
        # 因此这里不发明「所有归属对象必须落在自己的 Axes 里」这条作者没写过的约束：
        # 画布是永远存在的外边界，被实际裁切的图元另外受自己坐标框的裁切边界约束。
        base_by_axes = {rec['axes']: rec['bbox_mm']
                        for rec in base_shapes.values() if rec.get('container')}
        by_axes = {rec['axes']: rec['bbox_mm']
                   for rec in candidates.values() if rec.get('container')}
        pre_existing_overflow = []
        for key in containment_keys:
            shape = candidates[key]
            bounds = []  # (边界来源, 候选框, 基线框)
            if shape.get('clipped') or shape['kind'] == 'legend_envelope':
                # 实际被裁切的图元（线/包络/图像默认 clip_on）：越出坐标框就是被裁掉的部分。
                # 图例没有裁切，但严格 QA 的 check_out_of_frame 本来就盯它，这里保持一致。
                bounds.append((f'{shape["gid"]} 所在坐标框（实际裁切边界）',
                               by_axes.get(shape['axes']), base_by_axes.get(shape['axes'])))
            for owner in self._container_gids(shape.get('gid')):
                holder = candidates.get(f'gid:{owner}')
                base_holder = base_shapes.get(f'gid:{owner}')
                bounds.append((f'声明的容器 {owner}',
                               None if holder is None else holder.get('bbox_mm'),
                               None if base_holder is None else base_holder.get('bbox_mm')))
            # 画布是永远在的外边界：任何被移动的可见几何都不许压出画布（量不出来就退回渲染验证）。
            if not any(frame == by_axes.get(None) for _, frame, _ in bounds):
                bounds.append(('画布边界', by_axes.get(None), base_by_axes.get(None)))
            for source, frame, base_frame in bounds:
                if frame is None:
                    return self._render_verify(
                        affected, relation_ops, goals, changes,
                        note=f'{shape["gid"]} 的包含性需要「{source}」，但那个框量不出来，'
                             f'不拿渲染 QA 顶替（也未按几何快车道放行）')
                r = shape['bbox_mm']
                overflow = max(frame[0] - r[0], frame[1] - r[1],
                               r[2] - frame[2], r[3] - frame[3])
                if overflow <= 1e-9:
                    continue
                base_overflow = None
                base_shape = base_shapes.get(key)
                if base_shape is not None and base_frame is not None:
                    b = base_shape['bbox_mm']
                    base_overflow = max(0.0, base_frame[0] - b[0], base_frame[1] - b[1],
                                        b[2] - base_frame[2], b[3] - base_frame[3])
                if base_overflow is not None and overflow <= base_overflow + TOL_SAME_RENDERER_MM:
                    # 基线里就已经压出这么多：既有布局，不是这次改动造成的新越界。
                    pre_existing_overflow.append({'object': shape['gid'], 'bound': source,
                                                  'overflow_mm': round(overflow, 4),
                                                  'baseline_overflow_mm': round(base_overflow, 4)})
                    continue
                detail = (f'{shape["gid"]} 越出{source} {round(overflow, 3)} mm'
                          + ('' if base_overflow is None
                             else f'；基线同一对象在该边界只压出 {round(base_overflow, 4)} mm'))
                checks.append({'check': 'containment', 'object': shape['gid'], 'status': 'FAIL',
                               'bound': source, 'overflow_mm': round(overflow, 4), 'detail': detail,
                               'pre_existing': pre_existing_overflow})
                return {'status': STATUS_GEOMETRY_REJECTED, 'verification': VERIFICATION_GEOMETRY,
                        'message': detail, 'checks': checks, 'science_unchanged': None,
                        'affected_objects': affected, 'relations': relation_ids,
                        'diagnostics': diagnostics, 'measured': {'method': 'shape_bbox_mm'},
                        'png': None}
        checks.append({'check': 'containment', 'status': 'OK',
                       'pre_existing': pre_existing_overflow,
                       'detail': f'{len(containment_keys)} 个移动对象都没有越出作者声明的容器'
                                 f'（画布外边界 + contain 关系 + 实际裁切边界，形状包围盒，mm）'
                                 + (f'；基线里已存在的越界 {len(pre_existing_overflow)} 处未加深'
                                    if pre_existing_overflow else '')})
        # 碰撞：动过的对象 vs 同一次构建的候选几何。
        # 基线里的**未注册**可见几何（刻度标签包络等，没有 gid，只能按轴归属）
        # 不进基线碰撞对：构建的 dpi/字体变了它们的包络就整体偏移——那是两次构建的
        # 环境差异，不是本次位移造成的碰撞（候选内部动/静比较不受影响）。
        moved_set = set(moved_keys)
        collisions, pre_existing, uncertainties, min_clear = [], [], [], None

        def _baseline_pair_gap(key, other_key):
            """基线几何上**同一对**的测量：用来区分「既有重叠」与「新碰撞」。"""
            left, right = base_shapes.get(key), base_shapes.get(other_key)
            if left is None or right is None:
                return None, None
            try:
                gap, method = shape_gap(left, right, bbox_gate_mm=0.5)
            except Exception:
                return None, None
            return round(gap, 4), method

        pairs = []
        for key in moved_keys:
            for other_key in sorted(base_shapes):
                other = base_shapes[other_key]
                if other_key == key or other.get('container') or other_key in moved_set:
                    continue
                if not other_key.startswith('gid:'):
                    # 基线里的未注册可见几何（刻度标签包络等）不进碰撞对：
                    # 它们按轴归属、随构建 dpi/字体整体偏移——那是两次构建的
                    # 环境差异，不是本次位移造成的碰撞。但图幅图像
                    # （`figure_image_envelope`）不挂任何坐标轴、不随轴环境
                    # 偏移，是真实存在的静止几何，必须参与碰撞测量。
                    if other.get('kind') != 'figure_image_envelope':
                        continue
                pairs.append((key, other_key, other))
            for other_key in sorted(moved_keys):
                if other_key <= key:
                    continue
                pairs.append((key, other_key, candidates[other_key]))
        for key, other_key, other in pairs:
            gap, method = shape_gap(candidates[key], other, bbox_gate_mm=0.5)
            pair = [candidates[key]['gid'] or key, other.get('gid') or other_key]
            if gap > 0.0:
                if min_clear is None or gap < min_clear:
                    min_clear = gap
                continue
            base_gap, base_method = _baseline_pair_gap(key, other_key)
            evidence = {'pair': pair, 'method': method, 'gap_mm': round(gap, 4),
                        'baseline_gap_mm': base_gap, 'baseline_method': base_method}
            unchanged_overlap = (base_gap is not None and base_gap <= 0.0
                                 and gap >= base_gap - TOL_SAME_RENDERER_MM)
            if base_gap is None:
                # 基线量不出来（对象当时不可测/不可比）：不自己拍板，也不偷偷放行 → 交渲染 QA。
                uncertainties.append(evidence)
            elif method == 'bbox_conservative':
                # 候选侧只是**包络下界**重叠：说不清形状是否真的相交。
                # 既有的重叠没加深 → 既有布局；变深/新增 → 交渲染 QA，不假装证明过。
                (pre_existing if unchanged_overlap else uncertainties).append(evidence)
            elif base_gap > 0.0:
                # 基线上同一对**确实分开**（哪怕只是 bbox 下界，也是真实下界），
                # 现在精确测量到相交 → 这是**新碰撞**，不是「基线没有同一套测量」。
                collisions.append(evidence)
            else:
                # 基线里同一对本来就重叠（例如科学波段窗口就在曲线后面）：既有布局。
                pre_existing.append(evidence)
        if collisions:
            detail = '测量的几何碰撞（基线里同一对并未重叠）：' + '; '.join(
                _collision_text(entry) for entry in collisions)
            checks.append({'check': 'collision', 'status': 'FAIL', 'pairs': collisions,
                           'pre_existing': pre_existing})
            return {'status': STATUS_GEOMETRY_REJECTED, 'verification': VERIFICATION_GEOMETRY,
                    'message': detail, 'checks': checks, 'science_unchanged': None,
                    'affected_objects': affected, 'relations': relation_ids,
                    'diagnostics': diagnostics, 'measured': {'method': 'shape_local_clearance'},
                    'png': None}
        if uncertainties:
            return self._render_verify(affected, relation_ops, goals, changes,
                                       note=f'无法精确测量的包络对 {len(uncertainties)} 组'
                                            f'（或基线没有同一套测量），交由渲染 QA 判定')
        if pre_existing:
            checks.append({'check': 'collision', 'status': 'OK', 'pairs': [],
                           'pre_existing': pre_existing,
                           'detail': f'移动后无**新**相交；基线里已存在的重叠 '
                                     f'{len(pre_existing)} 组（科学窗口/背景）状态未恶化'})
        else:
            checks.append({'check': 'collision', 'status': 'OK', 'pairs': [],
                           'pre_existing': [],
                           'detail': '移动后与其它可见几何无相交（折线按线段、包络按矩形下界）'})
        # 关系目标实测（在候选几何上，同一套测量语义）。
        relation_reports = []
        for rel, target_mm in relation_ops:
            value, method, reason = self._relation_measurement(rel, candidates)
            if value is None:
                return self._render_verify(affected, relation_ops, goals, changes,
                                           note=f'关系 {rel.get("id")} 在候选几何上不可测量（{reason}）')
            tolerance = TOL_SAME_RENDERER_MM
            ok = abs(value - target_mm) <= tolerance
            relation_reports.append({'id': rel.get('id'), 'kind': rel.get('kind'),
                                     'target_mm': target_mm, 'measured_mm': round(value, 4),
                                     'method': method, 'tolerance_mm': tolerance,
                                     'move': list(rel.get('move') or []),
                                     'status': 'OK' if ok else 'FAIL'})
            if not ok:
                detail = (f'关系 {rel.get("id")} 在 ±{tolerance} mm 内未达到目标：'
                          f'实测 {round(value, 4)} vs 目标 {target_mm}')
                checks.append({'check': 'relation', 'status': 'FAIL', 'detail': detail})
                return {'status': STATUS_GEOMETRY_REJECTED, 'verification': VERIFICATION_GEOMETRY,
                        'message': detail, 'checks': checks, 'science_unchanged': None,
                        'affected_objects': affected, 'relations': relation_reports,
                        'diagnostics': diagnostics, 'png': None}
            checks.append({'check': 'relation', 'status': 'OK',
                           'detail': f'{rel.get("id")} 实测 {round(value, 4)} mm（{method}）'})
        for item in proofs.values():
            checks.append({'check': 'translation_proof', 'status': 'OK',
                           'parameter': item.get('key'),
                           'descendants': item.get('descendants') or [],
                           'detail': f'真实 YAML 重建扰动验证：{item.get("probe")} → '
                                     f'观测位移 ({round(item.get("dx_mm", 0.0), 4)}, '
                                     f'{round(item.get("dy_mm", 0.0), 4)}) mm，'
                                     f'受影响集合 {item.get("affected")}'
                                     f'（后代 {len(item.get("descendants") or [])} 个跟随），'
                                     f'科学等值 {item.get("science_unchanged")}'})
        diagnostics.append('几何快车道：本等级**不是**完整渲染 QA（未重绘、未跑 blocking_problems）；'
                           '只做了声明的刚体位移 + 形状级局部间隙/包含/碰撞检查。')
        science_seen = [p.get('science_unchanged') for p in proofs.values()]
        if any(value is False for value in science_seen):
            science_state = False
        elif any(value is True for value in science_seen):
            science_state = True
        else:
            science_state = None
        return {'status': STATUS_OK, 'verification': VERIFICATION_GEOMETRY,
                'message': f'{len(changes)} 项声明位移通过形状级局部检查',
                'checks': checks, 'affected_objects': affected,
                'relations': relation_reports, 'diagnostics': diagnostics,
                'science_unchanged': science_state,
                'science_note': '位移路径的科学等值来自首次真实重建扰动证明，未在本次候选上重测',
                'min_clearance_mm': None if min_clear is None else round(min_clear, 4),
                'png': None}

    def _prove_translation(self, rec):
        """真实 YAML 重建扰动，证明声明本身：受影响集合、mm 位移/方向、科学等值。

        这一步就是「声明 ≠ 绑定生效」的闸门，结论分三类：

        - `PROVED`：声明的作用集合/轴/物理量都在真实重建里被观测到，科学指纹不变。
        - `UNSUPPORTED`：**证明不了**（缺 axis、对象不在已测几何里、扰动量太小、扰动
          被脚本拒绝……）。这类允许退回渲染验证，但退回后仍要观测声明的落实。
        - `OBSERVED_MISMATCH` / `OBSERVED_NO_EFFECT`：真实重建里**观测到**声明不符或
          完全没有效果（错标尺、没接线、牵连未声明对象、科学指纹变了）。这类是事实，
          调用方必须明确拒绝，绝不许退回渲染验证后拿 QA 当成功。

        比较用的是**解析容差** `TOL_SAME_RENDERER_MM`（1 µm）：两端同一次构建、同一 DPI、
        同一字体，位移只是 ScaledTranslation，包围盒/折线位移是解析量（实测 1e-9 级）。
        因此声明 scale 写错一个数量级（例如 0.1× 却按 1.0 生效，或干脆没接线）都会露馅。
        跨 DPI / 跨字体的栅格不确定度（`TOL_ENVELOPE_MM_PER_PX`）不在这里用：
        那种容差只能说明「变了」，不能用来证明位移量。
        """
        key = rec.get('key')
        path = _norm_path(rec['path'])
        try:
            base_value = _finite(get_path(self._base_config, path), f'{list(path)} 的基线值')
        except (KeyError, ValueError) as error:
            return {'class': PROOF_OBSERVED_MISMATCH, 'status': STATUS_ERROR,
                    'path': list(path), 'key': key,
                    'reason': f'基线配置里读不到：{error}'}
        delta = self._probe_delta(rec, base_value)
        if delta is None:
            return {'class': PROOF_UNSUPPORTED, 'status': STATUS_UNSUPPORTED_PROOF,
                    'path': list(path), 'key': key,
                    'reason': '声明范围/单位无法给出有界的可测扰动'}
        probe = base_value + delta
        cfg = copy.deepcopy(self._base_config)
        set_path(cfg, path, probe)
        try:
            fig, reg = self.build_candidate(cfg)
        except Exception as error:
            return {'class': PROOF_UNSUPPORTED, 'status': STATUS_UNSUPPORTED_PROOF,
                    'path': list(path), 'key': key,
                    'reason': f'扰动重建失败：{error}'}
        try:
            after_shapes = drawn_shapes(fig, reg, include_frames=True)
            after_science = self._capture_science(fig, reg)
            after_styles = self._styles(fig, reg)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)
        before_shapes = self._baseline['shapes']
        declared = list(rec.get('objects') or [])
        axis = rec.get('axis')
        scale = float(rec.get('scale', 1.0) or 1.0)
        tol = TOL_SAME_RENDERER_MM
        expected_mm = delta * scale
        if not declared:
            return {'class': PROOF_UNSUPPORTED, 'status': STATUS_UNSUPPORTED_PROOF,
                    'path': list(path), 'key': key,
                    'reason': 'translate 声明没有 objects，无法观测作用集合'}
        if abs(expected_mm) < MIN_PROBE_MM:
            return {'class': PROOF_UNSUPPORTED, 'status': STATUS_UNSUPPORTED_PROOF,
                    'path': list(path), 'key': key,
                    'reason': f'扰动的物理量 {round(abs(expected_mm), 6)} mm 小于可测下限 '
                              f'{MIN_PROBE_MM} mm，不能证明位移绑定'}
        if axis not in ('x', 'y'):
            return {'class': PROOF_UNSUPPORTED, 'status': STATUS_UNSUPPORTED_PROOF,
                    'path': list(path), 'key': key,
                    'reason': f'translate 声明缺少可用的 axis（{axis!r}）'}
        per_object, observed, unsupported = {}, [], []
        for gid in declared:
            name = f'gid:{gid}'
            if name not in before_shapes or name not in after_shapes:
                unsupported.append(f'{gid} 不在已测显示几何里')
                continue
            if before_shapes[name].get('dpi') != after_shapes[name].get('dpi'):
                unsupported.append(f'{gid} 比较两端 DPI 不同'
                                   f'（{before_shapes[name].get("dpi")} vs '
                                   f'{after_shapes[name].get("dpi")}），'
                                   f'不能用解析容差证明物理位移')
                continue
            issues, entry, along = _rigid_delta(before_shapes[name], after_shapes[name],
                                                axis, expected_mm, tol, gid)
            per_object[gid] = {'dx_mm': round(entry['dx_mm'], 6), 'dy_mm': round(entry['dy_mm'], 6),
                               'dw_mm': round(entry['dw_mm'], 6),
                               'dh_mm': round(entry['dh_mm'], 6),
                               'tol_mm': tol, 'method': entry['method'],
                               'moved_mm': round(abs(along), 6)}
            observed.extend(issues)
        # 声明的作用集合是**声明对象 + 后代闭包**：面板整体平移时，面板里的图像/比例尺/文字
        # 跟着走是布局的一部分（作者用 parent 声明归属，不必把它们再抄进 objects）；
        # 但也正因为如此，后代必须**跟着走**，而不在闭包里的无关兄弟必须原地不动。
        owned = self.owned_closure(declared)
        for gid in sorted(set(owned) - set(declared)):
            name = f'gid:{gid}'
            if name not in before_shapes or name not in after_shapes:
                continue
            issues, entry, _ = _rigid_delta(before_shapes[name], after_shapes[name],
                                            axis, expected_mm, tol, f'{gid}（声明对象的后代）')
            observed.extend(issues)
        claimed_keys = _owned_keys(before_shapes, owned) | _owned_keys(after_shapes, owned)
        added = sorted(set(after_shapes) - set(before_shapes))
        removed = sorted(set(before_shapes) - set(after_shapes))
        structure = added + removed
        changed_all = _changed_shape_keys(before_shapes, after_shapes)
        undeclared = sorted(set(changed_all) - claimed_keys - set(structure))
        if undeclared:
            observed.append(f'牵连了未声明、也不是声明对象后代的可见几何：{undeclared}')
        if structure:
            observed.append(f'重建改变了可见结构：新增 {added}，消失 {removed}')
        science_ok, science_notes = self._compare_science(self._baseline['science'], after_science)
        if science_ok is False:
            observed.append('扰动重建改变了科学指纹：' + '; '.join(map(str, science_notes)))
        idle = sorted(gid for gid, entry in per_object.items()
                      if entry['moved_mm'] <= tol)
        if (per_object and len(per_object) == len(declared) and not unsupported
                and len(idle) == len(per_object) and not changed_all and not structure
                and science_ok is True and after_styles == self._baseline['styles']):
            return {'class': PROOF_OBSERVED_NO_EFFECT, 'status': STATUS_NO_EFFECT,
                    'path': list(path), 'key': key,
                    'reason': '真实 YAML 扰动后，显示几何、样式与科学载荷全部未变化',
                    'probe': probe, 'measured': per_object}
        if observed:
            status = (STATUS_SCIENCE_VIOLATION if science_ok is False
                      else STATUS_EFFECT_MISMATCH)
            return {'class': PROOF_OBSERVED_MISMATCH, 'status': status,
                    'path': list(path), 'key': key, 'reason': '；'.join(observed),
                    'probe': probe, 'measured': per_object,
                    'science_unchanged': science_ok}
        if per_object and len(idle) == len(per_object):
            return {'class': PROOF_OBSERVED_NO_EFFECT, 'status': STATUS_NO_EFFECT,
                    'path': list(path), 'key': key,
                    'reason': f'真实重建扰动 {base_value} → {probe} 后，声明的作用对象 '
                              f'{declared} 在毫米几何上没有任何可测位移（解析容差 {tol} mm）：'
                              f'参数没有接线或该键不被绘图代码读取',
                    'probe': probe, 'measured': per_object}
        if idle:
            return {'class': PROOF_OBSERVED_MISMATCH, 'status': STATUS_EFFECT_MISMATCH,
                    'path': list(path), 'key': key,
                    'reason': f'声明的作用对象没有全部响应：{idle} 没有位移'
                              f'（其余 {sorted(set(per_object) - set(idle))} 有）',
                    'probe': probe, 'measured': per_object}
        if unsupported:
            return {'class': PROOF_UNSUPPORTED, 'status': STATUS_UNSUPPORTED_PROOF,
                    'path': list(path), 'key': key, 'reason': '；'.join(unsupported),
                    'probe': probe, 'measured': per_object}
        return {'class': PROOF_PROVED, 'status': STATUS_OK, 'key': key, 'path': list(path),
                'probe': probe,
                'delta_value': delta, 'expected_mm': round(expected_mm, 4), 'axis': axis,
                'dx_mm': round(sum(v['dx_mm'] for v in per_object.values()) / len(per_object), 4),
                'dy_mm': round(sum(v['dy_mm'] for v in per_object.values()) / len(per_object), 4),
                'affected': declared, 'affected_count': len(per_object),
                'descendants': sorted(set(owned) - set(declared)),
                'method': 'real_yaml_rebuild_probe',
                'tolerances_mm': sorted({v['tol_mm'] for v in per_object.values()}),
                'science_unchanged': True, 'science_notes': science_notes}

    def _probe_delta(self, rec, base_value):
        """挑一个有界、可测（≥ MIN_PROBE_MM 物理量）的扰动量。"""
        unit = rec.get('unit') or 'mm'
        if unit not in ('mm', 'pt'):
            return None
        scale = float(rec.get('scale', 1.0) or 1.0)
        per_unit_mm = 1.0 if unit == 'mm' else MM_PER_INCH / 72.0
        lo, hi = rec.get('min'), rec.get('max')
        for magnitude in (1.0, 2.0, 3.0):
            if abs(magnitude * scale * per_unit_mm) < MIN_PROBE_MM:
                continue
            for sign in (1.0, -1.0):
                candidate = base_value + sign * magnitude
                if self._in_range(rec, candidate):
                    return sign * magnitude
        return None

    # -- 渲染验证 ---------------------------------------------------------- #

    def _figure_image_canvas_check(self, base_shapes, shapes, tol):
        """候选里**新**压出画布的图幅图像 → 拒绝结果；没有就返回 None。

        图幅图像的像素由 Agg 按画布裁掉（`FigureImage.make_image` 拿画布当 clip），所以
        「新压出画布」= 把受保护的像素悄悄切掉一块。判据只有**实测的显示几何**（不读 YAML），
        规则与几何快车道的画布边界一致：基线里本来就压出去的不算新增，只有这次改动加深了才
        拒绝；几何或画布边界量不出来时也拒绝 —— 绝不拿「没测到」冒充「没越界」。
        几何快车道只看得见注册 gid 的对象，这条补上真实重建里**未注册**的图幅图像。
        """
        keys = sorted(key for key, rec in shapes.items()
                      if rec.get('kind') == 'figure_image_envelope')
        if not keys:
            return None
        canvas, base_canvas = _canvas_bounds(shapes), _canvas_bounds(base_shapes)
        for key in keys:
            rec = shapes[key]
            gid = rec.get('gid')
            name = gid or f'未注册的图幅图像（{key}）'
            box = rec.get('bbox_mm')
            base = base_shapes.get(key)
            base_box = base.get('bbox_mm') if isinstance(base, dict) else None
            if box is None or canvas is None:
                return self._refuse(
                    STATUS_GEOMETRY_REJECTED,
                    f'{name} 或画布边界的显示几何量不出来：拒绝把「没测到」当成「没越界」',
                    checks=[{'check': 'figure_image_canvas', 'object': gid or key,
                             'status': 'UNMEASURED'}],
                    affected=[gid] if gid else [])
            overflow = max(canvas[0] - box[0], canvas[1] - box[1],
                           box[2] - canvas[2], box[3] - canvas[3])
            if overflow <= tol:
                continue
            base_overflow = None
            if base_box is not None and base_canvas is not None:
                base_overflow = max(0.0, base_canvas[0] - base_box[0],
                                    base_canvas[1] - base_box[1],
                                    base_box[2] - base_canvas[2], base_box[3] - base_canvas[3])
            if base_overflow is not None and overflow <= base_overflow + tol:
                continue
            return self._refuse(
                STATUS_GEOMETRY_REJECTED,
                f'{name} 压出画布 {round(overflow, 3)} mm：画布外的像素会被直接裁掉',
                checks=[{'check': 'figure_image_canvas', 'object': gid or key, 'status': 'FAIL',
                         'overflow_mm': round(overflow, 4),
                         'baseline_overflow_mm': (None if base_overflow is None
                                                  else round(base_overflow, 4))}],
                affected=[gid] if gid else [])
        return None

    def _audit_candidate(self, goals, relation_ops, shapes, styles, png_b64):
        """在**真实重建出来的**候选上核对每一条声明（几何 / 样式 / 关系 / 产物）。

        返回 `(refused, checks, diagnostics)`。`refused` 非空时调用方必须原样返回：退回渲染
        验证不等于放弃观测，观测不到声明落实（没接线、错标尺、牵连未声明对象）就是显式拒绝。
        """
        base_shapes = self._baseline['shapes']
        tol = TOL_SAME_RENDERER_MM
        moved = _changed_shape_keys(base_shapes, shapes)
        styled = _changed_style_gids(self._baseline['styles'] or {}, styles or {})

        def raster_changed():
            baseline_digest = self._baseline.get('png_digest')
            if not baseline_digest or not png_b64:
                return False
            return hashlib.sha256(base64.b64decode(png_b64)).hexdigest() != baseline_digest

        def observed_something():
            return bool(moved or styled or raster_changed())

        # 整批都是刚体平移时，闭包之外的可见几何动一下就是新问题（混批不做这种强断言）。
        strict_scope = bool(goals) and all(goal['param'].get('operation') == 'translate'
                                           for goal in goals)
        claimed = set()
        if strict_scope:
            for goal in goals:
                owned = self.owned_closure(goal['param'].get('objects') or [])
                claimed |= _owned_keys(shapes, owned) | _owned_keys(base_shapes, owned)

        checks, diagnostics = [], []
        # 图幅图像由画布直接裁掉：候选里**新**压出画布就是切掉一块受保护的像素。
        # 这与几何快车道的画布边界是同一条规则，但这里看的是**真实重建**的候选，
        # 连没有 gid 的图幅图像也一起核对。
        canvas_refusal = self._figure_image_canvas_check(base_shapes, shapes, tol)
        if canvas_refusal is not None:
            return canvas_refusal, checks, diagnostics
        for goal in goals:
            rec, path, value = goal['param'], goal['path'], goal['value']
            key = rec.get('key') or str(list(path))
            declared = [gid for gid in (rec.get('objects') or []) if gid]
            try:
                base_raw = get_path(self._base_config, path)
            except KeyError as error:
                return self._refuse(STATUS_EFFECT_MISMATCH,
                                    f'{key}: 基线配置里读不到目标：{error}'), checks, diagnostics
            pair = _pair_of(value)
            if pair is not None:
                # 2D 位移目标：只有**两边都是同一形状**（一对有限数字）才谈得上比较；
                # 基线不是这个形状就是声明与配置不自洽，明确拒绝而不是硬算。
                base_pair = _pair_of(base_raw)
                if base_pair is None:
                    return self._refuse(
                        STATUS_EFFECT_MISMATCH,
                        f'{key}: 目标是 2D 位移对，但基线配置里 {list(path)} = {base_raw!r} '
                        f'不是一对数字（声明与配置不自洽）'), checks, diagnostics
                if base_pair == pair:
                    checks.append({'check': 'declared_effect', 'parameter': key, 'status': 'OK',
                                   'detail': '目标等于基线的当前值，没有需要观测的变化'})
                    continue
            else:
                try:
                    base_value = _finite(base_raw, f'{list(path)} 的基线值')
                except ValueError as error:
                    return self._refuse(STATUS_EFFECT_MISMATCH,
                                        f'{key}: 基线配置里读不到目标：{error}'), checks, diagnostics
                if float(value) == base_value:
                    checks.append({'check': 'declared_effect', 'parameter': key, 'status': 'OK',
                                   'detail': '目标等于基线的当前值，没有需要观测的变化'})
                    continue
            if rec.get('operation') == 'translate':
                refused, translate_checks, translate_notes = self._audit_translation(
                    goal, key, declared, shapes, tol, observed_something,
                    moved=moved, claimed=claimed, strict_scope=strict_scope)
                if refused is not None:
                    return refused, checks, diagnostics
                checks.extend(translate_checks)
                diagnostics.extend(translate_notes)
                continue
            responded = sorted(gid for gid in declared
                               if f'gid:{gid}' in moved or gid in styled)
            if not declared:
                return self._refuse(STATUS_UNSUPPORTED_PROOF,
                                    f'{key}: {rec.get("operation")} 声明没有 objects，'
                                    f'无法观测作用集合是否落实'), checks, diagnostics
            if responded:
                checks.append({'check': 'declared_effect', 'parameter': key, 'status': 'OK',
                               'detail': f'真实重建后声明对象里有可测变化：{responded}'})
                continue
            if raster_changed():
                checks.append({'check': 'declared_effect', 'parameter': key, 'status': 'OK',
                               'detail': f'声明对象 {declared} 在毫米几何/样式上没观察到变化，'
                                         f'但重建产物（栅格）确实变了'})
                diagnostics.append(f'{key}: 声明的作用对象 {declared} 在毫米几何/样式上不可观测，'
                                   f'结论依据重建产物的栅格变化，不是毫米级证明')
                continue
            return self._refuse(
                STATUS_NO_EFFECT,
                f'{key}: 真实重建后声明的作用对象 {declared} 在毫米几何、样式与产物上都没有变化，'
                f'参数没有生效（没接线 / 该键不被绘图代码读取 / 取值恰好等于基线）'), checks, diagnostics
        for rel, target in relation_ops:
            value, method, reason = self._relation_measurement(rel, shapes)
            if value is None:
                if not observed_something():
                    return self._refuse(
                        STATUS_NO_EFFECT,
                        f'关系 {rel.get("id")} 在真实重建的候选上不可测量（{reason}），'
                        f'连产物都没有变化'), checks, diagnostics
                note = (f'关系 {rel.get("id")} 在本地显示几何里不可测量（{reason}），'
                        f'本次只核对到重建产物确有变化，没有毫米级结论')
                checks.append({'check': 'relation', 'status': 'UNVERIFIED',
                               'id': rel.get('id'), 'target_mm': target, 'detail': note})
                diagnostics.append(note)
                continue
            if abs(value - float(target)) > tol:
                return self._refuse(
                    STATUS_GEOMETRY_REJECTED,
                    f'关系 {rel.get("id")} 未在 ±{tol} mm 内达到目标：实测 {round(value, 4)} '
                    f'vs 目标 {target} mm（{method}）'), checks, diagnostics
            checks.append({'check': 'relation', 'status': 'OK', 'id': rel.get('id'),
                           'measured_mm': round(value, 4), 'target_mm': target,
                           'tolerance_mm': tol, 'method': method,
                           'move': list(rel.get('move') or []),
                           'detail': f'真实重建的候选上实测 {round(value, 4)} mm'})
        return None, checks, diagnostics

    def _audit_translation(self, goal, key, declared, shapes, tol, observed_something,
                           moved=(), claimed=(), strict_scope=False):
        """在真实重建的候选上核对一条 translate 声明；返回 `(refused, checks, diagnostics)`。

        声明的作用对象**全部可测**时不许打折：轴、物理量、刚体性、作用集合都要对上。
        声明的作用集合是**声明对象 + 后代闭包**：后代跟着走才算落实，闭包之外的可见几何
        动一下就是新问题（`strict_scope` 时按整批都是刚体平移来核对）。
        只有「本地显示几何测不到这些对象」（整块坐标轴/画布这类容器）才降级为
        `UNVERIFIED` 结论——那时仍要求重建产物确有可测变化，否则就是没接线。
        """
        rec, path, value = goal['param'], goal['path'], goal['value']
        axis, unit = rec.get('axis'), rec.get('unit')
        if not declared:
            return self._refuse(STATUS_UNSUPPORTED_PROOF,
                                f'{key}: translate 声明没有 objects，无法观测作用集合'), [], []
        if axis not in ('x', 'y') or unit not in ('mm', 'pt'):
            return self._refuse(STATUS_UNSUPPORTED_PROOF,
                                f'{key}: translate 声明缺少可用的轴/单位'
                                f'（axis={axis!r}, unit={unit!r}），无法观测物理目标'), [], []
        base_shapes = self._baseline['shapes']
        base_value = _finite(get_path(self._base_config, path), f'{list(path)} 的基线值')
        per_unit_mm = 1.0 if unit == 'mm' else MM_PER_INCH / 72.0
        scale = float(rec.get('scale', 1.0) or 1.0)
        expected_mm = (float(value) - base_value) * scale * per_unit_mm
        measured, idle, wrong, unmeasured = [], [], [], []
        for gid in declared:
            name = f'gid:{gid}'
            if name not in shapes or name not in base_shapes:
                unmeasured.append(gid)
                continue
            entry = shape_delta(base_shapes[name], shapes[name])
            along, across = ((entry['dx_mm'], entry['dy_mm']) if axis == 'x'
                             else (entry['dy_mm'], entry['dx_mm']))
            if not entry['size_stable']:
                wrong.append(f'{gid} 的包围盒尺寸变了 ({round(entry["dw_mm"], 4)}, '
                             f'{round(entry["dh_mm"], 4)}) mm，不是声明中的刚体平移')
                continue
            if abs(across) <= tol and abs(along) <= tol:
                idle.append(gid)
                continue
            measured.append(gid)
            if abs(across) > tol:
                wrong.append(f'{gid} 出现了非声明轴（{axis}）位移 {round(across, 6)} mm')
            elif abs(along - expected_mm) > tol:
                wrong.append(f'{gid} 实测位移 {round(along, 6)} mm 与声明物理量 '
                             f'{round(expected_mm, 6)} mm 不符（同渲染器解析容差 {tol} mm）')
        owned = self.owned_closure(declared)
        for gid in sorted(set(owned) - set(declared)):
            name = f'gid:{gid}'
            if name not in shapes or name not in base_shapes:
                continue
            issues, _, _ = _rigid_delta(base_shapes[name], shapes[name], axis, expected_mm, tol,
                                        f'{gid}（声明对象的后代）')
            wrong.extend(issues)
        if strict_scope:
            strays = sorted(key_ for key_ in moved if key_ not in claimed)
            if strays:
                wrong.append(f'牵连了未声明、也不是声明对象后代的可见几何：{strays}')
        if wrong:
            return self._refuse(STATUS_EFFECT_MISMATCH, f'{key}: ' + '；'.join(wrong)), [], []
        if measured and len(idle) == len(measured):
            return self._refuse(STATUS_NO_EFFECT,
                                f'{key}: 真实重建后声明的作用对象 {measured} 没有任何可测位移，'
                                f'参数没有接线或该键不被绘图代码读取'), [], []
        if idle:
            return self._refuse(STATUS_EFFECT_MISMATCH,
                                f'{key}: 声明的作用对象没有全部响应：{idle} 没有位移，'
                                f'{sorted(set(measured) - set(idle))} 有'), [], []
        if not measured:
            if not observed_something():
                return self._refuse(STATUS_NO_EFFECT,
                                    f'{key}: 真实重建后连产物都没变（声明的作用对象 '
                                    f'{unmeasured} 在本地显示几何里也不可测），参数没有生效'), [], []
            note = (f'{key}: 声明的作用对象 {unmeasured} 在本地显示几何里不可测'
                    f'（坐标轴/画布这类容器），本次只核对到重建产物/样式确有变化，'
                    f'没有毫米级结论')
            return None, [{'check': 'declared_translation', 'parameter': key,
                           'status': 'UNVERIFIED', 'axis': axis, 'unit': unit,
                           'objects': unmeasured,
                           'detail': note}], [note]
        check = {'check': 'declared_translation', 'parameter': key, 'status': 'OK',
                 'axis': axis, 'unit': unit, 'expected_mm': round(expected_mm, 4),
                 'tolerance_mm': tol, 'objects': measured,
                 'detail': f'真实重建里观测到 {sorted(measured)} 沿 {axis} 位移 '
                           f'{round(expected_mm, 4)} mm（同渲染器解析容差 {tol} mm）'}
        notes = []
        if unmeasured:
            note = (f'{key}: 声明的作用对象 {unmeasured} 在本地显示几何里不可测，'
                    f'未纳入毫米级核对')
            check = {**check, 'status': 'UNVERIFIED', 'unmeasured': unmeasured}
            notes.append(note)
        return None, [check], notes

    def _render_verify(self, affected, relation_ops, goals, changes, note=None):
        """真实重建 + 渲染 QA；**先**在实际候选上核对声明，再谈 QA 与科学指纹。

        `goals` 是本次判定涉及的全部参数目标，`relation_ops` 是 (关系, 目标 mm) 列表：
        退回渲染不等于降低标准，声明的物理量、作用集合、单位换算与关系目标都要观测到。
        """
        diagnostics = [note] if note else []
        relation_ids = [rel.get('id') for rel, _ in relation_ops]
        config = self.candidate_config
        try:
            fig, reg = self.build_candidate(config)
        except Exception as error:
            return {'status': STATUS_BUILD_FAILED, 'verification': None,
                    'message': f'候选配置被脚本拒绝：{error}', 'checks': [], 'diagnostics': diagnostics,
                    'affected_objects': affected, 'relations': list(relation_ids),
                    'science_unchanged': None}
        revision = self.revision
        try:
            payload = self._render_payload(fig, reg, revision)
            shapes = drawn_shapes(fig, reg, include_frames=True)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)
        refused, audit_checks, audit_notes = self._audit_candidate(
            goals, relation_ops, shapes, payload['styles'], payload.get('png'))
        diagnostics.extend(audit_notes)
        if refused is not None:
            refused['revision'] = revision
            refused['affected_objects'] = affected
            refused['relations'] = list(relation_ids)
            refused['diagnostics'] = list(refused.get('diagnostics') or []) + diagnostics
            refused['checks'] = list(refused.get('checks') or []) + audit_checks
            return refused
        self._preview_cache[revision] = payload
        science_ok, science_notes = self._compare_science(self._baseline['science'],
                                                          payload['science'])
        if science_ok is False:
            return {'status': STATUS_SCIENCE_VIOLATION, 'verification': VERIFICATION_RENDER,
                    'message': '候选改变了科学指纹：' + '; '.join(map(str, science_notes)),
                    'checks': audit_checks,
                    'diagnostics': diagnostics + list(map(str, science_notes)),
                    'affected_objects': affected, 'relations': list(relation_ids),
                    'science_unchanged': False, 'qa': payload['qa'], 'qa_kind': payload['qa_kind'],
                    'png': None}
        base_keys = self._qa_keys(self._baseline['qa']['qa'])
        new_keys = self._qa_keys(payload['qa'])
        added = [problem for problem, key in zip(payload['qa'], new_keys) if key not in base_keys]
        status = STATUS_QA_BLOCKED if added else STATUS_OK
        if added:
            message = f'候选新增 {len(added)} 条 QA 阻断项'
        else:
            message = f'候选渲染通过（{payload["qa_kind"]}，基线原有 {len(base_keys)} 条未变）'
        checks = audit_checks + [{'check': 'render_qa', 'status': 'FAIL' if added else 'OK',
                                  'qa_kind': payload['qa_kind'], 'new': added,
                                  'baseline_count': len(base_keys),
                                  'candidate_count': len(payload['qa'])}]
        return {'status': status, 'verification': VERIFICATION_RENDER, 'message': message,
                'checks': checks, 'diagnostics': diagnostics,
                'affected_objects': affected, 'relations': list(relation_ids),
                'science_unchanged': science_ok, 'science_notes': science_notes,
                'qa': payload['qa'], 'qa_kind': payload['qa_kind'],
                'new_qa': added, 'png': None}

    def _render_payload(self, fig, reg, revision):
        import matplotlib as mpl
        buf = io.BytesIO()
        with mpl.rc_context({'savefig.bbox': None}):
            fig.savefig(buf, format='png', dpi=fig.dpi, bbox_inches=None)
        science = self._capture_science(fig, reg)
        qa_payload = self._qa(fig)
        return {'scope': self.scope, 'revision': revision,
                'png': base64.b64encode(buf.getvalue()).decode('ascii'),
                'inventory': self._inventory(fig, reg), 'qa': qa_payload['qa'],
                'qa_kind': qa_payload['qa_kind'],
                'relations': list(getattr(fig, '_figpact_relations', []) or []),
                'space': list(getattr(fig, '_figpact_space', []) or []),
                'science': science, 'styles': self._styles(fig, reg)}

    def _inventory(self, fig, reg):
        from figpact.inventory import inventory
        with redirect_stdout(io.StringIO()):
            return inventory(fig, reg)

    # -- 预览 -------------------------------------------------------------- #

    def render_preview(self, *, revision=None):
        """渲染候选预览；同一 revision 命中缓存，不重复构建。"""
        self._sync()
        if revision is not None and revision != self.revision:
            raise StaleRevision(f'revision 已过期：请求 {revision}，当前 {self.revision}')
        current = self.revision
        cached = self._preview_cache.get(current)
        if cached is not None:
            payload = dict(cached)
            payload['cached'] = True
            return payload
        fig, reg = self.build_candidate(self.candidate_config)
        try:
            payload = self._render_payload(fig, reg, current)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)
        self._preview_cache[current] = payload
        out = dict(payload)
        out['cached'] = False
        return out
    # -- 同帧捕获 / 导出（G0+G1 纵向切片：worker 权威，单 Figure 同 draw） --------

    def capture_frame(self, *, revision=None):
        """Worker 权威的同源帧：实际候选 Figure 上一次 Agg draw 的 PNG+Scene。

        同一次 :func:`figpact.inspector.capture_figure` 绘制的 PNG 与 Scene（同一
        renderer、同一 draw），绝不把 ``render_preview`` 的 savefig PNG 与另一次
        draw 的 snapshot 拼成一帧。``qa``/``science`` 是同一候选 Figure 对象上的
        实测证据（同一构建，不是重建前后拼凑）；``required_content`` 这类判定由
        消费方用 Scene 自行查找，本帧只给事实。``qa`` 是绝对 QA 列表（候选实际
        的阻断项/警告项），不是「相对基线无新增」——「无新增」不等于安全，策略由
        消费方（Render API）自行应用。

        返回在 Inspector 帧原样字段上追加的嵌套 provenance：
        ``candidate_revision``/``revision``（候选配置哈希）、``source_revision``、
        ``base_config_revision``、``scope``、``science``（``{verified, digest}``）、
        ``qa``/``qa_kind``、``evidence``（``render``/``persistence``/``host``/
        ``export_page``；首轮 ``host`` 恒为 ``NOT_CONNECTED``，
        ``export_page`` 恒为 ``NOT_RUN``）。
        """
        self._sync()
        if revision is not None and revision != self.revision:
            raise StaleRevision(f'revision 已过期：请求 {revision}，当前 {self.revision}')
        current = self.revision
        key = (current, self._source_rev, self.base_config_revision)
        cached = self._frame_cache
        if cached is not None and self._frame_cache_key == key:
            # 精确同一候选/同一源/同一基线：同一帧（深拷贝防调用方篡改缓存）。
            return copy.deepcopy(cached)
        fig, held = self.build_candidate(self.candidate_config)
        try:
            from figpact.inspector import capture_figure
            # Inspector settles legal native view windows before its internal
            # science baseline; pin baseline AFTER first capture (its draw-time
            # guard already covers draw drift). Compare QA/shapes/recapture to it.
            frame = capture_figure(fig, held, scope=self.scope, contract=self.contract,
                                   science_manifest=self.science_manifest,
                                   source_revision=self._source_rev)
            base_science = self._capture_science(fig, held)
            # QA/科学证据必须与最终 PNG+Scene 同一 draw 状态，且后续绘制不得
            # 静默改变已捕获帧：QA/形状辅助绘制后做同 Figure 二次捕获并比较
            # PNG+Scene 哈希，漂移即拒绝（不拼接不同渲染）。
            qa_payload = self._qa(fig)
            if self._capture_science(fig, held).get('digest') != base_science.get('digest'):
                raise SessionError('QA 绘制改变了科学指纹，拒绝出帧')
            shapes = drawn_shapes(fig, held, include_frames=True)
            frame2 = capture_figure(fig, held, scope=self.scope, contract=self.contract,
                                    science_manifest=self.science_manifest,
                                    source_revision=self._source_rev)
            if frame2.get('png_sha256') != frame.get('png_sha256') \
                    or frame2.get('scene_sha256') != frame.get('scene_sha256') \
                    or frame2.get('frame_revision') != frame.get('frame_revision'):
                raise StaleRevision('候选 Figure 在捕获后发生绘制漂移，拒绝陈旧帧')
            science = self._capture_science(fig, held)
            if science.get('digest') != base_science.get('digest'):
                raise SessionError('二次捕获后科学指纹变化，拒绝出帧')
            frame['candidate_revision'] = current
            frame['revision'] = current
            frame['source_revision'] = self._source_rev
            frame['base_config_revision'] = self.base_config_revision
            frame['scope'] = self.scope
            frame['science'] = {'verified': science.get('verified'),
                                'digest': science.get('digest')}
            frame['qa'] = qa_payload.get('qa')
            frame['qa_kind'] = qa_payload.get('qa_kind')
            frame['evidence'] = {'render': 'SAME_CAPTURE_PNG_SCENE',
                                 'persistence': 'NOT_WRITTEN',
                                 'host': 'NOT_CONNECTED',
                                 'export_page': 'NOT_RUN'}
            # worker 持有该候选 Figure：先关闭旧持有对象再安装新对象。
            self._close_built()
            self._fig, self._reg = fig, held
            self._built_revision = current
            fig = None
            self._frame_cache = copy.deepcopy(frame)
            self._frame_cache_key = key
            self._frame_cache_shapes = shapes
            return copy.deepcopy(frame)
        finally:
            if fig is not None:
                import matplotlib.pyplot as plt
                plt.close(fig)
    def export_frame(self, output_dir, *, revision=None, frame_revision=None):
        """导出精确请求的那一帧：同帧 PNG（same-capture 字节）+ 另一后端 PDF。

        只接受 ``revision``/``frame_revision`` 与当前候选精确一致的请求，否则
        :class:`StaleRevision` 拒绝（动态漂移同样拒绝，不伪造 provenance）。
        PNG 字节就是 :meth:`capture_frame` 同一帧的字节（哈希复核）；PDF 是另一
        后端（``savefig(format='pdf')``）单独声明的产物。导出前后只观测同一
        Agg 侧 Figure 的科学指纹与显示几何（漂移即拒绝），写盘后实测 PDF 页框；
        **不**声称发射后 PDF 字形/几何等价或终页 QA。PDF 物理尺寸用已安装支持的
        依赖实测（复用 ``figpact.handoff.measure_pdf_page_mm``，缺 pypdf 时明确报
        可选能力缺失，不 casually 加依赖）。产物落在 ``output_dir`` 下以候选/帧
        寻址的**新建**不可变束里（已存在一律拒绝覆盖）；源脚本/配置/声明产物在
        显式 commit 前一律不动；失败时只删自己新建的文件（原子清理），路径恒界定
        在 ``output_dir`` 内，不写任意脚本文件。``renderer_fingerprint`` 随帧透传
        进 provenance/回执并显式标注上述限制。
        """
        import os as _os
        if not isinstance(output_dir, (str, _os.PathLike)) or not str(output_dir):
            raise SessionError('export_frame 需要 output_dir')
        if not isinstance(revision, str) or not revision:
            raise SessionError('export_frame 需要 revision（精确候选，不猜当前）')
        if not isinstance(frame_revision, str) or not frame_revision:
            raise SessionError('export_frame 需要 frame_revision（精确帧，不猜当前）')
        self._sync()
        current = self.revision
        if revision != current:
            raise StaleRevision(f'revision 已过期：请求 {revision}，当前 {current}')
        cached = self._frame_cache
        key = (current, self._source_rev, self.base_config_revision)
        if cached is None or self._frame_cache_key != key \
                or cached.get('frame_revision') != frame_revision:
            # 没有命中精确同一帧：重捕获一次，漂移/陈旧一律拒绝，不猜当前。
            frame = self.capture_frame(revision=current)
            if frame.get('frame_revision') != frame_revision:
                raise StaleRevision('frame 已更新（动态漂移或请求陈旧），拒绝陈旧导出')
        else:
            frame = copy.deepcopy(cached)
        png_bytes = base64.b64decode(frame['png_base64'])
        if hashlib.sha256(png_bytes).hexdigest() != frame.get('png_sha256'):
            raise SessionError('同帧 PNG 字节与摘要不一致，拒绝导出')
        held_fig, held_reg = self._fig, self._reg
        if held_fig is None or held_reg is None or self._built_revision != current:
            raise StaleRevision('候选 Figure 已失效（缓存/重载后未重捕获），拒绝陈旧导出')
        # 同一候选 Figure 上导出 PDF：绘制前后都做科学复核，漂移即拒绝。
        before_science = self._capture_science(held_fig, held_reg)
        if before_science.get('digest') != (frame.get('science') or {}).get('digest'):
            raise SessionError('候选 Figure 的科学指纹与请求帧不一致（动态漂移），拒绝陈旧导出')
        before_shapes = drawn_shapes(held_fig, held_reg, include_frames=True)
        cached_shapes = self._frame_cache_shapes
        if cached_shapes is not None:
            drifted = sorted(set(_changed_shape_keys(cached_shapes, before_shapes)))
            if drifted:
                raise StaleRevision(f'候选 Figure 在捕获后发生几何漂移（{len(drifted)} 处），拒绝陈旧导出')
        buf = io.BytesIO()
        held_fig.savefig(buf, format='pdf')
        pdf_bytes = buf.getvalue()
        after_science = self._capture_science(held_fig, held_reg)
        after_shapes = drawn_shapes(held_fig, held_reg, include_frames=True)
        if after_science.get('digest') != before_science.get('digest'):
            raise SessionError('PDF 后端绘制改变了同一 Figure 的科学指纹（draws 改动了图），'
                               '无法保全 PNG/PDF 同源一致，拒绝导出')
        drifted = sorted(set(_changed_shape_keys(before_shapes, after_shapes)))
        if drifted:
            raise StaleRevision(f'PDF 绘制改变了同一 Figure 的显示几何（{len(drifted)} 处，'
                                f'渲染器容差内也不许伪造同源），拒绝导出')
        self._sync()
        if self.revision != current:
            raise StaleRevision('导出期间来源变化，拒绝陈旧导出')
        try:
            from figpact.handoff import measure_pdf_page_mm
        except ImportError as error:
            raise SessionError('PDF 页面测量需要可选依赖 pypdf：'
                               'python -m pip install "figpact[handoff]"') from error
        root = Path(output_dir).expanduser().resolve()
        if not root.is_dir():
            raise SessionError(f'导出目标不存在或不是目录：{root}')
        guarded = [Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent / 'tools',
                   Path(__file__).resolve().parent.parent / 'tests']
        for base in guarded:
            if root == base or base in root.parents:
                raise SessionError(f'拒绝把导出束放在源码/前端/测试目录内：{root}')
        script_parent = self.script.parent
        if root == script_parent or script_parent in root.parents:
            raise SessionError(f'拒绝把导出束放在源脚本目录内（避免覆盖正式产物）：{root}')
        for declared in (self._outputs or []):
            try:
                other = Path(declared).resolve()
            except Exception:
                continue
            if other == root or other in root.parents or root in other.parents:
                raise SessionError(f'导出束与声明产物路径重叠，拒绝覆盖：{other}')
        bundle = root / f'figpact-frame-{current[:16]}-{frame_revision[:16]}'
        if _os.path.lexists(bundle):
            raise SessionError(f'导出束已存在，拒绝覆盖：{bundle}')
        created: list[Path] = []
        try:
            bundle.mkdir()
            png_path = bundle / 'candidate.png'
            with png_path.open('xb') as stream:
                created.append(png_path)
                stream.write(png_bytes)
            pdf_path = bundle / 'candidate.pdf'
            with pdf_path.open('xb') as stream:
                created.append(pdf_path)
                stream.write(pdf_bytes)
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_name = tmp.name
            try:
                measured = measure_pdf_page_mm(Path(tmp_name))
            finally:
                try:
                    _os.unlink(tmp_name)
                except OSError:
                    pass
            provenance = {'candidate_revision': current, 'frame_revision': frame_revision,
                          'source_revision': self._source_rev,
                          'base_config_revision': self.base_config_revision,
                          'scope': self.scope,
                          'png_sha256': frame.get('png_sha256'),
                          'pdf_sha256': hashlib.sha256(pdf_bytes).hexdigest(),
                          'page_mm': list(measured.get('measured_page_mm') or []),
                          'science_digest': (frame.get('science') or {}).get('digest'),
                          'qa_kind': frame.get('qa_kind'),
                          'qa_count': len(frame.get('qa') or []),
                          'renderer_fingerprint': frame.get('renderer_fingerprint'),
                          'renderer_digest': (frame.get('renderer_fingerprint') or {}).get('digest'),
                          'limits': 'Agg capture stack identity only; no cross-machine pixel promise; '
                                    'PDF is a separate backend product: science/state drift checked Agg-side '
                                    'before/after, PDF page measured, no PDF glyph/geometry equivalence claimed.'}
            prov_path = bundle / 'provenance.json'
            with prov_path.open('xb') as stream:
                created.append(prov_path)
                stream.write(json.dumps(provenance, sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':')).encode('utf8'))
            frame_path = bundle / 'frame.json'
            with frame_path.open('xb') as stream:
                created.append(frame_path)
                stream.write(json.dumps(frame, sort_keys=True, ensure_ascii=True,
                                        separators=(',', ':')).encode('ascii'))
        except BaseException:
            for path in created:
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                bundle.rmdir()
            except OSError:
                pass
            raise
        return {'bundle_dir': str(bundle), 'png_path': str(bundle / 'candidate.png'),
                'pdf_path': str(bundle / 'candidate.pdf'),
                'png_sha256': frame.get('png_sha256'),
                'pdf_sha256': hashlib.sha256(pdf_bytes).hexdigest(),
                'page_mm': list(measured.get('measured_page_mm') or []),
                'pdf_measurement': measured,
                'candidate_revision': current, 'frame_revision': frame_revision,
                'source_revision': self._source_rev,
                'base_config_revision': self.base_config_revision,
                'science_digest': (frame.get('science') or {}).get('digest'),
                'renderer_fingerprint': frame.get('renderer_fingerprint'),
                'renderer_digest': (frame.get('renderer_fingerprint') or {}).get('digest'),
                'qa': frame.get('qa'), 'qa_kind': frame.get('qa_kind'),
                'evidence': {'render': 'SAME_CAPTURE_PNG_SEPARATE_PDF_BACKEND',
                             'persistence': 'BUNDLE_WRITTEN_SOURCE_NOT_WRITTEN',
                             'host': 'NOT_CONNECTED', 'export_page': 'NOT_RUN'}}

    # -- 快照 / 检查 ------------------------------------------------------- #

    def _current_figure(self):
        # snapshot/inspect 用的候选 Figure：命中则复用 worker 持有的同一对象；
        # 未命中（新候选/重载后）才重建并作废帧缓存。render_preview 行为不变：
        # 它仍按 revision 走自己的 savefig 缓存，不碰帧缓存。
        current = self.revision
        if self._fig is not None and self._built_revision == current:
            return self._fig, self._reg
        self._close_built()
        self._frame_cache = None
        self._frame_cache_key = None
        self._frame_cache_shapes = None
        self._fig, self._reg = self.build_candidate(self.candidate_config)
        self._built_revision = current
        return self._fig, self._reg

    def snapshot(self, **kwargs):
        """场景快照：由父模块 figpact.scene 提供测量语义（构造会话时就要求在场）。"""
        self._sync()
        fig, reg = self._current_figure()
        scene_mod = self._scene or _core_module('scene')
        kwargs.setdefault('contract', self.contract)
        kwargs.setdefault('revision', self.revision)
        with redirect_stdout(io.StringIO()):
            return scene_mod.snapshot(fig, reg, scope=self.scope, **kwargs)

    def inspect(self, **filters):
        self._sync()
        scene_mod = self._scene or _core_module('scene')
        return scene_mod.inspect(self.snapshot(), **filters)

    def check_effects(self):
        from figpact.effects import check_effects
        return check_effects(self.script, self.config, self.scope, contract=self.contract)

    def state(self):
        """当前候选状态（只读，不重载、不改目标）。

        `base_config_revision` 是候选所依据的基线文件指纹；磁盘文件若已变，
        这个值不会偷偷跟着变——调用方据此拒绝陈旧提交。
        """
        return {'script': str(self.script), 'config': str(self.config), 'scope': self.scope,
                'revision': self.revision, 'base_config_revision': self.base_config_revision,
                'source_revision': self._source_rev, 'module_revision': self._module_rev,
                'loaders': loader_counters(),
                'science_inputs': list(self._science_inputs),
                'artifact_outputs': list(self._outputs),
                'candidate_patch': self.candidate_patch, 'candidate_config': self.candidate_config,
                'has_candidate': bool(self._goals),
                'contract': self.contract, 'science_manifest': self.science_manifest,
                'contract_validation_error': self.contract.get('validation_error'),
                'config_writeback': dict(self.last_config_writeback),
                'user_output': self.last_user_output,
                'goals': len(self._goals),
                'proofs': {name: proof.get('status')
                           for name, proof in sorted(self._proofs.items())}}
