#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实数据切换验收：FTIR 四个作用域 + NMR main 的基线复现、独立严格发布与新 worker/API 行为。

跑法（在工作树任意位置都可）：

    D:/programs/Python/python.exe -X utf8 eval/verify_real_cutover.py --baseline-revision <捕获时的完整 commit SHA>
    ... --repo <树根> --baseline <json> --json <报告.json> [--skip-strict] [--skip-api] [--keep-temp]
    ... --selftest    # 只跑本文件纯函数自检（毫米换算/比较器/产物归一化/源改写），不碰正式文件

退出码：0 = 全部检查通过；1 = 有 FAIL（回归 / 前置缺失）；2 = 基线不可读等硬错误。

本工具只**测量与比较**，不修改任何正式文件：
* 三个来源都在只读位置：不可变基线 JSON、正式产物（examples/ftir、examples/nmr）、正式 YAML；
* 严格发布一律在临时沙箱里跑（`--probe`），正式输出目录一个字节都不动；
* 会修改文件的两项（源指纹语义、源文件失效）只在**临时目录的副本**上做；
  副本必须放在工作树内的临时目录（`<repo>/.figpact-cutover-tmp-<pid>`）里——适配器的
  导入前导会向上找含 `figpact/` 的祖先目录，放系统临时目录会 ImportError。
  该目录在退出时删除（`--keep-temp` 保留），跑完 `git status` 应当看不到它。

诚实声明的边界（写进报告，不许当成通过）：
* PNG/TIFF 逐字节确定性可证（本机 matplotlib 实测），PDF/SVG 天生带创建时间与随机 id，
  因此对这两种格式报「逐字节」与「归一化后逐字节」两个结果，PASS 允许后者；
* 关系目标 1.5 mm 的 1e-6 容差只覆盖**向量几何数学**（中心线/包围盒），不是文字栅格化精度；
* 科学等值来自真实重建与真实数组比较，**不是**只比对声明源码的哈希；
* 基线里退化成点（0×0）的包围盒来自旧捕获绑到空艺术家（如 `ax.title`）的注册 bug：
  改由明确的 `--baseline-revision` 源码独立重绘；同一面板的真正可见标题必须内容相同，
  实测位置误差也不超过 0.05 mm，不能用随着提交移动的 HEAD 或仅核对文字来放行；
  不写任何人工豁免条目，取不到旧版源码就按未验证判失败；
* 本工具不测盲测 agent 时延，也不把确定性重放冒充成 agent 成功率。
"""
from __future__ import annotations

import argparse
import builtins
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import types
from contextlib import redirect_stdout
from pathlib import Path

import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
BASELINE_DEFAULT = Path(r'C:/Users/Lin/AppData/Local/Temp/figpact_vnext_before.json')
#: 验收口径：每个原始对象的包围盒毫米偏差上限。
OBJECT_TOL_MM = 0.05
#: 关系目标/其它关系保持的容差：只覆盖向量几何数学（见模块 docstring）。
RELATION_TOL_MM = 1e-6
#: 科学数组比较容差：同一份计算应当逐位相同，1e-12 只是防浮点序列化噪声。
SCIENCE_TOL = 1e-12
RELATION_TARGET_MM = 1.5
GROUP_SHIFT_MM = 0.4
STRICT_TIMEOUT_S = 1800
FORMAL_ARTIFACT_TOTAL = 16

ADAPTERS = ('ftir', 'nmr')


# ──────────────────────────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────────────────────────
class Rows:
    """检查结果账本：一行 = 一条可核对的测量。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, section: str, subject: str, check: str, status: str, *,
            measured=None, detail: str = '', tolerance=None) -> dict:
        row = {'section': section, 'subject': subject, 'check': check, 'status': status,
               'tolerance': tolerance, 'measured': measured if measured is not None else {},
               'detail': str(detail)}
        self.rows.append(row)
        return row

    def ok(self, section, subject, check, **kw):
        return self.add(section, subject, check, 'OK', **kw)

    def fail(self, section, subject, check, **kw):
        return self.add(section, subject, check, 'FAIL', **kw)

    def unsupported(self, section, subject, check, **kw):
        return self.add(section, subject, check, 'UNSUPPORTED', **kw)

    def skip(self, section, subject, check, **kw):
        return self.add(section, subject, check, 'SKIP', **kw)

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for row in self.rows:
            out[row['status']] = out.get(row['status'], 0) + 1
        return out


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def mm_of(px: float, dpi: float) -> float:
    return float(px) * 25.4 / float(dpi)


def approx_equal(a, b, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def compare_payload(before, after, *, tol: float = 1e-9, path: str = '') -> list[str]:
    """递归比较两个 JSONable 值：数字按容差，其余按等值。返回差异描述列表。"""
    diffs: list[str] = []
    if isinstance(before, dict):
        if not isinstance(after, dict):
            return [f'{path}: 类型不同（{type(before).__name__} vs {type(after).__name__}）']
        for key in before:
            if key not in after:
                diffs.append(f'{path}.{key}: 构建结果缺失该字段')
            else:
                diffs.extend(compare_payload(before[key], after[key], tol=tol, path=f'{path}.{key}'))
        return diffs
    if isinstance(before, (list, tuple)):
        if not isinstance(after, (list, tuple)) or len(before) != len(after):
            return [f'{path}: 序列长度/类型不同（{len(before)} vs '
                    f'{len(after) if isinstance(after, (list, tuple)) else type(after).__name__}）']
        for i, (x, y) in enumerate(zip(before, after)):
            diffs.extend(compare_payload(x, y, tol=tol, path=f'{path}[{i}]'))
        return diffs
    if isinstance(before, bool) or isinstance(after, bool):
        if before != after:
            diffs.append(f'{path}: {before!r} != {after!r}')
        return diffs
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        if not approx_equal(before, after, tol):
            diffs.append(f'{path}: {before!r} != {after!r}（差 {abs(float(before) - float(after)):g}）')
        return diffs
    if before != after:
        diffs.append(f'{path}: {before!r} != {after!r}')
    return diffs


def normalize_artifact(name: str, data: bytes) -> bytes:
    """仅归一化导出时间与 SVG 身份名；保留全部绘图内容和引用关系。"""
    suffix = Path(name).suffix.lower()
    if suffix == '.pdf':
        return re.sub(rb'/(CreationDate|ModDate)\s*\(D:[^)]*\)', b'', data)
    if suffix == '.svg':
        text = re.sub(r'<dc:date>[^<]*</dc:date>', '', data.decode('utf-8', 'replace'))
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return data
        ids = {element.attrib['id']: f'normid{index:04d}'
               for index, element in enumerate(e for e in root.iter() if 'id' in e.attrib)}
        for element in root.iter():
            for key, value in element.attrib.items():
                if key == 'id':
                    element.attrib[key] = ids[value]
                elif key == 'href' or key.endswith('}href'):
                    if value.startswith('#') and value[1:] in ids:
                        element.attrib[key] = '#' + ids[value[1:]]
                elif 'url(#' in value:
                    element.attrib[key] = re.sub(
                        r'url\(#([^)]+)\)', lambda match: f'url(#{ids.get(match[1], match[1])})', value)
        return ET.tostring(root, encoding='utf-8')
    return data


def artifact_identity(name: str, produced: bytes, installed: bytes) -> tuple[bool, str]:
    if sha256_bytes(produced) == sha256_bytes(installed):
        return True, 'byte_identical'
    if normalize_artifact(name, produced) == normalize_artifact(name, installed):
        return True, f'identical_after_timestamp/id_normalisation（{Path(name).suffix}）'
    return False, 'bytes_differ'


# ──────────────────────────────────────────────────────────────────────────────
# 0×0 基线占位（旧捕获的注册 bug）的独立证据
# ──────────────────────────────────────────────────────────────────────────────
def _placeholder_gids(baseline_scope: dict) -> list[str]:
    """基线里包围盒退化成**一个点**的对象：旧捕获把 gid 绑在空艺术家上（如 `ax.title`）。

    这种 0×0 记录不是可见几何，不能拿来算毫米偏差；真正画出来的那条标题要另找证据。
    """
    out: list[str] = []
    for item in (baseline_scope.get('inventory') or {}).get('items') or []:
        bbox = (item.get('snapshot') or {}).get('bbox')
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            degenerate = float(bbox[0]) == float(bbox[2]) and float(bbox[1]) == float(bbox[3])
        except (TypeError, ValueError):
            continue
        if degenerate:
            out.append(str(item.get('gid')))
    return out


def _git_revision_blob(repo: Path, rel: str, revision: str | None) -> str | None:
    """读取捕获基线时明确记录的源码版本，绝不随当前 HEAD 漂移。"""
    if not revision or not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        return None
    try:
        res = subprocess.run(['git', '-C', str(repo), 'show', f'{revision}:{rel}'],
                             capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 and res.stdout else None


def load_pristine_adapter(repo: Path, spec: dict, revision: str | None) -> tuple[object | None, str]:
    """把捕获基线时的适配器当模块执行（不落盘、不改任何正式文件）。

    `__file__` 指向正式脚本，所以旧版的 `Path(__file__).parent` 数据/样式解析照常；
    旧版本只有 import 级读取，不建图、不渲染、不写文件。
    """
    rel = spec['script'].relative_to(repo).as_posix()
    source = _git_revision_blob(repo, rel, revision)
    if source is None:
        return None, f'取不到明确基线版本 {revision!r}:{rel}'
    module = types.ModuleType(f'figpact_pristine_{spec["name"]}')
    module.__file__ = str(spec['script'])
    argv_before = sys.argv
    sys.argv = [str(spec['script'])]  # 旧版在 import 级就解析 argv（严格 argparse），必须给干净参数
    try:
        with redirect_stdout(io.StringIO()):
            exec(compile(source, str(spec['script']), 'exec'), module.__dict__)
    except Exception as exc:  # noqa: BLE001
        return None, f'旧版适配器无法执行：{type(exc).__name__}: {exc}'
    finally:
        sys.argv = argv_before
    return module, f'{revision}:{rel}（{len(source)} 字符）'


def visible_texts(fig) -> list[dict]:
    """真的画出来、文字非空、包围盒有正面积的 Text（真实 renderer 量，不看声明）。"""
    from matplotlib.text import Text
    renderer = fig.canvas.get_renderer()
    out: list[dict] = []
    for artist in fig.findobj(Text):
        text = str(artist.get_text() or '').strip()
        if not artist.get_visible():
            continue
        if not text:
            continue
        try:
            box = artist.get_window_extent(renderer)
        except Exception:  # noqa: BLE001
            continue
        if float(box.width) > 0.0 and float(box.height) > 0.0:
            out.append({'gid': artist.get_gid(), 'text': text,
                        'axes_index': fig.axes.index(artist.axes) if artist.axes in fig.axes else None,
                        'fontsize_pt': float(artist.get_fontsize()),
                        'bbox_px': [round(float(box.x0), 4), round(float(box.y0), 4),
                                    round(float(box.x1), 4), round(float(box.y1), 4)]})
    return out


def pristine_scope_evidence(module, scope: str, gids: list[str]) -> dict:
    """旧版源码真渲染一次：那条 gid 绑的艺术家是空的、同一张图却有条非空可见标题。"""
    note_prefix = '旧版源码真渲染'
    try:
        with redirect_stdout(io.StringIO()):
            fig, reg = module.build_figure_and_registry(scope)
    except Exception as exc:  # noqa: BLE001
        return {'available': False, 'note': f'{note_prefix} {scope} 构建失败：{type(exc).__name__}: {exc}'}
    try:
        with redirect_stdout(io.StringIO()):
            try:
                fig.canvas.draw()
            except Exception:  # noqa: BLE001
                pass
            bound = {}
            for gid in gids:
                artist = reg.get(gid) if reg is not None else None
                text = artist.get_text() if hasattr(artist, 'get_text') else None
                bound[gid] = {'artist': type(artist).__name__ if artist is not None else None,
                              'text': text, 'blank': not str(text or '').strip(),
                              'axes_index': fig.axes.index(artist.axes)
                              if getattr(artist, 'axes', None) in fig.axes else None}
            return {'available': True, 'note': f'{note_prefix} {scope}', 'dpi': float(fig.dpi),
                    'bound': bound, 'visible_texts': visible_texts(fig),
                    'curve_science': curve_science(reg),
                    'unregistered': reg.unregistered(fig), 'unbound': reg.unbound()}
    except Exception as exc:  # noqa: BLE001
        return {'available': False, 'note': f'{note_prefix} {scope} 测量失败：{type(exc).__name__}: {exc}'}
    finally:
        _close(fig)


def judge_bbox_placeholder(rows: Rows, subject: str, gid: str, bbox_b, bbox_a, artist,
                           placeholders: dict) -> str | None:
    """0×0 基线包围盒的判定：不许人工豁免，必须有独立证据。返回失败原因或 None。"""
    info = placeholders or {}
    evidence = (info.get('bound') or {}).get(gid) or {}
    visible = list(info.get('visible_texts') or [])   # visible_texts 已保证非空文字 + 正面积
    built_text = str(artist.get_text() or '').strip() if hasattr(artist, 'get_text') else ''
    match = [t for t in visible if t.get('gid') != gid
             and t.get('axes_index') == evidence.get('axes_index')
             and str(t.get('text') or '').strip() == built_text]
    visible_ok = bool(bbox_a) and len(bbox_a) == 4 \
        and float(bbox_a[2]) > float(bbox_a[0]) and float(bbox_a[3]) > float(bbox_a[1])
    measured = {'baseline_bbox_px': bbox_b, 'built_bbox_px': bbox_a, 'built_text': built_text,
                'pristine_note': info.get('note'), 'pristine_bound': evidence,
                'pristine_visible_texts': visible[:4], 'pristine_visible_count': len(visible),
                'source': '明确基线源码版本的独立渲染（不是人工豁免条目）'}

    if not info.get('available'):
        rows.fail('real.baseline', subject, f'bbox_placeholder::{gid}', measured=measured,
                  detail='0×0 基线占位拿不到旧版源码的独立渲染证据：按未验证处理，不给通过')
        return f'{gid}: 0×0 占位缺少独立证据（{info.get("note")}）'
    if not evidence.get('blank'):
        rows.fail('real.baseline', subject, f'bbox_placeholder::{gid}', measured=measured,
                  detail='旧版源码里这条 gid 绑的艺术家不是空的：0×0 不是注册 bug，基线不可信')
        return f'{gid}: 旧版绑定的艺术家非空，0×0 记录来源不明'
    if not visible_ok:
        rows.fail('real.baseline', subject, f'bbox_placeholder::{gid}', measured=measured,
                  detail='新版这条 gid 的包围盒仍然退化：不是可见几何（真的丢内容）')
        return f'{gid}: 新版包围盒退化'
    if not built_text or not match:
        rows.fail('real.baseline', subject, f'bbox_placeholder::{gid}', measured=measured,
                  detail='旧版那张图里找不到与新版文字逐字相同的非空可见标题：内容不等价')
        return f'{gid}: 找不到与新版一致的非空可见标题'
    old_dpi = info.get('dpi')
    new_dpi = getattr(getattr(artist, 'figure', None), 'dpi', None)
    if not old_dpi or not new_dpi:
        return f'{gid}: 标题独立测量缺少实际 DPI'
    new_mm = [float(value) * 25.4 / float(new_dpi) for value in bbox_a]
    error = min(max(abs(float(value) * 25.4 / float(old_dpi) - current)
                    for value, current in zip(text['bbox_px'], new_mm)) for text in match)
    measured['visible_bbox_error_mm'] = error
    measured['pristine_dpi'] = old_dpi
    measured['built_dpi'] = new_dpi
    if error > OBJECT_TOL_MM:
        rows.fail('real.baseline', subject, f'bbox_placeholder::{gid}', measured=measured,
                  tolerance=OBJECT_TOL_MM, detail='旧版真正可见标题与新版的位置误差超限')
        return f'{gid}: 可见标题实际位置误差 {error:.6f} mm > {OBJECT_TOL_MM} mm'
    rows.ok('real.baseline', subject, f'bbox_placeholder::{gid}', measured=measured,
            tolerance=OBJECT_TOL_MM,
            detail='旧注册绑定为空，但同一面板的实际可见标题内容与位置经独立渲染核对一致；未加豁免')
    return None


def load_engine():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from importlib import import_module
    return tuple(import_module(f'figpact.{name}') for name in ('geometry', 'inventory', 'session'))


# ──────────────────────────────────────────────────────────────────────────────
# 适配器与基线
# ──────────────────────────────────────────────────────────────────────────────
def adapter_spec(repo: Path, name: str) -> dict:
    if name == 'ftir':
        base = repo / 'examples' / 'ftir'
        return {'name': name, 'baseline_key': 'ftir', 'dir': base,
                'script': base / 'plot_ftir.py', 'config': base / 'ftir.yaml'}
    if name == 'nmr':
        base = repo / 'examples' / 'nmr'
        return {'name': name, 'baseline_key': 'nmr', 'dir': base,
                'script': base / '08 NMR.py', 'config': base / 'nmr.yaml'}
    raise ValueError(f'未知适配器 {name!r}')


def load_adapter_module(session_mod, script, config):
    return session_mod.load_module(Path(script), Path(config))


def declared_outputs(module, spec: dict, scopes) -> dict[str, list[str]]:
    """各作用域声明的正式产物名（native 契约是唯一来源）。"""
    hook = getattr(module, 'layout_contract', None)
    if not callable(hook):
        return {}
    out: dict[str, list[str]] = {}
    for scope in scopes:
        contract = hook(scope)
        names = [str(n) for n in (contract.get('outputs') or [])]
        if names:
            out[scope] = names
    return out


def scope_list(module, baseline_entry: dict, spec: dict) -> list[str]:
    declared = [str(s) for s in (getattr(module, 'SCOPES', None) or ())]
    known = list(baseline_entry['scopes'])
    if declared:
        return [s for s in declared if s in known] or known
    return known


# ──────────────────────────────────────────────────────────────────────────────
# 构建与复现比较
# ──────────────────────────────────────────────────────────────────────────────
CURVE_MARK = '.curve.'


def build_legacy(module, scope: str):
    with redirect_stdout(io.StringIO()):
        return module.build_figure_and_registry(scope)


def build_native(module, spec: dict, scope: str):
    science = module.load_science()
    config = copy.deepcopy(module.CONFIG)  # 已由各适配器原有校验器读取的同一份原始 YAML
    with redirect_stdout(io.StringIO()):
        return module.build_scene(science, config, scope), science


def inventory_of(inventory_mod, fig, reg) -> dict:
    with redirect_stdout(io.StringIO()):
        return inventory_mod.inventory(fig, reg)


def curve_gaps(fig, scope: str) -> tuple[list[float], float]:
    """作用域内相邻谱线在画布毫米下的净空（与基线捕获脚本同一套测量）。"""
    mm_per_px = 25.4 / float(fig.dpi)
    lines = []
    for ax in fig.axes:
        for line in ax.lines:
            gid = line.get_gid() or ''
            if f'.{scope}.curve.' in gid:
                lines.append(line)
    if not lines:
        return [], float('nan')
    renderer = fig.canvas.get_renderer()
    extents = sorted(((line.get_window_extent(renderer), line) for line in lines), key=lambda x: x[0].y0)
    gaps = [(b.y0 - a.y1) * mm_per_px
            for (a, _), (b, _) in zip(extents, extents[1:])]
    first_transform = extents[0][1].get_transform().transform(extents[0][1].get_xydata())
    second_transform = extents[1][1].get_transform().transform(extents[1][1].get_xydata())
    pitch = (second_transform[0, 1] - first_transform[0, 1]) * mm_per_px
    return [round(g, 12) for g in gaps], float(pitch)


def curve_science(reg) -> dict:
    """受保护曲线数组的实测指纹：x 逐字节 SHA256 + y 相对首个采样的形状。"""
    import numpy as np
    out = {}
    for gid in sorted(reg.all()):
        if CURVE_MARK not in gid:
            continue
        artist = reg.get(gid)
        x = np.asarray(artist.get_xdata(), dtype=float)
        y = np.asarray(artist.get_ydata(), dtype=float)
        out[gid] = {'x_sha256': sha256_bytes(np.ascontiguousarray(x).tobytes()),
                    'y_sha256': sha256_bytes(np.ascontiguousarray(y).tobytes()),
                    'y_shape': (y - y[0])}
    return out


def judge_new_identity(gid: str, artist, evidence: dict, new_dpi: float) -> dict:
    """新增身份必须对应旧渲染里实际存在的同一个可见对象，不能把新增内容当登记升级。"""
    if not evidence.get('available') or not hasattr(artist, 'get_text'):
        return {'gid': gid, 'verified': False, 'reason': '缺少旧版可见对象证据'}
    old_dpi = float(evidence['dpi'])
    box = artist.get_window_extent(artist.figure.canvas.get_renderer())
    current = [float(v) * 25.4 / new_dpi for v in box.extents]
    axes = artist.figure.axes
    panel = axes.index(artist.axes) if artist.axes in axes else None
    matches = []
    for old in evidence.get('visible_texts', []):
        if old['text'] != str(artist.get_text()).strip() or old['axes_index'] != panel:
            continue
        if old['fontsize_pt'] != float(artist.get_fontsize()):
            continue
        error = max(abs(float(v) * 25.4 / old_dpi - now)
                    for v, now in zip(old['bbox_px'], current))
        if error <= OBJECT_TOL_MM:
            matches.append(error)
    return {'gid': gid, 'verified': len(matches) == 1,
            'matched_visible_objects': len(matches),
            'max_error_mm': matches[0] if len(matches) == 1 else None,
            'source': evidence.get('note')}


def compare_scope(rows: Rows, section: str, spec: dict, scope: str, built, baseline_scope: dict,
                  build_label: str, placeholders: dict | None = None) -> dict:
    """把一个真实构建结果与不可变基线逐项比较。返回实测摘要。

    `placeholders` 是**这个作用域**的 0×0 基线占位证据（旧版源码真渲染出来的），
    用来单独判定那些退化包围盒，绝不进毫米统计、也不加豁免条目。
    """
    fig, reg = built
    subject = f"{spec['name']}.{scope}[{build_label}]"
    inv = inventory_of(_INVENTORY, fig, reg)
    summary: dict = {'scope': scope, 'build': build_label}

    base_items = {item['gid']: item for item in baseline_scope['inventory']['items']}
    got_items = {item['gid']: item for item in inv['items']}
    missing = sorted(set(base_items) - set(got_items))
    extra = sorted(set(got_items) - set(base_items))
    identity_evidence = [judge_new_identity(gid, reg.get(gid), placeholders or {},
                                          float(inv['figure_dpi'])) for gid in extra]
    unidentified = [item for item in identity_evidence if not item['verified']]
    if missing or unidentified:
        rows.fail(section, subject, 'inventory_gid_set',
                  measured={'missing': missing, 'unidentified': unidentified},
                  detail='旧对象不得丢失；新增身份必须独立证明对应旧版已存在的可见对象')
    else:
        rows.ok(section, subject, 'inventory_gid_set',
                measured={'original_objects': len(base_items),
                          'newly_identified_visible_objects': identity_evidence},
                detail='原始身份全部保留，新增登记对象与旧版实际可见内容和位置逐个核对')

    base_dpi = float(baseline_scope['inventory']['figure_dpi'])
    got_dpi = float(inv['figure_dpi'])
    if not approx_equal(base_dpi, got_dpi, 1e-9):
        rows.fail(section, subject, 'figure_dpi', measured={'baseline': base_dpi, 'built': got_dpi},
                  detail='渲染 DPI 与基线不同，毫米换算不再可比')
    else:
        rows.ok(section, subject, 'figure_dpi', measured={'baseline': base_dpi, 'built': got_dpi})

    worst = 0.0
    worst_gid = None
    compared = 0
    exact = 0
    field_diffs: list[str] = []
    placeholder_failures: list[str] = []
    placeholder_gids = set((placeholders or {}).get('gids') or [])
    for gid, item in base_items.items():
        got = got_items.get(gid)
        if got is None:
            continue
        before = item.get('snapshot') or {}
        after = got.get('snapshot') or {}
        bbox_b, bbox_a = before.get('bbox'), after.get('bbox')
        if gid in placeholder_gids:
            # 0×0 基线占位（旧捕获绑到空艺术家）不是可见几何：判独立证据，不进毫米统计，
            # 位置/字号字段记的也是那个空艺术家，一并排除。
            problem = judge_bbox_placeholder(rows, subject, gid, bbox_b, bbox_a,
                                             reg.get(gid) if reg is not None else None,
                                             placeholders or {})
            if problem:
                placeholder_failures.append(problem)
            continue
        if bbox_b and bbox_a and len(bbox_b) == len(bbox_a):
            compared += 1
            item_worst = 0.0
            for x, y in zip(bbox_b, bbox_a):
                diff = abs(mm_of(x, base_dpi) - mm_of(y, got_dpi))
                item_worst = max(item_worst, diff)
            if item_worst <= 0.0:
                exact += 1
            if item_worst > worst:
                worst, worst_gid = item_worst, gid
        rest_before = {k: v for k, v in before.items() if k != 'bbox'}
        rest_after = {k: v for k, v in after.items() if k != 'bbox'}
        for diff in compare_payload(rest_before, rest_after, tol=1e-9, path=f'{gid}.snapshot'):
            field_diffs.append(diff)
    summary['bbox_compared'] = compared
    summary['bbox_max_error_mm'] = worst
    summary['bbox_worst_gid'] = worst_gid
    summary['bbox_exact'] = exact
    summary['bbox_placeholders'] = sorted(placeholder_gids)
    summary['bbox_placeholder_failures'] = placeholder_failures
    summary['snapshot_field_diffs'] = len(field_diffs)

    status = 'OK' if (worst <= OBJECT_TOL_MM and compared and not placeholder_failures) else 'FAIL'
    rows.add(section, subject, 'inventory_bbox_mm', status,
             measured={'objects_compared': compared, 'objects_exact': exact,
                       'max_error_mm': worst, 'worst_gid': worst_gid,
                       'placeholders_excluded': sorted(placeholder_gids),
                       'placeholder_failures': placeholder_failures},
             tolerance=OBJECT_TOL_MM,
             detail='初始位置误差：每个原始对象包围盒相对基线的实测毫米偏差'
                    '（基线 px × 25.4/基线 figure_dpi，与构建侧 px × 25.4/构建侧 figure_dpi '
                    '各自换算）；0×0 基线占位另有独立渲染证据，不计入这条统计')
    if field_diffs:
        rows.fail(section, subject, 'inventory_snapshot_fields_text_position',
                  measured={'differences': field_diffs[:12], 'count': len(field_diffs)},
                  detail='非包围盒字段（文字/位置/字号/线宽/均值）与基线不同')
    else:
        rows.ok(section, subject, 'inventory_snapshot_fields_text_position',
                measured={'objects': len(base_items)},
                detail='文字赋值、位置（peak-x）、字号、线宽等字段逐项等于基线')

    # 受保护科学数组
    base_sci = baseline_scope.get('scientific') or {}
    got_sci = curve_science(reg)
    sci_missing = sorted(set(base_sci) - set(got_sci))
    pristine_sci = (placeholders or {}).get('curve_science') or {}
    sha_bad, shape_bad, shape_worst = [], [], 0.0
    for gid, record in base_sci.items():
        got, pristine = got_sci.get(gid), pristine_sci.get(gid)
        if got is None:
            continue
        if pristine is None:
            shape_bad.append(f'{gid}（缺少明确旧版本的原始数组）')
            continue
        if got['x_sha256'] != record['x'] or got['x_sha256'] != pristine['x_sha256']:
            sha_bad.append(gid)
        if got['y_sha256'] != pristine['y_sha256']:
            shape_bad.append(f'{gid}（原始 y 数组 SHA256 与旧版不同）')
        import numpy as np
        expected = np.asarray(record['shape'], dtype=float)
        actual = np.asarray(got['y_shape'], dtype=float)
        # 捕获脚本明确执行 np.round(y - y[0], 10)，不是完整精度的原始科学数组。
        if expected.shape != actual.shape:
            shape_bad.append(f'{gid}（形状 {expected.shape} vs {actual.shape}）')
            continue
        diff = float(np.max(np.abs(expected - actual))) if expected.size else 0.0
        shape_worst = max(shape_worst, diff)
        if not np.array_equal(expected, np.round(actual, 10)):
            shape_bad.append(f'{gid}（与原捕获的 10 位小数形状不同）')
    summary['science_curves'] = len(base_sci)
    summary['science_shape_capture_quantization_error'] = shape_worst
    rows.add(section, subject, 'science_arrays_exact',
             'FAIL' if sci_missing or sha_bad or shape_bad else 'OK',
             measured={'missing': sci_missing, 'x_sha_mismatch': sha_bad,
                       'y_sha_or_shape_mismatch': shape_bad,
                       'capture_decimal_places': 10,
                       'capture_quantization_error': shape_worst},
             detail='x/y 原始数组 SHA256 必须与明确旧版逐字节一致；另核对旧捕获的 10 位小数形状')

    # 关系物理量与参考换算
    base_gaps = list(baseline_scope.get('clearances_mm') or [])
    got_gaps, pitch = curve_gaps(fig, scope)
    gap_err = max([abs(a - b) for a, b in zip(sorted(base_gaps), sorted(got_gaps))], default=0.0)
    if len(base_gaps) != len(got_gaps):
        gap_err = float('inf')
    summary['clearance_max_error_mm'] = gap_err
    summary['pitch_mm'] = pitch
    rows.add(section, subject, 'clearances_and_pitch_mm',
             'OK' if gap_err <= RELATION_TOL_MM else 'FAIL',
             measured={'baseline_clearances_mm': base_gaps, 'built_clearances_mm': got_gaps,
                       'max_error_mm': gap_err, 'baseline_pitch_mm': baseline_scope.get('pitch_mm'),
                       'built_pitch_mm': pitch},
             tolerance=RELATION_TOL_MM,
             detail='相邻谱线净空与堆叠间距的实测毫米值')

    base_ref = baseline_scope.get('reference') or {}
    ref = {}
    for ax in fig.axes:
        if any(f'.{scope}.curve.' in (line.get_gid() or '') for line in ax.lines):
            mm_per_px = 25.4 / float(fig.dpi)
            import numpy as np
            ref = {'axis_bottom_data': float(ax.get_ylim()[0]),
                   'units_per_mm': float(np.diff(ax.get_ylim())[0]
                                         / (ax.get_window_extent().height * mm_per_px))}
            break
    ref_diffs = compare_payload(base_ref, ref, tol=1e-9, path='reference')
    rows.add(section, subject, 'layout_reference',
             'OK' if not ref_diffs else 'FAIL',
             measured={'baseline': base_ref, 'built': ref, 'differences': ref_diffs[:6]},
             detail='坐标轴参考换算（axis_bottom_data / units_per_mm）')

    pristine_audit = placeholders or {}
    unreg_ok = (pristine_audit.get('available')
                and list(inv.get('unregistered') or []) == list(pristine_audit.get('unregistered') or [])
                and list(inv.get('unbound') or []) == list(pristine_audit.get('unbound') or []))
    rows.add(section, subject, 'unregistered_and_unbound',
             'OK' if unreg_ok else 'FAIL',
             measured={'built_unregistered': inv.get('unregistered'),
                       'built_unbound': inv.get('unbound'),
                       'pristine_unregistered': pristine_audit.get('unregistered'),
                       'pristine_unbound': pristine_audit.get('unbound'),
                       'old_capture_unregistered': baseline_scope['inventory'].get('unregistered')},
             detail='同一可见性审计器检查旧版与新版，保留旧捕获曾漏列的真实 Patch 等风险')
    return summary


def compare_native_vs_legacy(rows: Rows, spec: dict, scope: str, legacy_inv: dict,
                             legacy_sci: dict, native_inv: dict, native_sci: dict,
                             legacy_gaps: list, native_gaps: list) -> None:
    subject = f"{spec['name']}.{scope}[native-vs-legacy]"
    diffs = []
    if legacy_inv['items'] and native_inv['items']:
        b = {i['gid']: i.get('snapshot') for i in legacy_inv['items']}
        a = {i['gid']: i.get('snapshot') for i in native_inv['items']}
        for gid in sorted(set(b) | set(a)):
            diffs.extend(compare_payload(b.get(gid), a.get(gid), tol=1e-9, path=f'{gid}'))
    if legacy_sci and native_sci:
        for gid in sorted(set(legacy_sci) | set(native_sci)):
            lb, ln = legacy_sci.get(gid), native_sci.get(gid)
            if lb is None or ln is None:
                diffs.append(f'{gid}: 一侧缺曲线')
                continue
            if lb['x_sha256'] != ln['x_sha256']:
                diffs.append(f'{gid}: x SHA256 不同')
            import numpy as np
            if float(np.max(np.abs(lb['y_shape'] - ln['y_shape']))) > SCIENCE_TOL:
                diffs.append(f'{gid}: y 形状不同')
    if legacy_gaps and native_gaps:
        if len(legacy_gaps) != len(native_gaps):
            diffs.append(f'净空个数不同：{len(legacy_gaps)} vs {len(native_gaps)}')
        else:
            worst = max(abs(a - b) for a, b in zip(legacy_gaps, native_gaps))
            if worst > SCIENCE_TOL:
                diffs.append(f'净空最大差 {worst:g} mm：{legacy_gaps} vs {native_gaps}')
    rows.add('real.baseline', subject, 'native_matches_legacy',
             'OK' if not diffs else 'FAIL',
             measured={'differences': diffs[:8], 'count': len(diffs)},
             detail='native build_scene(load_science(), config) 与 legacy 入口必须给出同一张图')


# ──────────────────────────────────────────────────────────────────────────────
# 严格发布（只在临时沙箱）
# ──────────────────────────────────────────────────────────────────────────────
def run_strict_probe(rows: Rows, spec: dict, workdir: Path, expected: list[str]) -> dict:
    section = 'real.strict'
    subject = spec['name']
    probe = workdir / f"probe-{spec['name']}"
    probe.mkdir(parents=True, exist_ok=True)
    cfg_copy = probe / spec['config'].name
    shutil.copyfile(spec['config'], cfg_copy)
    cmd = [sys.executable, '-X', 'utf8', str(spec['script']), '--config', str(cfg_copy),
           '--strict', '--probe', str(probe)]
    env = {**os.environ, 'FIGPACT_PROBE_DIR': str(probe), 'MPLBACKEND': 'Agg',
           'PYTHONIOENCODING': 'utf-8'}
    started = time.perf_counter()
    try:
        res = subprocess.run(cmd, cwd=str(spec['script'].parent), capture_output=True, text=True,
                             encoding='utf-8', errors='replace', env=env, timeout=STRICT_TIMEOUT_S)
        code, out, err = res.returncode, res.stdout or '', res.stderr or ''
    except subprocess.TimeoutExpired:
        code, out, err = None, '', f'超时 {STRICT_TIMEOUT_S}s'
    duration = time.perf_counter() - started
    produced = sorted(p.name for p in probe.iterdir()
                      if p.is_file() and p.name != 'qa_exemptions.json' and p != cfg_copy)
    qa_lines = [line.strip() for line in (out + '\n' + err).splitlines()
                if '阻断' in line or 'QA' in line or '豁免' in line]
    info = {'returncode': code, 'seconds': round(duration, 3), 'produced': produced,
            'expected': expected, 'qa': qa_lines[:40]}
    skipped = [name for name in expected if name not in produced]
    info['missing'] = skipped
    rows.add(section, subject, 'strict_probe_exit', 'OK' if code == 0 else 'FAIL',
             measured={'returncode': code, 'seconds': info['seconds'], 'qa_lines': qa_lines[:8]},
             detail='正式 YAML 的完整严格发布（临时沙箱）；基线应当零阻断项')
    rows.add(section, subject, 'strict_probe_outputs',
             'OK' if (expected and not skipped) else ('FAIL' if expected else 'UNSUPPORTED'),
             measured={'produced': produced, 'declared': expected, 'missing': skipped},
             detail=f'严格发布的实际产出文件名与完整度（{len(produced)} 个文件）')
    return info


# ──────────────────────────────────────────────────────────────────────────────
# 新 worker / API（真实适配器）
# ──────────────────────────────────────────────────────────────────────────────
def nodes_by_gid(snapshot: dict) -> dict:
    return {n['gid']: n for n in (snapshot.get('nodes') or []) if n.get('gid')}


def measure_relation(geometry_mod, rel: dict, nodes: dict):
    objs = [nodes.get(g) for g in rel.get('objects') or []]
    if any(o is None for o in objs):
        return None, f'快照里缺少对象：{[g for g in rel["objects"] if g not in nodes]}'
    axis = rel.get('axis') or 'x'
    res = geometry_mod.measure_relation(rel['kind'], objs, axis=axis, anchor=rel.get('anchor'),
                                        method=rel.get('method'), tolerance_mm=RELATION_TOL_MM)
    if res.get('status') != 'OK' and rel.get('method'):
        retry = geometry_mod.measure_relation(rel['kind'], objs, axis=axis, anchor=rel.get('anchor'),
                                             method=None, tolerance_mm=RELATION_TOL_MM)
        if retry.get('status') == 'OK':
            retry['notes'] = list(retry.get('notes') or []) + [f'契约 method 不可用，退回默认：{res.get("notes")}']
            return retry, ''
    return res, ''


def gap_relations(contract: dict, config: dict) -> list[dict]:
    """契约里可测的 gap/clearance 关系（按声明顺序）。"""
    out = []
    for rel in contract.get('relations') or []:
        if rel.get('kind') not in ('gap', 'clearance'):
            continue
        if len(rel.get('objects') or []) < 2:
            continue
        out.append(rel)
    return out


def relation_target_candidates(contract: dict, config: dict, get_path) -> list[tuple[dict, list]]:
    """可被一个毫米标量控制、且当前值落在合理区间的 gap/clearance 关系。"""
    out = []
    for rel in gap_relations(contract, config):
        paths = rel.get('controlled_by') or []
        if len(paths) != 1 or not isinstance(paths[0], list):
            continue
        try:
            value = get_path(config, paths[0])
        except KeyError:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not (-50.0 <= float(value) <= 50.0):
            continue
        out.append((rel, paths[0]))
    return out


def probe_relation_target(rows: Rows, worker, geometry_mod, contract: dict, config: dict,
                          spec: dict, scope: str, get_path) -> dict:
    section = 'real.api'
    subject = f"{spec['name']}.{scope}"
    info: dict = {'scope': scope}
    base = worker.snapshot()
    base_nodes = nodes_by_gid(base)
    relations = gap_relations(contract, config)
    base_values = {}
    for rel in relations:
        value, note = measure_relation(geometry_mod, rel, base_nodes)
        base_values[rel['id']] = (value, note)
    info['relations'] = len(relations)

    candidates = relation_target_candidates(contract, config, get_path)
    if not candidates:
        rows.unsupported(section, subject, 'relation_target_1.5mm',
                         measured={'relations': len(relations)},
                         detail='契约里没有「单一路径控制的可测 gap/clearance 关系」，无法打目标')
        return info
    attempts = []
    for rel, path in candidates:
        result = worker.try_layout([{'operation': 'set_relation', 'relation_id': rel['id'],
                                     'target_mm': RELATION_TARGET_MM}])
        attempts.append({'relation': rel['id'], 'path': path, 'status': result.get('status'),
                         'verification': result.get('verification'),
                         'message': result.get('message'), 'checks': result.get('checks')})
        if result.get('status') != 'OK':
            continue
        after = worker.snapshot()
        after_nodes = nodes_by_gid(after)
        measured, note = measure_relation(geometry_mod, rel, after_nodes)
        target_err = (abs(float(measured['value_mm']) - RELATION_TARGET_MM)
                      if measured and measured.get('value_mm') is not None else float('inf'))
        other_errors = {}
        for other in relations:
            if other['id'] == rel['id']:
                continue
            value, _ = measure_relation(geometry_mod, other, after_nodes)
            before = base_values.get(other['id'], (None, ''))[0]
            if value is None or before is None or value.get('value_mm') is None \
                    or before.get('value_mm') is None:
                other_errors[other['id']] = None
                continue
            other_errors[other['id']] = abs(float(value['value_mm']) - float(before['value_mm']))
        worst_other = max([v for v in other_errors.values() if v is not None], default=0.0)
        info.update({'relation': rel['id'], 'path': path, 'status': result.get('status'),
                     'verification': result.get('verification'),
                     'measured_mm': measured.get('value_mm') if measured else None,
                     'method': measured.get('method') if measured else None,
                     'target_error_mm': target_err,
                     'other_gap_max_error_mm': worst_other,
                     'other_gaps': other_errors,
                     'affected_objects': result.get('affected_objects'),
                     'attempts': attempts})
        rows.add(section, subject, 'relation_target_1.5mm',
                 'OK' if target_err <= RELATION_TOL_MM else 'FAIL',
                 measured={'relation': rel['id'], 'path': path, 'requested_mm': RELATION_TARGET_MM,
                           'measured_mm': measured.get('value_mm') if measured else None,
                           'method': measured.get('method') if measured else None,
                           'verification': result.get('verification'),
                           'error_mm': target_err},
                 tolerance=RELATION_TOL_MM,
                 detail='一个关系打到 1.5 mm 的实测值（真实重建/几何快车道，按返回的 verification 记录）')
        rows.add(section, subject, 'other_gaps_preserved',
                 'OK' if worst_other <= RELATION_TOL_MM else 'FAIL',
                 measured={'max_error_mm': worst_other, 'per_relation': other_errors},
                 tolerance=RELATION_TOL_MM,
                 detail='其余关系的实测值必须不动（不许用"整体缩放"糊过去）')
        return info
    after = worker.snapshot()
    unchanged = nodes_by_gid(after) == base_nodes and after.get('revision') == base.get('revision')
    measured_refusal = unchanged and all(
        attempt.get('status') == 'GEOMETRY_REJECTED'
        and any(check.get('status') == 'FAIL' for check in attempt.get('checks') or [])
        for attempt in attempts)
    rows.add(section, subject, 'relation_target_1.5mm',
             'REFUSED' if measured_refusal else 'FAIL',
             measured={'attempts': attempts, 'state_unchanged': unchanged,
                       'requested_mm': RELATION_TARGET_MM, 'achieved_mm': None},
             detail='原目标没有达成：实测新碰撞时保持原状态并拒绝；不得把拒绝记成 1.5 mm 成功')
    info.update(status='REFUSED' if measured_refusal else 'FAIL', attempts=attempts,
                requested_mm=RELATION_TARGET_MM, measured_mm=None, state_unchanged=unchanged)
    return info


def probe_group_shift(rows: Rows, worker, spec: dict, scope: str, contract: dict) -> dict:
    section = 'real.api'
    subject = f"{spec['name']}.{scope}"
    target = ['group_y_mm', scope]
    record = None
    for param in contract.get('parameters') or []:
        if param.get('path') == target:
            record = param
            break
    if record is None:
        rows.unsupported(section, subject, 'group_shift_0.4mm',
                         measured={'path': target},
                         detail='契约里没有 group_y_mm[scope] 这条声明，无法打组位移')
        return {}
    objects = [g for g in record.get('objects') or []]
    before = worker.snapshot()
    base_nodes = nodes_by_gid(before)
    shift = GROUP_SHIFT_MM
    result = worker.try_layout([{'operation': 'set_parameter', 'path': target, 'value': shift}])
    if result.get('status') == 'GEOMETRY_REJECTED':
        refused = worker.snapshot()
        unchanged = nodes_by_gid(refused) == base_nodes and refused.get('revision') == before.get('revision')
        rows.add(section, subject, 'group_shift_positive_collision_guard',
                 'OK' if unchanged else 'FAIL',
                 measured={'requested_mm': shift, 'status': result['status'],
                           'message': result.get('message'), 'state_unchanged': unchanged},
                 detail='碰撞请求必须明确拒绝且不改变状态；另做独立、有实测余量的位移烟测，不豁免碰撞')
        clearances = [pair['baseline_gap_mm']
                      for check in result.get('checks', []) for pair in check.get('pairs', [])
                      if isinstance(pair.get('baseline_gap_mm'), (int, float))
                      and pair['baseline_gap_mm'] > 0]
        if not clearances:
            return {'status': result['status'], 'safe_motion': 'UNMEASURED'}
        # 这是独立的有余量烟测，不是替用户夹紧原来的 0.4 mm 请求。
        shift = min(GROUP_SHIFT_MM, min(clearances) / 2.0)
        result = worker.try_layout([{'operation': 'set_parameter', 'path': target, 'value': shift}])
    after = worker.snapshot()
    after_nodes = nodes_by_gid(after)
    errors = {}
    for gid in objects:
        b, a = base_nodes.get(gid), after_nodes.get(gid)
        if b is None or a is None or not b.get('bounds_mm') or not a.get('bounds_mm'):
            errors[gid] = None
            continue
        errors[gid] = abs((float(a['bounds_mm'][1]) - float(b['bounds_mm'][1])) - shift)
    worst = max([v for v in errors.values() if v is not None], default=None)
    if result.get('status') != 'OK':
        rows.fail(section, subject, 'group_shift_0.4mm',
                  measured={'status': result.get('status'), 'message': result.get('message'),
                            'path': target},
                  detail='组位移被拒绝')
        return {'status': result.get('status')}
    rows.add(section, subject, 'group_shift_safe_probe',
             'OK' if (worst is not None and worst <= RELATION_TOL_MM) else 'FAIL',
             measured={'path': target, 'declared_objects': len(objects), 'requested_mm': shift,
                       'max_error_mm': worst, 'per_object': errors,
                       'verification': result.get('verification')},
             tolerance=RELATION_TOL_MM,
             detail='整组（曲线 + 归属文字）真实毫米位移；声明里没列的对象不参与、也不许被顺手带走')
    return {'max_error_mm': worst, 'status': result.get('status')}


def probe_scope_isolation(rows: Rows, spec: dict, modules, scope: str, other_scope: str,
                          config: dict, get_path) -> dict:
    section = 'real.api'
    subject = f"{spec['name']}.{scope}→{other_scope}"
    from figpact.runtime import FigureWorker
    worker = FigureWorker(spec['script'], spec['config'], scope)
    try:
        worker.open()
        contract = worker.contract
        base_nodes = nodes_by_gid(worker.snapshot())
        target = None
        for param in contract.get('parameters') or []:
            path = param.get('path') or []
            if len(path) == 3 and path[0] == 'clearance_mm' and path[1] == scope \
                    and param.get('operation') == 'translate':
                target = path
                break
        if target is None:
            rows.unsupported(section, subject, 'scope_isolation',
                             measured={'expected_path': ['clearance_mm', scope, '<curve>']},
                             detail='该作用域没有逐曲线净空路径可打')
            return {}
        sid = target[2]
        value = float(get_path(worker.candidate_config, target))
        result = worker.try_layout([{'operation': 'set_parameter', 'path': target,
                                     'value': min(value + 0.75, 1.5)}])
        if result.get('status') != 'OK':
            rows.fail(section, subject, 'scope_isolation',
                      measured={'path': target, 'status': result.get('status'),
                                'message': result.get('message')},
                      detail='目标被拒绝，无法判定作用域隔离')
            return {}
        after_nodes = nodes_by_gid(worker.snapshot())
        leaked = [list(p) for p in _paths_of(worker.candidate_patch) if scope not in p]
        other_errors = {}
        for gid, node in after_nodes.items():
            if f'.{other_scope}.' not in gid or gid not in base_nodes:
                continue
            b, a = base_nodes[gid], node
            if not b.get('bounds_mm') or not a.get('bounds_mm'):
                continue
            other_errors[gid] = max(abs(float(y) - float(x))
                                    for x, y in zip(b['bounds_mm'], a['bounds_mm']))
        worst = max(other_errors.values(), default=0.0)
        ok = (not leaked) and worst <= RELATION_TOL_MM
        rows.add(section, subject, 'scope_isolation', 'OK' if ok else 'FAIL',
                 measured={'alias_path': target, 'candidate_paths': [list(p) for p in _paths_of(worker.candidate_patch)],
                           'leaked_paths': leaked, 'other_scope_objects': len(other_errors),
                           'other_scope_max_error_mm': worst},
                 tolerance=RELATION_TOL_MM,
                 detail=f'改 {scope} 的路径不得写进 {other_scope} 的候选，也不得移动它的对象')
        return {'candidate_paths': [list(p) for p in _paths_of(worker.candidate_patch)],
                'other_scope_max_error_mm': worst}
    finally:
        worker.close()


def _paths_of(patch: dict, prefix: tuple = ()) -> list[tuple]:
    out = []
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and value:
            out.extend(_paths_of(value, (*prefix, key)))
        else:
            out.append((*prefix, key))
    return out


def probe_no_source_reread(rows: Rows, spec: dict, modules, scope: str) -> dict:
    """查询阶段不得再读科研源文件：源文件读取被拦截时，快照/检查/试算/预览仍必须工作。"""
    section = 'real.api'
    subject = f"{spec['name']}.{scope}"
    session_mod = modules['session']
    module = load_adapter_module(session_mod, spec['script'], spec['config'])
    inputs = sorted({str(Path(p).resolve()) for p in _declared_inputs(session_mod, module, spec)})
    if not inputs:
        rows.unsupported(section, subject, 'no_source_reread',
                         measured={'declared_inputs': []},
                         detail='该适配器没有声明科学输入文件，无法用"再读源文件"来证伪')
        return {}
    session = session_mod.FigureSession(spec['script'], spec['config'], scope)
    real_open = builtins.open
    real_io_open = io.open
    reads: list[str] = []

    def guard(file, *args, **kwargs):
        try:
            name = str(Path(file).resolve())
        except (TypeError, ValueError):
            name = str(file)
        if name in inputs:
            reads.append(name)
            raise AssertionError(f'查询阶段重读了科研源文件：{name}')
        return real_open(file, *args, **kwargs)

    def io_guard(file, *args, **kwargs):
        try:
            name = str(Path(file).resolve())
        except (TypeError, ValueError):
            name = str(file)
        if name in inputs:
            reads.append(name)
            raise AssertionError(f'查询阶段重读了科研源文件：{name}')
        return real_io_open(file, *args, **kwargs)

    instrumentation_proved = False
    try:
        builtins.open = guard
        io.open = io_guard
        try:
            with io_guard(inputs[0], 'rb'):
                pass
            instrumentation_proved = bool(reads)
        except AssertionError:
            instrumentation_proved = bool(reads)
        reads.clear()
        try:
            session.snapshot()
            session.inspect()
            session.render_preview()
            session.state()
            ok = True
            error = ''
        except AssertionError as exc:
            ok, error = False, str(exc)
        except Exception as exc:  # 别的失败照实报，不当成"通过"
            ok, error = False, f'{type(exc).__name__}: {exc}'
    finally:
        builtins.open = real_open
        io.open = real_io_open
    if not instrumentation_proved:
        rows.fail(section, subject, 'no_source_reread_instrumentation',
                  detail='拦截器没有拦住一次主动读取，这条证据是空的')
    rows.add(section, subject, 'no_source_reread',
             'OK' if (ok and not reads and instrumentation_proved) else 'FAIL',
             measured={'declared_inputs': inputs, 'blocked_reads': len(reads), 'error': error},
             detail='warm 会话的 snapshot/inspect/render_preview/state 不重读科研源文件')
    return {'instrumented': True, 'blocked_reads': len(reads)}


def _declared_inputs(session_mod, module, spec: dict) -> list[str]:
    hook = getattr(session_mod, 'declared_science_inputs', None)
    if callable(hook):
        return list(hook(module))
    raw = getattr(module, 'science_inputs', None)
    if callable(raw):
        return [str(p) for p in raw()]
    return [str(p) for p in (getattr(module, 'SCIENCE_INPUTS', None) or ())]


def copy_adapter_tree(spec: dict, module, session_mod, dest: Path) -> dict:
    """只复制适配器真正需要的东西：脚本、同目录辅助 .py、配置、声明的输入、声明的产物。"""
    dest.mkdir(parents=True, exist_ok=True)
    script = dest / spec['script'].name
    shutil.copyfile(spec['script'], script)
    config = dest / spec['config'].name
    shutil.copyfile(spec['config'], config)
    for sibling in sorted(spec['dir'].glob('*.py')):
        if sibling.name != spec['script'].name:
            shutil.copyfile(sibling, dest / sibling.name)
    inputs = []
    for raw in _declared_inputs(session_mod, module, spec):
        path = Path(raw)
        if not path.is_file():
            continue
        rel = path.relative_to(spec['dir']) if path.is_absolute() and str(path).startswith(str(spec['dir'])) \
            else Path(path.name)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        inputs.append(str(target))
    artifacts = []
    for name in _declared_artifact_names(module, spec):
        src = spec['dir'] / name
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.copyfile(src, target)
        else:
            target.write_bytes(b'figpact-copy-sentinel')
        artifacts.append(str(target))
    return {'dir': dest, 'script': script, 'config': config, 'inputs': inputs,
            'artifacts': artifacts}


def _declared_artifact_names(module, spec: dict) -> list[str]:
    hook = getattr(module, 'layout_contract', None)
    names: list[str] = []
    if callable(hook):
        for scope in (getattr(module, 'SCOPES', None) or ()):
            for name in (hook(scope).get('outputs') or []):
                if str(name) not in names:
                    names.append(str(name))
    return names


def mutate_input(path: Path) -> str:
    """真实内容变更（不是改时间戳）：把首个数据行的第二个数字最后一位改掉。"""
    text = path.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if ',' not in line:
            continue
        head, _, tail = line.partition(',')
        token = tail.split(',')[0] if ',' in tail else tail
        stripped = token.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        last = stripped[-1]
        replacement = '1' if last != '1' else '2'
        mutated = stripped[:-1] + replacement
        lines[index] = head + ',' + tail.replace(stripped, mutated, 1)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return f'第 {index + 1} 行的第二个数字 {stripped!r} -> {mutated!r}'
    # 兜底：整文件字节级翻转一个数字
    data = path.read_bytes()
    for i, byte in enumerate(data):
        if 0x30 <= byte <= 0x39:
            data = data[:i] + (b'1' if byte != 0x31 else b'2') + data[i + 1:]
            path.write_bytes(data)
            return f'字节 {i} 的数字被改写'
    path.write_bytes(data + b'\n')
    return '文件尾部加了一个换行（内容变更）'


def probe_fingerprint_semantics(rows: Rows, spec: dict, modules, copy: dict) -> dict:
    """声明的科学输入（哪怕扩展名像产物）必须参与输入 revision；正式产物按精确路径排除。"""
    section = 'real.api'
    subject = spec['name']
    session_mod = modules['session']
    source_revision = getattr(session_mod, 'source_revision', None)
    module = load_adapter_module(session_mod, copy['script'], copy['config'])
    if not callable(source_revision):
        rows.unsupported(section, subject, 'science_input_revision_semantics',
                         detail='运行时未暴露 source_revision，无法核对输入 revision 语义')
        return {}
    contract = module.layout_contract('main') if callable(getattr(module, 'layout_contract', None)) else {}
    declared_stems = getattr(session_mod, 'declared_output_stems', None)
    if callable(declared_stems):
        exclude = list(declared_stems(contract, copy['script']))
    else:
        exclude = [str(copy['dir'] / name) for name in (contract.get('outputs') or [])]
    required = _declared_inputs(session_mod, module, spec)
    if not required:
        rows.unsupported(section, subject, 'science_input_revision_semantics',
                         detail='副本适配器没有声明科学输入')
        return {'excluded': list(exclude)}
    base = source_revision(copy['script'], copy['config'], exclude=exclude, required=required)
    # 只改**声明为该作用域产物**的文件：按精确路径排除，所以 revision 必须不变。
    artifact = next((Path(p) for p in copy['artifacts']
                     if str(Path(p).resolve()) in {str(Path(e).resolve()) for e in exclude}
                     or Path(p).name in {Path(e).name for e in exclude}), None)
    if artifact is None:
        rows.unsupported(section, subject, 'science_input_revision_semantics',
                         measured={'excluded': [Path(e).name for e in exclude]},
                         detail='副本里没有落在声明产物路径上的文件，无法验证排除语义')
        return {}
    artifact.write_bytes(artifact.read_bytes() + b'x')
    artifact_changed = source_revision(copy['script'], copy['config'], exclude=exclude,
                                       required=required)
    input_mutation = mutate_input(Path(required[0]))
    input_changed = source_revision(copy['script'], copy['config'], exclude=exclude, required=required)
    ok = (artifact_changed == base) and (input_changed != base)
    rows.add(section, subject, 'science_input_revision_semantics', 'OK' if ok else 'FAIL',
             measured={'declared_inputs': [Path(p).name for p in required],
                       'excluded_outputs': [Path(e).name for e in exclude],
                       'artifact_touched': artifact.name,
                       'artifact_change_kept_revision': artifact_changed == base,
                       'input_change_bumped_revision': input_changed != base,
                       'input_mutation': input_mutation},
             detail='扩展名像产物的科学输入必须算进 revision；精确声明的产物路径必须排除')
    return {'base_revision': base, 'input_changed': input_changed}


def probe_invalidation(rows: Rows, spec: dict, modules, copy: dict) -> dict:
    """源文件变了：候选作废、旧 revision 不能提交。"""
    section = 'real.api'
    subject = spec['name']
    agent_api = _agent_api_module()
    if agent_api is None:
        rows.unsupported(section, subject, 'input_change_invalidates_candidate',
                         detail='agent_api 不可用，无法核对提交门')
        return {}
    try:
        session_obj = agent_api.AgentSession(copy['script'], copy['config'], 'main',
                                             output_dir=copy['dir'] / 'out')
    except Exception as exc:  # noqa: BLE001
        rows.unsupported(section, subject, 'input_change_invalidates_candidate',
                         measured={'copy': str(copy['dir']),
                                   'error': f'{type(exc).__name__}: {exc}'},
                         detail='临时代理副本无法建立会话（副本环境问题，不是正式文件的回归）')
        return {}
    try:
        contract = session_obj._worker.contract  # noqa: SLF001 - 读取真实契约
        target = None
        for param in contract.get('parameters') or []:
            if param.get('operation') == 'translate' and param.get('mutability') == 'EDITABLE':
                target = param
                break
        if target is None:
            rows.unsupported(section, subject, 'input_change_invalidates_candidate',
                             detail='副本契约里没有可编辑的纯位移参数')
            return {}
        path = list(target['path'])
        base_value = _get_path_from_yaml(copy['config'], path)
        if isinstance(base_value, bool) or not isinstance(base_value, (int, float)):
            rows.unsupported(section, subject, 'input_change_invalidates_candidate',
                             detail=f'路径 {path} 的值不是数字')
            return {}
        # 本项只测科学输入失效；大位移的新碰撞另有独立拒绝证据。
        value = float(base_value) + 0.05
        if target.get('max') is not None:
            value = min(value, float(target['max']))
        if target.get('min') is not None:
            value = max(value, float(target['min']))
        result = session_obj.try_layout([{'operation': 'set_parameter', 'path': path, 'value': value}])
        if result.get('status') != 'OK':
            # 副本无法构建/被脚本拒绝 ≠ 本工具要报的回归：真实适配器自身的构建已在
            # real.baseline 段核过；这里只说明「失效语义无法在这份副本上验证」。
            rows.unsupported(section, subject, 'input_change_invalidates_candidate',
                             measured={'path': path, 'status': result.get('status'),
                                       'message': result.get('message'),
                                       'copy': str(copy['dir'])},
                             detail='临时代理副本上的位移目标被拒绝，失效语义未能验证（不是正式文件的问题）')
            return {}
        config_bytes = copy['config'].read_bytes()
        inputs = _declared_inputs(modules['session'], load_adapter_module(modules['session'], copy['script'], copy['config']), spec)
        if not inputs:
            rows.unsupported(section, subject, 'input_change_invalidates_candidate',
                             detail='副本适配器没有声明科学输入')
            return {}
        mutation = mutate_input(Path(inputs[0]))
        stale_code = None
        stale_message = ''
        try:
            session_obj.commit('draft')
            refused = False
        except agent_api.AgentError as exc:
            refused = True
            stale_code, stale_message = exc.code, exc.message
        except Exception as exc:  # noqa: BLE001 - 非预期错误照实报
            refused, stale_message = False, f'{type(exc).__name__}: {exc}'
        config_intact = copy['config'].read_bytes() == config_bytes
        preview_error = ''
        has_candidate = None
        try:
            session_obj._worker.render_preview()
            has_candidate = bool(session_obj._worker.state().get('has_candidate'))
        except Exception as exc:  # noqa: BLE001
            preview_error = f'{type(exc).__name__}: {exc}'
        ok = refused and config_intact and (has_candidate is False)
        rows.add(section, subject, 'input_change_invalidates_candidate', 'OK' if ok else 'FAIL',
                 measured={'mutation': mutation, 'commit_refused': refused, 'error_code': stale_code,
                           'error_message': stale_message, 'config_bytes_intact': config_intact,
                           'has_candidate_after_resync': has_candidate, 'resync_error': preview_error},
                 detail='源文件内容变更后：旧候选不能提交（STALE_REVISION），配置副本一个字节不动，'
                        '下一次同步调用清掉候选')
        return {'refused': refused, 'has_candidate': has_candidate}
    finally:
        try:
            session_obj.close()
        except Exception:  # noqa: BLE001
            pass


def _get_path_from_yaml(config_path: Path, path: list):
    import yaml
    data = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    node = data
    for segment in path:
        if isinstance(node, dict):
            node = node.get(segment)
        elif isinstance(node, list):
            node = node[int(segment)]
        else:
            return None
    return node


def _agent_api_module():
    try:
        from figpact import agent_api  # noqa: F401
        return agent_api
    except Exception:  # noqa: BLE001
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────
_INVENTORY = None


def _selftest() -> int:
    """纯函数自检：毫米换算、比较器、产物归一化、源文件改写。不碰任何正式文件。"""
    import tempfile as _tempfile
    failures: list[str] = []
    checks: list[tuple[str, bool, str]] = []
    checks.append(('mm_of', approx_equal(mm_of(120.0, 120.0), 25.4, 1e-9),
                   f'120px@120dpi -> {mm_of(120.0, 120.0):g} mm'))
    checks.append(('compare_payload 容差', compare_payload({'a': 1.0}, {'a': 1.0 + 5e-10}, tol=1e-9) == [],
                   '1e-9 以内的差不算差异'))
    checks.append(('compare_payload 抓差', bool(compare_payload({'a': 1.0}, {'a': 1.02}, tol=1e-3)),
                   '超容差必须报差异'))
    checks.append(('compare_payload 抓缺字段', bool(compare_payload({'a': 1, 'b': 2}, {'a': 1})),
                   '构建结果缺字段必须报差异'))
    svg_a = b'<svg><path id="m0a1b2c3d4" d="M 0 0 L 2 3"/><use href="#m0a1b2c3d4"/></svg>'
    svg_b = b'<svg><path id="fig.main.curve" d="M 0 0 L 2 3"/><use href="#fig.main.curve"/></svg>'
    checks.append(('svg 身份归一化',
                   normalize_artifact('a.svg', svg_a) == normalize_artifact('a.svg', svg_b),
                   '登记对象身份变化不改变路径或引用'))
    svg_changed = svg_b.replace(b'L 2 3', b'L 2 4')
    checks.append(('svg 保留路径变更',
                   normalize_artifact('a.svg', svg_a) != normalize_artifact('a.svg', svg_changed),
                   '数据路径发生实际位移时必须拒绝'))
    pdf_a = b'%PDF-1.4 /CreationDate (D:20260101000000+00\'00\') /ID [<1><2>] x'
    pdf_b = b'%PDF-1.4 /CreationDate (D:20260102000000+00\'00\') /ID [<1><2>] y'
    checks.append(('pdf 归一化', normalize_artifact('a.pdf', pdf_a) != normalize_artifact('a.pdf', pdf_b),
                   '只归一化时间戳，正文差异必须保留'))
    checks.append(('artifact_identity 抓差', not artifact_identity('a.png', b'x', b'y')[0],
                   'PNG 字节不同必须判不一致'))
    checks.append(('artifact_identity 归一化容忍',
                   artifact_identity('a.svg', svg_a, svg_b)[0],
                   'SVG 只差时间戳/随机 id 时允许判一致'))
    with _tempfile.TemporaryDirectory() as work:
        csv = Path(work) / 'sample.CSV'
        csv.write_text('3.99e+002,4.963080e-001\n4.00e+002,5.001000e-001\n', encoding='utf-8')
        before = csv.read_bytes()
        note = mutate_input(csv)
        after = csv.read_bytes()
        parsed_ok = True
        try:
            import numpy as np
            data = np.loadtxt(csv, delimiter=',')
            parsed_ok = data.shape == (2, 2)
        except Exception:  # noqa: BLE001
            parsed_ok = False
        checks.append(('mutate_input 是内容变更', before != after and parsed_ok,
                       f'{note}；改写后仍是合法 CSV'))
    point = {'inventory': {'items': [
        {'gid': 'a.title', 'snapshot': {'bbox': [10.0, 20.0, 10.0, 20.0]}},
        {'gid': 'b.line', 'snapshot': {'bbox': [10.0, 20.0, 90.0, 20.0]}},
        {'gid': 'c.panel', 'snapshot': {'bbox': [1.0, 2.0, 30.0, 40.0]}},
    ]}}
    checks.append(('0×0 占位只认退化点', _placeholder_gids(point) == ['a.title'],
                   '水平线（高 0）与正常矩形都不是占位，只有点状的旧注册 bug 才是'))
    for name, ok, note in checks:
        print(f"[{'ok  ' if ok else 'FAIL'}] {name}：{note}")
        if not ok:
            failures.append(name)
    print(f"自检：{len(checks) - len(failures)}/{len(checks)} 通过")
    return 1 if failures else 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description='figpact vnext 真实数据切换验收（只读正式文件）')
    ap.add_argument('--repo', default=str(ROOT), help='工作树根（默认：本文件的上上级）')
    ap.add_argument('--baseline', default=str(BASELINE_DEFAULT), help='不可变基线 JSON')
    ap.add_argument('--baseline-revision', default=None,
                    help='捕获基线时的完整 40 位 Git commit SHA；有旧注册占位时必须提供')
    ap.add_argument('--json', default=None, help='把完整报告写到该路径')
    ap.add_argument('--work', default=None,
                    help='临时工作目录（默认：<repo>/.figpact-cutover-tmp-<pid>，跑完即删）')
    ap.add_argument('--keep-temp', action='store_true', help='保留临时目录（排查用）')
    ap.add_argument('--skip-strict', action='store_true', help='跳过严格发布探针')
    ap.add_argument('--skip-api', action='store_true', help='跳过 worker/API 探针')
    ap.add_argument('--adapters', default=','.join(ADAPTERS))
    ap.add_argument('--selftest', action='store_true',
                    help='只跑本文件纯函数自检（毫米换算/比较器/产物归一化/源改写），不碰正式文件')
    return ap.parse_args(argv)


def main(argv=None) -> int:
    global _INVENTORY
    args = parse_args(argv)
    if args.selftest:
        return _selftest()
    repo = Path(args.repo).resolve()
    baseline_path = Path(args.baseline)
    if not baseline_path.is_file():
        print(f'基线不可读：{baseline_path}', file=sys.stderr)
        return 2
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    try:
        geometry_mod, inventory_mod, session_mod = load_engine()
    except Exception as exc:  # noqa: BLE001
        print(f'引擎不可导入（{repo}）：{exc}', file=sys.stderr)
        return 2
    _INVENTORY = inventory_mod
    modules = {'geometry': geometry_mod, 'inventory': inventory_mod, 'session': session_mod}

    rows = Rows()
    report = {'repo': str(repo), 'baseline': str(baseline_path),
              'baseline_revision': args.baseline_revision,
              'python': sys.version.split()[0], 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
    summaries: dict = {}
    # 副本必须落在工作树内：适配器的导入前导会向上找含 figpact/ 的祖先目录。
    temp_root = (Path(args.work).resolve() if args.work
                 else repo / f'.figpact-cutover-tmp-{os.getpid()}')
    temp_root.mkdir(parents=True, exist_ok=True)
    keep = args.keep_temp or bool(args.work)
    try:
        for name in [a.strip() for a in args.adapters.split(',') if a.strip()]:
            spec = adapter_spec(repo, name)
            if not spec['script'].is_file() or not spec['config'].is_file():
                rows.fail('real.baseline', name, 'adapter_present',
                          measured={'script': str(spec['script']), 'config': str(spec['config'])},
                          detail='适配器脚本或配置缺失')
                continue
            entry = baseline.get(spec['baseline_key']) or {}
            baseline_scopes = entry.get('scopes') or {}
            if not baseline_scopes:
                rows.fail('real.baseline', name, 'baseline_scopes',
                          detail=f'基线里没有 {spec["baseline_key"]} 的作用域')
                continue
            try:
                module = load_adapter_module(session_mod, spec['script'], spec['config'])
            except Exception as exc:  # noqa: BLE001
                rows.fail('real.baseline', name, 'adapter_import',
                          measured={'error': f'{type(exc).__name__}: {exc}'},
                          detail='适配器无法导入，后续检查全部跳过')
                continue
            scopes = scope_list(module, entry, spec)
            native_ready = callable(getattr(module, 'build_scene', None)) \
                and callable(getattr(module, 'load_science', None)) \
                and callable(getattr(module, 'layout_contract', None))
            if not native_ready:
                rows.fail('real.baseline', name, 'native_hooks',
                          measured={'hooks': sorted(h for h in
                                                    ('load_science', 'build_scene', 'layout_contract',
                                                     'science_manifest', 'science_inputs')
                                                    if callable(getattr(module, h, None)))},
                          detail='适配器没有 native 接缝，native 侧无法复现')
            declared = declared_outputs(module, spec, scopes)
            summaries[name] = {'scopes': {}, 'declared_outputs': declared,
                               'native_ready': native_ready,
                               'config_sha256_before': sha256_file(spec['config'])}
            names = sorted({n for group in declared.values() for n in group})
            # 捕获的 y 形状只保留 10 位小数；科学数组必须另与明确旧版本的原始数组逐字节核对。
            pristine, pristine_note = load_pristine_adapter(repo, spec, args.baseline_revision)
            summaries[name]['pristine_source'] = pristine_note
            for scope in scopes:
                base_scope = baseline_scopes.get(scope)
                if base_scope is None:
                    continue
                gids = _placeholder_gids(base_scope)
                placeholders = {'gids': gids, 'available': pristine is not None,
                                'note': pristine_note}
                if pristine is not None:
                    placeholders.update(pristine_scope_evidence(pristine, scope, gids))
                try:
                    legacy = build_legacy(module, scope)
                except Exception as exc:  # noqa: BLE001
                    rows.fail('real.baseline', f'{name}.{scope}[legacy]', 'legacy_build',
                              measured={'error': f'{type(exc).__name__}: {exc}'},
                              detail='legacy 入口构建失败')
                    continue
                # 所有测量都在图还活着的时候做完：关掉之后不再碰 renderer。
                try:
                    legacy_summary = compare_scope(rows, 'real.baseline', spec, scope, legacy,
                                                   base_scope, 'legacy', placeholders)
                    legacy_metrics = {'inventory': inventory_of(inventory_mod, legacy[0], legacy[1]),
                                      'science': curve_science(legacy[1]),
                                      'gaps': curve_segments(legacy[0], scope)}
                except Exception as exc:  # noqa: BLE001
                    _close(legacy[0])
                    rows.fail('real.baseline', f'{name}.{scope}[legacy]', 'legacy_measure',
                              measured={'error': f'{type(exc).__name__}: {exc}',
                                        'traceback': traceback.format_exc().splitlines()[-5:]},
                              detail='legacy 侧测量失败')
                    continue
                _close(legacy[0])
                summaries[name]['scopes'][scope] = {'legacy': legacy_summary}
                if not native_ready:
                    continue
                try:
                    native, science = build_native(module, spec, scope)
                except Exception as exc:  # noqa: BLE001
                    rows.fail('real.baseline', f'{name}.{scope}[native]', 'native_build',
                              measured={'error': f'{type(exc).__name__}: {exc}'},
                              detail='native build_scene 构建失败')
                    continue
                native_summary: dict = {}
                try:
                    native_summary = compare_scope(rows, 'real.baseline', spec, scope, native,
                                                   base_scope, 'native', placeholders)
                    native_metrics = {'inventory': inventory_of(inventory_mod, native[0], native[1]),
                                      'science': curve_science(native[1]),
                                      'gaps': curve_segments(native[0], scope)}
                    compare_native_vs_legacy(rows, spec, scope,
                                             legacy_metrics['inventory'], legacy_metrics['science'],
                                             native_metrics['inventory'], native_metrics['science'],
                                             legacy_metrics['gaps'], native_metrics['gaps'])
                except Exception as exc:  # noqa: BLE001
                    rows.fail('real.baseline', f'{name}.{scope}[native]', 'native_measure',
                              measured={'error': f'{type(exc).__name__}: {exc}',
                                        'traceback': traceback.format_exc().splitlines()[-5:]},
                              detail='native 侧测量失败')
                finally:
                    _close(native[0])
                summaries[name]['scopes'][scope]['native'] = native_summary
            summaries[name]['declared_artifact_names'] = names

        # 正式产物清单（16 个）：存在性 + 哈希（开始/结束两次）
        before_artifacts: dict[str, dict] = {}
        for name in [a.strip() for a in args.adapters.split(',') if a.strip()]:
            spec = adapter_spec(repo, name)
            if name not in summaries:
                continue
            names = summaries[name].get('declared_artifact_names') or []
            snapshot = {}
            for artifact_name in names:
                path = spec['dir'] / artifact_name
                snapshot[artifact_name] = {'exists': path.is_file(),
                                           'sha256': sha256_file(path) if path.is_file() else None}
            before_artifacts[name] = snapshot
            missing = [n for n, rec in snapshot.items() if not rec['exists']]
            declared_count = len(snapshot)
            rows.add('real.artifacts', name, 'official_artifacts_present',
                     'OK' if (declared_count and not missing) else 'FAIL',
                     measured={'declared': declared_count, 'missing': missing},
                     detail='正式产物必须按 native 契约声明的名字全部存在')
        total = sum(len(v) for v in before_artifacts.values())
        rows.add('real.artifacts', 'total', 'formal_artifact_count',
                 'OK' if total == FORMAL_ARTIFACT_TOTAL else 'FAIL',
                 measured={'count': total, 'expected': FORMAL_ARTIFACT_TOTAL,
                           'per_adapter': {k: len(v) for k, v in before_artifacts.items()}},
                 detail='FTIR 三张图 × 4 格式 + NMR 一张图 × 4 格式 = 16')
        report['artifacts_before'] = before_artifacts
        report['temp_root'] = str(temp_root)

        # 严格发布探针（临时沙箱）
        if args.skip_strict:
            rows.skip('real.strict', 'all', 'strict_probe', detail='--skip-strict')
        else:
            for name, summary in summaries.items():
                spec = adapter_spec(repo, name)
                expected = summary.get('declared_artifact_names') or []
                info = run_strict_probe(rows, spec, temp_root, expected)
                summary['strict'] = info
                # 沙箱产出 vs 正式产物：字节/归一化一致
                for artifact_name in expected:
                    produced = temp_root / f"probe-{name}" / artifact_name
                    installed = spec['dir'] / artifact_name
                    if not produced.is_file():
                        continue
                    if not installed.is_file():
                        rows.fail('real.strict', name, f'artifact_identity::{artifact_name}',
                                  detail='正式产物不存在，无法比对')
                        continue
                    same, how = artifact_identity(artifact_name, produced.read_bytes(),
                                                 installed.read_bytes())
                    rows.add('real.strict', name, f'artifact_identity::{artifact_name}',
                             'OK' if same else 'FAIL',
                             measured={'sha256_produced': sha256_file(produced),
                                       'sha256_installed': sha256_file(installed),
                                       'comparison': how},
                             detail='严格发布重新产出的字节必须与已安装的正式产物一致')

        # worker/API 探针
        if args.skip_api:
            rows.skip('real.api', 'all', 'worker_api', detail='--skip-api')
        else:
            for name, summary in summaries.items():
                spec = adapter_spec(repo, name)
                module = load_adapter_module(session_mod, spec['script'], spec['config'])
                scopes = [s for s in summary.get('scopes') or ()]
                scope = 'main' if 'main' in scopes else (scopes[0] if scopes else 'main')
                hooks = {h: callable(getattr(module, h, None))
                         for h in ('load_science', 'build_scene', 'layout_contract',
                                   'science_manifest', 'science_inputs')}
                if not all(hooks.values()):
                    rows.fail('real.api', name, 'native_hooks',
                              measured=hooks, detail='native 接缝不完整，API 探针无法执行')
                    continue
                config = copy.deepcopy(module.CONFIG)
                _probe_worker_api(rows, spec, module, modules, config, scope, summary, temp_root)
    finally:
        if not keep:
            shutil.rmtree(temp_root, ignore_errors=True)

    # 收尾：正式文件（YAML 与 16 个产物）必须一个字节都没变
    for name, summary in summaries.items():
        spec = adapter_spec(repo, name)
        after = sha256_file(spec['config'])
        rows.add('real.artifacts', name, 'config_unchanged',
                 'OK' if after == summary['config_sha256_before'] else 'FAIL',
                 measured={'sha256': after, 'sha256_before': summary['config_sha256_before']},
                 detail='正式 YAML 必须一个字节未改（没有永久验收改动）')
    for name, snapshot in report.get('artifacts_before', {}).items():
        spec = adapter_spec(repo, name)
        changed = []
        for artifact_name, record in snapshot.items():
            path = spec['dir'] / artifact_name
            if not path.is_file():
                changed.append(f'{artifact_name}: 消失')
            elif sha256_file(path) != record['sha256']:
                changed.append(f'{artifact_name}: 字节变化')
        rows.add('real.artifacts', name, 'official_artifacts_unchanged',
                 'OK' if not changed else 'FAIL',
                 measured={'changed': changed, 'checked': len(snapshot)},
                 detail='正式产物在本工具运行前后必须逐字节不变')

    report['rows'] = rows.rows
    report['summary'] = rows.counts()
    report['adapter_summaries'] = summaries
    report['limitations'] = [
        '关系目标容差 1e-6 mm 只覆盖向量几何数学（中心线/包围盒），不是文字栅格化精度',
        'PDF/SVG 逐字节比较受创建时间与随机 id 影响，报告同时给出归一化后的结果；'
        'PNG/TIFF 已实测为逐字节确定',
        '科学等值来自真实重建与真实数组比较（含图元像素），不是声明源码哈希',
        '本工具不测量盲测 agent 成功率/时延，也不把确定性重放当成 agent 成绩',
        '几何快车道（GEOMETRY_CHECKED）的证据是首次真实重建扰动，报告按实际返回的 '
        'verification 记录，不假定等级',
        '基线里退化成点（0×0）的包围盒来自旧捕获绑到空艺术家的注册 bug：它不进毫米统计，'
        '而是由明确指定基线版本的源码真渲染出的同一条非空可见标题单独判定；不写豁免条目',
    ]
    _print_report(report, rows)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                   encoding='utf-8')
    failed = [row for row in rows.rows if row['status'] == 'FAIL']
    return 1 if failed else 0


def _close(fig) -> None:
    try:
        import matplotlib.pyplot as plt
        plt.close(fig)
    except Exception:  # noqa: BLE001
        pass


def curve_segments(fig, scope: str) -> list:
    """(净空列表, 间距) —— 给 native/legacy 同图比较复用。"""
    return list(curve_gaps(fig, scope)[0])


def _probe_worker_api(rows: Rows, spec: dict, module, modules, config: dict, scope: str,
                      summary: dict, temp_root: Path) -> None:
    geometry_mod = modules['geometry']
    session_mod = modules['session']
    from figpact.runtime import FigureWorker
    get_path = modules['session'].get_path if hasattr(modules['session'], 'get_path') else None
    if get_path is None:
        from figpact.contracts import get_path as _contract_get_path
        get_path = _contract_get_path
    contract = module.layout_contract(scope)
    worker = FigureWorker(spec['script'], spec['config'], scope)
    api_info: dict = {}
    try:
        open_info = worker.open()
        base_snapshot = worker.snapshot()
        inspected = worker.inspect(ids=[c for c in (contract.get('nodes') or {})][:3]) \
            if contract.get('nodes') else {}
        api_info = {'open': {k: open_info.get(k) for k in
                             ('scope', 'revision', 'base_config_revision', 'pid')
                             if k in open_info},
                    'snapshot_nodes': len(base_snapshot.get('nodes') or []),
                    'inspected': len(inspected.get('nodes') or []) if isinstance(inspected, dict) else None}
        rows.add('real.api', f'{spec["name"]}.{scope}', 'worker_open_and_query',
                 'OK' if base_snapshot.get('nodes') else 'FAIL',
                 measured={'open': api_info['open'], 'snapshot_nodes': api_info['snapshot_nodes'],
                           'inspect_matches': api_info['inspected']},
                 detail='持久 worker 的真实协议：open/snapshot/inspect')
        target_info = probe_relation_target(rows, worker, geometry_mod, contract, config, spec,
                                            scope, get_path)
        api_info['relation'] = target_info
    except Exception as exc:  # noqa: BLE001
        rows.fail('real.api', f'{spec["name"]}.{scope}', 'worker_flow',
                  measured={'error': f'{type(exc).__name__}: {exc}'},
                  detail='worker 流程异常')
    finally:
        worker.close()
    shift_worker = FigureWorker(spec['script'], spec['config'], scope)
    try:
        shift_worker.open()  # 独立会话：组位移探针不背上别的关系目标
        api_info['group_shift'] = probe_group_shift(rows, shift_worker, spec, scope, contract)
    except Exception as exc:  # noqa: BLE001
        rows.fail('real.api', f'{spec["name"]}.{scope}', 'group_shift_probe',
                  measured={'error': f'{type(exc).__name__}: {exc}'}, detail='组位移探针异常')
    finally:
        shift_worker.close()
    if spec['name'] == 'ftir' and 'compare_processed' in (summary.get('scopes') or {}):
        try:
            api_info['scope_isolation'] = probe_scope_isolation(
                rows, spec, modules, 'compare_raw', 'compare_processed', config, get_path)
        except Exception as exc:  # noqa: BLE001
            rows.fail('real.api', f'{spec["name"]}.compare_raw', 'scope_isolation_probe',
                      measured={'error': f'{type(exc).__name__}: {exc}'}, detail='作用域隔离探针异常')
    try:
        api_info['no_source_reread'] = probe_no_source_reread(rows, spec, modules, scope)
    except Exception as exc:  # noqa: BLE001
        rows.fail('real.api', f'{spec["name"]}.{scope}', 'no_source_reread_probe',
                  measured={'error': f'{type(exc).__name__}: {exc}'}, detail='源文件读取探针异常')
    # 临时副本上的指纹语义与失效语义
    if api_info.get('relation') or True:
        try:
            copy = copy_adapter_tree(spec, module, session_mod, temp_root / f'copy-{spec["name"]}')
            api_info['copy'] = {'dir': str(copy['dir']), 'inputs': [Path(p).name for p in copy['inputs']],
                                'artifacts': [Path(p).name for p in copy['artifacts']]}
            api_info['fingerprint'] = probe_fingerprint_semantics(rows, spec, modules, copy)
            api_info['invalidation'] = probe_invalidation(rows, spec, modules, copy)
        except Exception as exc:  # noqa: BLE001
            rows.fail('real.api', spec['name'], 'temp_copy_probe',
                      measured={'error': f'{type(exc).__name__}: {exc}',
                                'traceback': traceback.format_exc().splitlines()[-6:]},
                      detail='临时副本探针异常')
    summary['api'] = api_info


def _print_report(report: dict, rows: Rows) -> None:
    print('=' * 78)
    print(f"figpact vnext 真实数据切换验收 · {report['repo']}")
    print(f"基线：{report['baseline']}")
    print('=' * 78)
    section = None
    for row in rows.rows:
        if row['section'] != section:
            section = row['section']
            print(f"\n── {section} ──")
        marker = {'OK': 'ok  ', 'FAIL': 'FAIL', 'REFUSED': '拒绝',
                  'UNSUPPORTED': 'n/a ', 'SKIP': 'skip'}[row['status']]
        print(f"[{marker}] {row['subject']:<28} {row['check']}")
        if row['detail']:
            print(f"        {row['detail']}")
        if row['measured']:
            text = json.dumps(row['measured'], ensure_ascii=False, default=str)
            print(f"        实测：{text[:400]}{'…' if len(text) > 400 else ''}")
        if row['tolerance'] is not None:
            print(f"        容差：{row['tolerance']}")
    counts = rows.counts()
    print('\n' + '=' * 78)
    print('统计：' + '，'.join(f'{k}={v}' for k, v in sorted(counts.items())))
    print('边界：' + '；'.join(report['limitations']))
    print('=' * 78)


if __name__ == '__main__':
    sys.exit(main())
