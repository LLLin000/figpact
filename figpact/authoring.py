"""无绑定图元的作者级修复提案（G4：`NEEDS_AUTHORING` + `AuthoringRepairSpec`）。

本模块只做「如实描述 + 提案」：读该脚本的源码、读会话里**已经声明**的契约与科学基线，
产出一份字段对齐 `docs/figpact-vnext-kit/schemas/authoring-repair-spec.schema.json`
的规格。它**不写任何用户文件**、不改科学数据、不建图、不另造绘图引擎；写入路径一律
走 G3b 的 journal，并且必须由调用方显式授权。

取证原则：信息不足时如实留空或标 `unknown`，绝不编造科学基线、源码位置或「已确认」的
编辑入口。源码位置只用 `ast` 静态判定，**不执行**用户脚本（执行就是副作用）——运行时的
绑定读取由 G4 适配器负责，这里是它的静态对应物，两者不共用执行路径。

`plan_authoring_binding` 是同一份取证的**写入侧**：给「一个绑定都没有」的脚本生成**最小**
作者化补丁（插入一个模块级位移映射 + 一个取值助手，只改写目标那一个 `xytext=` 实参），
经 G3b 的 journal 出计划——同样**零字节**写用户源码，落盘必须由调用方显式授权。
"""
from __future__ import annotations

import ast
import hashlib
import io
import math
import tokenize
from pathlib import Path

from . import source_writes

#: 设计包 schema 的版本枚举（只有一个值）。
SCHEMA_VERSION = 'figpact.vnext/1'
#: Python-native 脚本声明排版绑定的映射名（与 `examples/python_native/simple_figure.py` 一致）。
LAYOUT_BINDING_NAME = 'LAYOUT_MM'
#: 候选构建预算：配对的 before/after 各一次，再多就必须停下来请示。
MAX_CANDIDATE_BUILDS = 2
#: 取不到信息时的诚实字面量。
UNKNOWN = 'unknown'
#: 作者化写回插进源码的位移映射名与取值助手名：无绑定脚本靠这两个名字拿到**一个**局部自由度。
LEGACY_OFFSET_BINDING = 'LEGACY_LABEL_OFFSET_PT'
LEGACY_OFFSET_HELPER = '_legacy_offset_pt'
#: 本 kind 的位移单位：**pt**，与目标调用现场的 `textcoords="offset points"` 同一个坐标系
#: （把 mm 当 pt 用会静默放大 2.8 倍）。
OFFSET_UNITS = 'pt'

__all__ = ['SCHEMA_VERSION', 'LAYOUT_BINDING_NAME', 'LEGACY_OFFSET_BINDING',
           'LEGACY_OFFSET_HELPER', 'OFFSET_UNITS', 'MAX_CANDIDATE_BUILDS', 'UNKNOWN',
           'build_repair_spec', 'plan_authoring_binding']


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


# --------------------------------------------------------------------------- #
# 作者化写回：无绑定脚本的**最小**补丁（只计划，零字节写用户文件）
# --------------------------------------------------------------------------- #

def _proposal(status: str, candidates: list[dict], message: str) -> dict:
    """只给提案：候选 + 低置信度，且不产生任何文件变更（与 `python_native._reject` 同形）。"""
    return {'status': status, 'candidates': candidates, 'confidence': 'low', 'message': message}


def _line_starts(source: str) -> list[int]:
    """每行行首的字符偏移：`starts[lineno - 1]` 即该行第一个字符的位置。"""
    starts, total = [0], 0
    for line in source.splitlines(keepends=True):
        total += len(line)
        starts.append(total)
    return starts


def _char_span(starts: list[int], node) -> tuple[int, int] | None:
    """AST 节点在解码后文本里的字符区间 `[start, end)`；位置信息缺失或越界返回 None。"""
    lineno, col = getattr(node, 'lineno', None), getattr(node, 'col_offset', None)
    end_lineno, end_col = getattr(node, 'end_lineno', None), getattr(node, 'end_col_offset', None)
    if None in (lineno, col, end_lineno, end_col):
        return None
    try:
        start = starts[lineno - 1] + col
        end = starts[end_lineno - 1] + end_col
    except IndexError:
        return None
    return (start, end) if 0 <= start <= end <= starts[-1] else None


def _comments(source: str) -> list[tuple[int, str]]:
    """源码里的 (行号, 注释文本)；词法本身不成立时如实返回已读到的部分。"""
    out: list[tuple[int, str]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                out.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return out
    return out


def _keyword(node: ast.Call, name: str):
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _offset_pair(node) -> list[float] | None:
    """纯数字 `(dx, dy)` / `[dx, dy]` 字面量（允许一元负号）；其它形状一律 None。

    变量、调用、字符串、长度不等于 2、非有限值都判为不可安全改写：那段常量可能是排版位移，
    也可能是数据坐标，本模块不猜。
    """
    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) != 2:
        return None
    out: list[float] = []
    for element in node.elts:
        sign = 1.0
        if isinstance(element, ast.UnaryOp) and isinstance(element.op, ast.USub):
            element, sign = element.operand, -1.0
        if not isinstance(element, ast.Constant) or isinstance(element.value, bool) \
                or not isinstance(element.value, (int, float)):
            return None
        number = sign * float(element.value)
        if not math.isfinite(number):
            return None
        out.append(number)
    return out


def _pair(value) -> list[float] | None:
    """调用方给的位移：两个有限数字，归一成 `[float, float]`。"""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    out: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if not math.isfinite(number):
            return None
        out.append(number)
    return out


def _annotate_calls(tree) -> list[ast.Call]:
    """模块里每一次 `*.annotate(...)`（`ast` 顺序即源码顺序，不是行号猜的）。"""
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'annotate']
    return sorted(calls, key=lambda node: (node.lineno, node.col_offset))


def _annotation_text(call: ast.Call) -> str | None:
    """这次 `annotate(...)` 画出来的标签文本（位置参数或 `text=`；读不出就 None）。"""
    value = call.args[0] if call.args else _keyword(call, 'text')
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _gid_name_links(tree, gid: str) -> set[str]:
    """与 gid 字面量出现在**同一次调用**里的变量名（如 `reg.register(label_a, "<gid>")`）。

    这是「这次调用画出来的图元就是那个 gid」的静态证据：注册现场把变量与 gid 钉在一起。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not any(isinstance(arg, ast.Constant) and arg.value == gid for arg in node.args):
            continue
        names.update(arg.id for arg in node.args if isinstance(arg, ast.Name))
    return names


def _assigned_names(call: ast.Call, parents: dict) -> set[str]:
    """承载这次调用的赋值目标名（`label_a = ax.annotate(...)` → `{'label_a'}`）。"""
    node, names = call, set()
    while node is not None:
        parent = parents.get(node)
        if isinstance(parent, (ast.Assign, ast.AnnAssign)):
            for target in _targets(parent):
                if isinstance(target, ast.Name):
                    names.add(target.id)
            break
        if not isinstance(parent, (ast.Tuple, ast.List, ast.Starred, ast.Attribute,
                                   ast.Subscript, ast.Call)):
            break
        node = parent
    return names


def _evidence(comments, parents: dict, tree, call: ast.Call, gid: str) -> list[str]:
    """这次调用与目标 gid 的静态关联证据（按证据类型记名；一条都没有就不算命中）。"""
    found: list[str] = []
    last_line = call.end_lineno or call.lineno
    for line, text in comments:
        if gid in text and call.lineno - 2 <= line <= last_line:
            found.append('comment')
            break
    if _assigned_names(call, parents) & _gid_name_links(tree, gid):
        found.append('binding')
    text = _annotation_text(call)
    if text is not None and text in {gid, gid.rsplit('.', 1)[-1]}:
        found.append('label')
    return found


def _candidate(starts, call: ast.Call, evidence: list[str]) -> dict:
    """一次 `annotate(...)` 调用的如实汇报（含没法改的原因，供人看候选）。"""
    value = _keyword(call, 'xytext')
    textcoords = _keyword(call, 'textcoords')
    span = None if value is None else _char_span(starts, value)
    why: list[str] = []
    if value is None:
        why.append('调用没有 xytext 实参')
    elif _offset_pair(value) is None:
        why.append('xytext 不是纯数字 (dx, dy) 字面量')
    if not (isinstance(textcoords, ast.Constant) and textcoords.value == 'offset points'):
        why.append('textcoords 不是 "offset points"：pt 语义不成立')
    if not evidence:
        why.append(f'没有任何证据把 {call.lineno} 行的调用与目标 gid 联系起来')
    return {'kind': 'annotate', 'line': call.lineno, 'text': _annotation_text(call),
            'xytext': None if value is None else _offset_pair(value),
            'textcoords': textcoords.value if isinstance(textcoords, ast.Constant) else None,
            'evidence': list(evidence), 'why': why,
            'start': None if span is None else span[0], 'end': None if span is None else span[1]}


def _declares_offset_support(tree) -> bool:
    """源码里是否已经有本补丁要插入的名字（有就拒绝：本 kind 只从零新增这一处）。"""
    for node in getattr(tree, 'body', []) or []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == LEGACY_OFFSET_HELPER:
            return True
        if any(isinstance(target, ast.Name) and target.id == LEGACY_OFFSET_BINDING
               for target in _targets(node)):
            return True
    return False


def _insert_offset(starts: list[int], tree) -> int:
    """docstring / import 之后那一行的行首偏移：新代码插在这儿，`from __future__` 仍在最前。"""
    last = 0
    for node in getattr(tree, 'body', []) or []:
        docstring = isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
            and isinstance(node.value.value, str)
        if isinstance(node, (ast.Import, ast.ImportFrom)) or docstring:
            last = max(last, node.end_lineno or node.lineno)
    return starts[min(last, len(starts) - 1)]


def _problems_in_after(after: str, gid: str, wanted: list[float], base: list[float],
                       annotate_count: int) -> list[str]:
    """改写结果的**机械自检**：解析得动、只插了这一处映射、只改了目标那一个实参。"""
    tree = _parse(after)
    if tree is None:
        return ['改写后的源码语法不成立（改写区间算错了），不落任何字节']
    problems: list[str] = []
    if len(_annotate_calls(tree)) != annotate_count:
        problems.append('改写动了 annotate 调用的数量，只能改写目标那一个实参')
    table = None
    for node in getattr(tree, 'body', []) or []:
        if any(isinstance(target, ast.Name) and target.id == LEGACY_OFFSET_BINDING
               for target in _targets(node)):
            table = node
    if not isinstance(getattr(table, 'value', None), ast.Dict):
        problems.append(f'{LEGACY_OFFSET_BINDING} 没有以字典字面量出现在模块级')
    elif [(ast.literal_eval(key), _numeric_pair(value))
          for key, value in zip(table.value.keys, table.value.values)] != [(gid, wanted)]:
        problems.append(f'{LEGACY_OFFSET_BINDING} 的表内容不等于 {{"{gid}": {wanted}}}')
    helper = [node for node in getattr(tree, 'body', []) or []
              if isinstance(node, ast.FunctionDef) and node.name == LEGACY_OFFSET_HELPER]
    if len(helper) != 1:
        problems.append(f'模块级 {LEGACY_OFFSET_HELPER} 必须恰好定义一次，实得 {len(helper)} 次')
    rewired = []
    for call in _annotate_calls(tree):
        value = _keyword(call, 'xytext')
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
                and value.func.id == LEGACY_OFFSET_HELPER:
            rewired.append(value)
    if len(rewired) != 1:
        problems.append(f'应当恰好有一处 xytext 走 {LEGACY_OFFSET_HELPER}，实得 {len(rewired)} 处')
    else:
        args = rewired[0].args
        if len(args) != 2 or not (isinstance(args[0], ast.Constant) and args[0].value == gid) \
                or _offset_pair(args[1]) != base:
            problems.append(f'{LEGACY_OFFSET_HELPER} 的实参不是 ({gid!r}, {tuple(base)})')
    return problems


def plan_authoring_binding(script, gid: str, value_pt, *, base_offset_pt=None,
                           state_home, reason: str) -> dict:
    """无绑定脚本 → 受控作者化补丁的**计划**（写 journal/blob，零字节写用户源码）。

    补丁最小且受限，一共三处：

    ① 模块顶层（docstring/imports 之后）插入 ``LEGACY_LABEL_OFFSET_PT = {"<gid>": [dx, dy]}``；
    ② 插入取值助手 ``def _legacy_offset_pt(gid, base): return (base[0] + dx, base[1] + dy)``；
    ③ **只**把目标 gid 那一次 ``ax.annotate(..., xytext=(x, y), ...)`` 的 ``xytext=`` 实参
       改写成 ``_legacy_offset_pt("<gid>", (x, y))``；其余字节逐位原样。

    目标调用按 ``ast`` 定位，证据只有三类：注释里写了该 gid、该调用画出的图元在注册现场与
    该 gid 字面量钉在一起、标签文本等于 gid 末段。命中不唯一 → ``AMBIGUOUS``；一次都没命中
    → ``NEEDS_AUTHORING``；两种情况都附 ``candidates`` 且**零写入**。``value_pt`` 是位移增量，
    单位 **pt**（目标调用现场的 ``textcoords="offset points"`` 就是这个坐标系）；``value_pt``
    为 ``[0, 0]`` 时改写后的图与原件逐位相同。``base_offset_pt`` 是调用方声明的现场 ``xytext``
    现值，对不上就是过期事实 → ``STALE_BASE``，不按旧事实改写。
    """
    script = Path(script)
    if not isinstance(gid, str) or not gid:
        return _proposal('INVALID', [], f'gid 必须是非空字符串，得到 {gid!r}')
    wanted = _pair(value_pt)
    if wanted is None:
        return _proposal('INVALID', [], f'value_pt 必须是两个有限数字（单位 {OFFSET_UNITS}），'
                                         f'得到 {value_pt!r}')
    base_claimed = None if base_offset_pt is None else _pair(base_offset_pt)
    if base_offset_pt is not None and base_claimed is None:
        return _proposal('INVALID', [], f'base_offset_pt 必须是两个有限数字（单位 {OFFSET_UNITS}），'
                                         f'得到 {base_offset_pt!r}')
    try:
        source = script.read_bytes().decode('utf-8')
    except FileNotFoundError:
        return _proposal('NEEDS_AUTHORING', [], f'{script}：脚本不存在，无法定位标签调用')
    except UnicodeDecodeError:
        return _proposal('NEEDS_AUTHORING', [],
                         f'{script}：源码不是 UTF-8 文本，ast 定位与字节级改写都无法保证')
    tree = _parse(source)
    if tree is None:
        return _proposal('NEEDS_AUTHORING', [], f'{script}：源码语法不成立，无法定位目标调用')
    if _declares_offset_support(tree):
        return _proposal('NEEDS_AUTHORING', [],
                         f'源码已经声明 {LEGACY_OFFSET_BINDING} 或 {LEGACY_OFFSET_HELPER}：'
                         '本 kind 只从零新增这一处自由度，不叠加第二份')
    starts = _line_starts(source)
    comments = _comments(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    calls = _annotate_calls(tree)
    candidates = [_candidate(starts, call,
                             _evidence(comments, parents, tree, call, gid))
                  for call in calls]
    matched = [item for item in candidates if item['evidence']]
    hit = [item for item in matched if item['xytext'] is not None
           and item['textcoords'] == 'offset points' and item['start'] is not None]
    if not hit:
        return _proposal('NEEDS_AUTHORING', candidates,
                         f'没有可安全改写的 {gid} 目标调用（候选 {len(candidates)} 处）：'
                         '要改的调用必须唯一地关联到这个 gid、xytext 为纯数字、'
                         'textcoords="offset points"')
    if len(hit) > 1:
        return _proposal('AMBIGUOUS', candidates,
                         f'{gid}：有 {len(hit)} 处调用都像目标（第 '
                         f'{", ".join(str(item["line"]) for item in hit)} 行），'
                         '无法安全判定该改哪一处，只给候选')
    match = hit[0]
    if base_claimed is not None and base_claimed != match['xytext']:
        return _proposal('STALE_BASE', candidates,
                         f"{gid}：调用现场第 {match['line']} 行的 xytext {match['xytext']} "
                         f'与调用方声明的 base_offset_pt {base_claimed} 不符，'
                         '不按过期事实改写')

    key_text = f'"{gid}"' if '"' not in gid and '\\' not in gid else repr(gid)
    numbers = ', '.join(repr(number) for number in wanted)
    base_numbers = ', '.join(repr(number) for number in match['xytext'])
    block = (f'{LEGACY_OFFSET_BINDING} = {{{key_text}: [{numbers}]}}\n'
             '\n'
             '\n'
             f'def {LEGACY_OFFSET_HELPER}(gid, base):\n'
             f'    dx, dy = {LEGACY_OFFSET_BINDING}.get(gid, (0.0, 0.0))\n'
             '    return (base[0] + dx, base[1] + dy)')
    insert_at = _insert_offset(starts, tree)
    edits = [(insert_at, insert_at, '\n' + block + '\n\n'),
             (match['start'], match['end'],
              f'{LEGACY_OFFSET_HELPER}({key_text}, ({base_numbers}))')]
    after = source
    for start, end, text in sorted(edits, key=lambda item: item[0], reverse=True):
        after = after[:start] + text + after[end:]
    problems = _problems_in_after(after, gid, wanted, match['xytext'], len(calls))
    if problems:
        return _proposal('NEEDS_AUTHORING', candidates, '补丁自检未通过（零写入）：'
                                                        + '；'.join(problems))

    before = source.encode('utf-8')
    after_bytes = after.encode('utf-8')
    before_sha256 = hashlib.sha256(before).hexdigest()
    after_sha256 = hashlib.sha256(after_bytes).hexdigest()
    journal = source_writes.plan_source_change(
        [source_writes.FileChange(path=script, before_sha256=before_sha256,
                                  after_bytes=after_bytes)],
        state_home=state_home, reason=reason)
    return {'status': 'OK', 'units': OFFSET_UNITS, 'gid': gid,
            'value_pt': wanted, 'base_offset_pt': list(match['xytext']),
            'script': str(script), 'evidence': list(match['evidence']),
            'target_line': match['line'],
            'inserted': {'binding': LEGACY_OFFSET_BINDING, 'helper': LEGACY_OFFSET_HELPER,
                         'at': insert_at},
            'journal_id': journal['id'], 'journal': journal,
            'before_sha256': before_sha256, 'after_sha256': after_sha256,
            'diff': journal['files'][0].get('diff')}
