"""无绑定图元的作者级修复提案（G4：`NEEDS_AUTHORING` + `AuthoringRepairSpec`）。

本模块只做「如实描述 + 提案」：读该脚本的源码、读会话里**已经声明**的契约与科学基线，
产出一份字段对齐 `docs/figpact-vnext-kit/schemas/authoring-repair-spec.schema.json`
的规格。它**不写任何用户文件**、不改科学数据、不建图、不另造绘图引擎；写入路径一律
走 G3b 的 journal，并且必须由调用方显式授权。

取证原则：信息不足时如实留空或标 `unknown`，绝不编造科学基线、源码位置或「已确认」的
编辑入口。源码位置只用 `ast` 静态判定，**不执行**用户脚本（执行就是副作用）——运行时的
绑定读取由 G4 适配器负责，这里是它的静态对应物，两者不共用执行路径。
"""
from __future__ import annotations

import ast
import hashlib
import math
from pathlib import Path

#: 设计包 schema 的版本枚举（只有一个值）。
SCHEMA_VERSION = 'figpact.vnext/1'
#: Python-native 脚本声明排版绑定的映射名（与 `examples/python_native/simple_figure.py` 一致）。
LAYOUT_BINDING_NAME = 'LAYOUT_MM'
#: 候选构建预算：配对的 before/after 各一次，再多就必须停下来请示。
MAX_CANDIDATE_BUILDS = 2
#: 取不到信息时的诚实字面量。
UNKNOWN = 'unknown'

__all__ = ['SCHEMA_VERSION', 'LAYOUT_BINDING_NAME', 'MAX_CANDIDATE_BUILDS', 'UNKNOWN',
           'build_repair_spec']


# --------------------------------------------------------------------------- #
# 源码静态取证（只解析，不执行）
# --------------------------------------------------------------------------- #

def _decode(data: bytes) -> str | None:
    """能当文本读就返回文本；二进制内容返回 None（不猜编码，不猜内容）。"""
    try:
        text = data.decode('utf8')
    except UnicodeDecodeError:
        return None
    return None if '\0' in text else text


def _parse(text: str | None):
    if not text or not text.strip():
        return None
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _targets(node: ast.stmt):
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def _binding_literals(tree) -> tuple[bool, dict[str, ast.AST]]:
    """模块级 `LAYOUT_MM` 的 (是否声明, key → 值字面量节点)。

    只看**模块级**赋值上的字典字面量：运行时构造出来的映射静态判不了，那就是「键读不出来」，
    不是「没有绑定」。
    """
    declared, out = False, {}
    for node in getattr(tree, 'body', []) or []:
        if not any(isinstance(t, ast.Name) and t.id == LAYOUT_BINDING_NAME
                   for t in _targets(node)):
            continue
        declared = True
        value = getattr(node, 'value', None)
        if not isinstance(value, ast.Dict):
            continue
        for key, item in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value:
                out.setdefault(key.value, item)
    return declared, out


def _numeric_pair(node: ast.AST | None) -> list[float] | None:
    """字面量是不是 `[dx, dy]` 这对纯数字（不是就返回 None：不解析表达式，不猜变量）。"""
    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) != 2:
        return None
    out = []
    for elt in node.elts:
        if not isinstance(elt, ast.Constant) or isinstance(elt.value, bool) \
                or not isinstance(elt.value, (int, float)) or not math.isfinite(elt.value):
            return None
        out.append(float(elt.value))
    return out


def _gid_functions(tree, target_gid: str) -> list[str]:
    """函数体内出现该 gid 字面量的模块级函数名：**候选**位置，不是确认的编辑入口。"""
    found = set()
    for node in ast.walk(tree) if tree is not None else ():
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and sub.value == target_gid:
                found.add(node.name)
                break
    return sorted(found)


def _sibling_files(script: Path, tree) -> list[str]:
    """脚本按名字导入、且确实躺在同目录的 Python 文件（必要的同目录源码资源）。

    返回的是**同目录文件路径**（带后缀的相对路径），与 `allowed_paths` 的路径语义一致；
    包、标准库、第三方等解析不到同目录实体文件的名字一律不列。
    """
    names = set()
    for node in ast.walk(tree) if tree is not None else ():
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            if node.module:
                names.add(node.module.split('.')[0])
    return sorted(f'{name}.py' for name in names if (script.parent / f'{name}.py').is_file())


# --------------------------------------------------------------------------- #
# 会话取证（鸭子类型；取不到就如实是 unknown）
# --------------------------------------------------------------------------- #

def _session_state(session) -> dict:
    state = getattr(session, 'state', None)
    if callable(state):
        try:
            state = state()
        except Exception:            # 会话自己的状态读取失败不该伪造出事实
            return {}
    return state if isinstance(state, dict) else {}


def _lookup(session, state: dict, name: str):
    value = getattr(session, name, None)
    return state.get(name) if value is None else value


def _intent_id(session, state: dict) -> str:
    value = _lookup(session, state, 'intent_id')
    if isinstance(value, str) and value:
        return value
    intent = _lookup(session, state, 'intent')
    if isinstance(intent, dict):
        value = intent.get('id')
    else:
        value = getattr(intent, 'id', None)
    return value if isinstance(value, str) and value else UNKNOWN


def _desired_delta(session, state: dict) -> list[float] | None:
    value = _lookup(session, state, 'desired_delta_mm')
    if value is None:
        intent = _lookup(session, state, 'intent')
        value = intent.get('delta_mm') if isinstance(intent, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in value):
        return None
    return [float(v) for v in value]


def _contract(session, state: dict) -> dict:
    value = _lookup(session, state, 'contract')
    return value if isinstance(value, dict) else {}


def _editable_gids(contract: dict) -> set[str]:
    out: set[str] = set()
    for record in contract.get('parameters') or []:
        if isinstance(record, dict) and str(record.get('mutability') or '').upper() == 'EDITABLE':
            out.update(gid for gid in record.get('objects') or []
                       if isinstance(gid, str) and gid)
    return out


def _locked_gids(contract: dict) -> list[str]:
    """作者声明为锁定科学/不可编辑的对象：修复不得碰它们（科学基线在 gid 上的摘要）。"""
    out: set[str] = set()
    for record in contract.get('parameters') or []:
        if not isinstance(record, dict):
            continue
        if str(record.get('mutability') or '').upper() == 'LOCKED_SCIENCE':
            out.update(gid for gid in record.get('objects') or []
                       if isinstance(gid, str) and gid)
    nodes = contract.get('nodes')
    for gid, meta in (nodes if isinstance(nodes, dict) else {}).items():
        if not isinstance(meta, dict) or not isinstance(gid, str) or not gid:
            continue
        if str(meta.get('science_policy') or '').upper() == 'LOCKED_SCIENCE' \
                or meta.get('editable') is False:
            out.add(gid)
    return sorted(out)


def _follow_gids(session, state: dict, target_gid: str, fixed: list[str]) -> list[str]:
    """允许跟随目标一起动的非目标 gid：只认会话按作者声明算出的归属闭包。"""
    closure = _lookup(session, state, 'owned_closure')
    if not callable(closure):
        return []
    try:
        closure = closure([target_gid])
    except Exception:
        return []
    if not isinstance(closure, (list, tuple)):
        return []
    blocked = set(fixed) | {target_gid}
    return sorted({gid for gid in closure if isinstance(gid, str) and gid and gid not in blocked})


# --------------------------------------------------------------------------- #
# 规格
# --------------------------------------------------------------------------- #

def build_repair_spec(*, script, target_gid: str, session) -> dict:
    """构造一份 `AuthoringRepairSpec`（只描述与提案，**不写任何文件**）。

    `session` 按鸭子类型取用：`contract` / `science_manifest` / `intent_id` /
    `desired_delta_mm` / `owned_closure()` / `state()`；会话里没有的事实一律留空或标
    `unknown`，绝不用环境猜测补上。
    """
    if not isinstance(target_gid, str) or not target_gid:
        raise ValueError('target_gid 必须是非空字符串')
    script = Path(script)
    data = script.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    tree = _parse(_decode(data))

    state = _session_state(session)
    contract = _contract(session, state)
    manifest = _lookup(session, state, 'science_manifest')

    declared, bindings = _binding_literals(tree)
    bound = target_gid in bindings
    literal = _numeric_pair(bindings.get(target_gid)) if bound else None

    allowed = sorted({script.name} | set(_sibling_files(script, tree)))
    fixed = _locked_gids(contract)
    follow = _follow_gids(session, state, target_gid, fixed)

    candidates: list[dict] = []
    if declared:
        candidates.append({'relative_path': script.name, 'symbol': LAYOUT_BINDING_NAME,
                           'certainty': 'confirmed' if literal is not None else 'candidate'})
    candidates.extend({'relative_path': script.name, 'symbol': name, 'certainty': 'candidate'}
                      for name in _gid_functions(tree, target_gid))

    why: list[str] = []
    if not contract:
        why.append('会话没有可用的布局契约，目标没有已证明的运行时编辑入口')
    elif target_gid not in _editable_gids(contract):
        why.append('目标 gid 不在任何 EDITABLE 契约路径的作用集合里')
    if not declared:
        why.append(f'源码没有声明 {LAYOUT_BINDING_NAME} 排版绑定，需要作者级新增一个局部自由度')
    elif not bindings:
        why.append(f'声明了 {LAYOUT_BINDING_NAME}，但静态读不出键（运行时构造），'
                   '需要作者级确认该 gid 的绑定位置')
    elif not bound:
        why.append(f'{LAYOUT_BINDING_NAME} 里没有该 gid 的绑定，需要作者级新增该键')
    else:
        why.append('绑定已在源码里声明，但源码写入仍需显式授权（本模块只出提案）')
    if isinstance(manifest, dict):
        science = f'科学基线：science_manifest 已声明（{len(manifest)} 个顶层小节），锁定对象见 fixed_gids。'
    else:
        science = '科学基线：science_manifest=unknown（会话未声明，修复后的科学等值无法证明）。'

    goal: dict = {
        'kind': 'adjust_existing_binding' if bound else 'new_edit_binding',
        'explanation': '不可直接编辑：' + '；'.join(why) + '。' + science,
    }
    delta = _desired_delta(session, state)
    if delta is not None:
        goal['desired_delta_mm'] = delta

    return {
        'schema_version': SCHEMA_VERSION,
        'repair_spec_id': 'repair-' + hashlib.sha256(
            f'{target_gid}\0{digest}'.encode('utf8')).hexdigest()[:16],
        'intent_id': _intent_id(session, state),
        'target_gid': target_gid,
        'base_source_sha256': digest,
        'goal': goal,
        'allowed_paths': allowed,
        'forbidden_science_changes': True,
        'fixed_gids': fixed,
        'allowed_follow_gids': follow,
        'source_candidates': candidates,
        'requires_explicit_approval': True,
        'max_candidate_builds': MAX_CANDIDATE_BUILDS,
    }
