"""Python-native（无 YAML）布局绑定的读取、定位与计划（G4）。

本模块只做三件事：读脚本声明的 ``LAYOUT_MM`` → 用 ``ast`` 唯一定位那条绑定的字面量
→ 生成"只替换这一个字面量"的新源码字节并交给 G3b 的 ``figpact.source_writes`` 计划。
它**不**新建绘图引擎、**不**读写科学数据：scene / geometry / science / TargetOracle
一概由调用方复用（G4 工单第 2、5 条）。端到端流程 ``edit_layout_and_verify`` 只在**另
起的子进程**里按既有接缝重建一次来做实测，本进程不执行 ``build_scene``。

定位一律基于 ``ast``，且只在**模块级** ``LAYOUT_MM`` 字典字面量里按字符串 key 精确
匹配：同一份源码里别处的同名字面量（例如 ``SCIENCE_MM``）可能是科学数据，"用正则找
一个数字就直接改"正是该阶段明令禁止的。定位不到、同一 key 出现多次、或字面量不是
纯数字 ``[dx, dy]`` 时只返回候选与 ``confidence='low'``，一个字节都不改；任何源码写入
都必须由调用方显式授权，并走 journal（``plan_source_change`` → ``apply_source_change``）。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from .history import HistoryStore
from .source_writes import (FileChange, apply_source_change, plan_source_change,
                            restore_project)

__all__ = ['LayoutBindingError', 'VERIFY_TOL_MM', 'apply_planned_edit',
           'edit_layout_and_verify', 'locate_layout_literal', 'plan_layout_edit',
           'read_layout_binding', 'restore_layout_from_history']

#: 声明布局位移的模块级映射名。**不是配置项**：定位按名字找，改名等于没有声明。
LAYOUT_NAME = 'LAYOUT_MM'
#: LAYOUT_MM 的值是 ``[dx, dy]`` 两个毫米位移；别的形状判为不可安全定位。
LAYOUT_MM_PAIR = 2

_PROBE_COUNTER = [0]


class LayoutBindingError(ValueError):
    """声明读不出来：脚本不存在、无法建 loader、导入期抛异常、``LAYOUT_MM`` 形状非法。"""


# ------------------------------------------------------------------ 隔离装载

def read_layout_binding(script: Path) -> dict:
    """在隔离命名空间装载脚本，返回其声明的 ``LAYOUT_MM`` 映射（**深拷贝**）。

    与 ``session.load_module`` 同路数（``spec_from_file_location`` + 屏蔽 stdout），
    但更克制：模块名唯一且用完即从 ``sys.modules`` 摘下、``sys.path`` 只临时插脚本
    目录、不传 ``--config``/``--inventory``、不建 Figure、不写任何文件——脚本的
    ``if __name__ == '__main__'`` 块因此不会跑。没有 ``LAYOUT_MM`` 声明返回 ``{}``
    （"什么都没声明"是事实，不是错误）；脚本导入期自己抛异常则不吞，那是"这份源码
    当前根本读不出声明"。
    """
    script = Path(script)
    if not script.is_file():
        raise LayoutBindingError(f'{script}：脚本不存在，无法读取布局绑定')
    _PROBE_COUNTER[0] += 1
    name = f'figpact_native_probe_{_PROBE_COUNTER[0]}'
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise LayoutBindingError(f'无法为脚本创建 loader：{script}')
    module = importlib.util.module_from_spec(spec)
    parent = str(script.parent)
    argv = sys.argv
    sys.modules[name] = module
    sys.path.insert(0, parent)
    sys.argv = [str(script)]
    try:
        with redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
    finally:
        sys.argv = argv
        sys.path.remove(parent)
        sys.modules.pop(name, None)
    declared = getattr(module, LAYOUT_NAME, None)
    if declared is None:
        return {}
    if not isinstance(declared, dict) or not all(isinstance(item, str) for item in declared):
        raise LayoutBindingError(
            f'{script}：{LAYOUT_NAME} 必须是「字符串 → 值」的映射，'
            f'得到 {type(declared).__name__}')
    return copy.deepcopy(declared)


# ------------------------------------------------------------------ ast 定位

def _layout_dicts(tree: ast.Module) -> list[ast.Dict]:
    """模块级 ``LAYOUT_MM`` 的字典字面量（普通赋值与带注解赋值都认）。

    只看模块级、只看赋给这个名字的**字典字面量**：``LAYOUT_MM.update(...)`` 之类
    的动态拼装定位不了，就当没有声明——猜不得。
    """
    found: list[ast.Dict] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        if any(isinstance(target, ast.Name) and target.id == LAYOUT_NAME
               for target in targets):
            found.append(node.value)
    return found


def _char_span(source: str, node: ast.AST) -> tuple[int, int]:
    """``ast`` 的行/列 → 源码字符偏移 ``[start, end)``。

    列偏移在 CPython 里是**该行的 UTF-8 字节**偏移，注释里带中文就会与字符下标对不上，
    所以按行取字节前缀再解码回字符；多行字面量用 ``end_lineno`` 收尾。
    """
    lines = source.splitlines(keepends=True)
    starts: list[int] = []
    total = 0
    for text in lines:
        starts.append(total)
        total += len(text)

    def offset(lineno: int, col: int) -> int:
        raw = lines[lineno - 1].encode('utf-8')
        return starts[lineno - 1] + len(raw[:col].decode('utf-8'))

    return offset(node.lineno, node.col_offset), offset(node.end_lineno, node.end_col_offset)


def _numeric_pair(node: ast.expr) -> list[float] | None:
    """纯数字 ``[dx, dy]`` 字面量 → ``[float, float]``；其它形状返回 None。

    变量、函数调用、字符串、布尔、长度不等于 2、非有限值（``1e400`` 解析成 inf）一律
    判为不可安全定位：那段常量可能是排版，也可能是科学数据，本模块不猜。
    """
    if not isinstance(node, ast.List) or len(node.elts) != LAYOUT_MM_PAIR:
        return None
    numbers: list[float] = []
    for element in node.elts:
        if isinstance(element, ast.UnaryOp) and isinstance(element.op, ast.USub):
            element = element.operand
            sign = -1.0
        else:
            sign = 1.0
        if not isinstance(element, ast.Constant):
            return None
        value = element.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = sign * float(value)
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return numbers


def _layout_matches(source: str, key: str) -> list[dict[str, Any]]:
    """``LAYOUT_MM`` 里 key 的每一次出现，各带字面量在源码里的精确位置。

    语法都不成立的源码定位不到任何字面量（返回空列表）：那是"需要作者级改动"，不是
    可以猜一个位置就去改。
    """
    matches: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for table in _layout_dicts(tree):
        for spot, key_node in enumerate(table.keys):
            try:
                literal = ast.literal_eval(key_node)
            except (ValueError, SyntaxError, TypeError):
                continue
            if not isinstance(literal, str) or literal != key:
                continue
            value_node = table.values[spot]
            start, end = _char_span(source, value_node)
            matches.append({'key': key, 'start': start, 'end': end, 'line': value_node.lineno,
                            'value': _numeric_pair(value_node), 'text': source[start:end]})
    return matches


def locate_layout_literal(source: str, key: str) -> dict | None:
    """唯一定位：``LAYOUT_MM`` 里该 key 恰好出现一次、且字面量是纯数字 ``[dx, dy]``。

    返回 ``{'start': int, 'end': int, 'value': list[float], 'line': int}``，
    ``start``/``end`` 是可在源码文本上直接切片的字符偏移。不唯一或形状可疑返回 None
    ——想区分"没有绑定"和"有多个绑定"的调用方走 ``plan_layout_edit`` 的候选。
    """
    matches = _layout_matches(source, key)
    if len(matches) == 1 and matches[0]['value'] is not None:
        return {field: matches[0][field] for field in ('start', 'end', 'value', 'line')}
    return None


# -------------------------------------------------------------------- 计划

def _reject(status: str, candidates: list[dict[str, Any]], message: str) -> dict:
    """只给提案：候选 + 低置信度，且不产生任何文件变更。"""
    return {'status': status, 'candidates': candidates, 'confidence': 'low', 'message': message}


def _requested_pair(value: Any) -> list[float] | None:
    """校验调用方给的目标位移：两个有限数字，归一成 ``[float, float]``。"""
    if not isinstance(value, (list, tuple)) or len(value) != LAYOUT_MM_PAIR:
        return None
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return numbers


def _format_pair(value: list[float]) -> str:
    """``repr`` 往返无损：只改数字，绝不顺手重排或截断精度。"""
    return '[' + ', '.join(repr(number) for number in value) + ']'


def plan_layout_edit(script: Path, gid: str, value: list[float], *,
                     state_home: Path, reason: str) -> dict:
    """定位 → 生成新源码字节 → **只计划**（写 journal 与 blob，不改用户源码）。

    成功返回 ``{'status': 'OK', 'journal': {...}, 'before_sha256': ..., 'after_sha256': ...}``；
    新源码只把命中的那个字面量换掉，其余字节原样保留。任何不确定都停在候选：
    ``AMBIGUOUS``（同一 key 出现多次、或字面量不是纯数字 ``[dx, dy]``）与
    ``NEEDS_AUTHORING``（源码里没有这条绑定，或源码不是 UTF-8 文本）都附
    ``candidates`` 与 ``confidence='low'``，且不写任何文件。真正落盘要调用方拿
    journal id 显式授权给 ``apply_planned_edit``。
    """
    script = Path(script)
    try:
        source = script.read_bytes().decode('utf-8')
    except FileNotFoundError:
        return _reject('NEEDS_AUTHORING', [], f'{script}：脚本不存在，无法定位布局字面量')
    except UnicodeDecodeError:
        return _reject('NEEDS_AUTHORING', [],
                       f'{script}：源码不是 UTF-8 文本，ast 定位与字节级替换都无法保证')
    wanted = _requested_pair(value)
    if wanted is None:
        return _reject('INVALID', [], f'目标位移必须是两个有限数字，得到 {value!r}')
    matches = _layout_matches(source, gid)
    if not matches:
        return _reject('NEEDS_AUTHORING', [],
                       f'{LAYOUT_NAME} 里没有 {gid} 的布局字面量：需要作者级改动，不猜常量')
    if len(matches) > 1 or any(match['value'] is None for match in matches):
        candidates = [{field: match[field] for field in ('key', 'start', 'end', 'line', 'value', 'text')}
                      for match in matches]
        why = '同一 key 在 %s 里出现 %d 次' % (LAYOUT_NAME, len(matches)) if len(matches) > 1 \
            else '命中的字面量不是纯数字 [dx, dy]'
        return _reject('AMBIGUOUS', candidates,
                       f'{gid}：{why}；无法安全判定这是排版还是科学数据，只给候选')
    match = matches[0]
    before = source.encode('utf-8')
    after = (source[:match['start']] + _format_pair(wanted) + source[match['end']:]).encode('utf-8')
    before_sha256 = hashlib.sha256(before).hexdigest()
    after_sha256 = hashlib.sha256(after).hexdigest()
    journal = plan_source_change(
        [FileChange(path=script, before_sha256=before_sha256, after_bytes=after)],
        state_home=state_home, reason=reason)
    return {'status': 'OK', 'journal': journal,
            'before_sha256': before_sha256, 'after_sha256': after_sha256}


def apply_planned_edit(journal_id: str, *, state_home: Path, authorized: bool) -> dict:
    """授权为真才落地：走 G3b 的 ``apply_source_change``，journal 状态即事实。

    未授权直接拒绝且**不碰任何文件/状态**（授权检查在读取 journal 之前）。授权后返回
    更新过的 journal 与其状态（成功为 ``COMMITTED``；写入期失败会被 G3b 受控回滚）。
    """
    if not authorized:
        return {'status': 'UNAUTHORIZED', 'journal_id': journal_id,
                'message': f'拒绝写入 {journal_id}：源码变更需要显式授权'}
    journal = apply_source_change(journal_id, state_home=state_home)
    return {'status': journal.get('status'), 'journal': journal}


# -------------------------------------------------------------- 端到端流程

#: 重建实测允许的位移误差（毫米）：与 ``tests/test_python_native_example.py`` 同一约定。
VERIFY_TOL_MM = 0.01
#: 重建子进程的超时（秒）：装载 + 建图 + 量测是秒级，给足余量即可。
_PROBE_TIMEOUT_S = 300
_PROBE_MARKER = 'FIGPACT_PROBE '

#: 重建探针：**独立进程**里按 `FigureSession` 的真实接缝重建一次，把「画出来的毫米几何 +
#: 图元身份 + 科研载荷指纹」原样报回来。探针自己不判对错，判定留在调用方。
_PROBE_SOURCE = r'''
import hashlib
import json
import sys
import traceback

MARK = 'FIGPACT_PROBE '


def emit(payload):
    sys.stdout.write(MARK + json.dumps(payload, sort_keys=True) + '\n')


def measure(script, config, scope):
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from figpact.session import FigureSession, drawn_shapes, load_module_cached

    science_sha256 = None
    loader = getattr(load_module_cached(script, config), 'load_science', None)
    if callable(loader):
        science_sha256 = hashlib.sha256(
            json.dumps(loader(), sort_keys=True, default=repr).encode('utf-8')).hexdigest()
    with FigureSession(script, config, scope) as session:
        fig, registry = session.build_candidate(session.candidate_config)
        try:
            shapes = drawn_shapes(fig, registry, include_frames=True)
        finally:
            plt.close(fig)
        gids = sorted(registry.gids())
    geometry = {key: [float(value) for value in record['bbox_mm']]
                for key, record in shapes.items() if record.get('bbox_mm') is not None}
    emit({'ok': True, 'geometry': geometry, 'gids': gids, 'science_sha256': science_sha256})


try:
    measure(sys.argv[1], sys.argv[2], sys.argv[3])
except BaseException as error:
    traceback.print_exc()
    emit({'ok': False, 'error': '%s: %s' % (type(error).__name__, error)})
    raise SystemExit(1)
'''


def _measure_geometry(script: Path, config: Path, scope: str) -> dict:
    """**另起一个进程**真实重建一次，返回 ``{geometry, gids, science_sha256}``。

    刻意不在当前进程里量：本进程刚刚为计划碰过这份源码，`sys.modules`、模块缓存与
    matplotlib 的全局状态都可能让"重建"看到的还是改写前的世界。子进程从磁盘重新导入，
    测到的才是这次写入之后磁盘上的那份源码。
    """
    root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
    env['MPLBACKEND'] = 'Agg'
    command = [sys.executable, '-c', _PROBE_SOURCE, str(script), str(config), scope]
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=_PROBE_TIMEOUT_S, env=env,
                              cwd=str(Path(script).parent))
    except (OSError, subprocess.SubprocessError) as error:
        raise LayoutBindingError(f'重建子进程无法完成：{error}') from error
    reported = [line for line in (done.stdout or '').splitlines()
                if line.startswith(_PROBE_MARKER)]
    if not reported:
        detail = ((done.stderr or '').strip() or (done.stdout or '').strip() or '无输出')[-500:]
        raise LayoutBindingError(
            f'重建子进程没有给出测量结果（退出码 {done.returncode}）：{detail}')
    result = json.loads(reported[-1][len(_PROBE_MARKER):])
    if not result.get('ok'):
        raise LayoutBindingError(f"重建失败：{result.get('error')}")
    return result


def _verified_shift(before: dict, after: dict, target_key: str,
                    requested: list[float]) -> tuple[list[float] | None, list[str]]:
    """实测目标 gid 的包围盒位移，并逐键核对其余可见几何一动不动。

    返回 ``(实测位移, 问题清单)``；测不出来时位移为 ``None``，问题照记。
    """
    problems: list[str] = []
    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    if only_before or only_after:
        problems.append(f'可见几何的键集合变了：消失 {only_before}，新增 {only_after}')
    measured: list[float] | None = None
    if target_key not in before or target_key not in after:
        problems.append(f'{target_key} 在重建里测不到，无法证明位移')
    else:
        measured = [after[target_key][index] - before[target_key][index] for index in (0, 1)]
        for axis, (want, got) in enumerate(zip(requested, measured)):
            # 写成 `not (… <= …)`：NaN 也必须落进问题清单，不能靠比较为假冒充通过。
            if not abs(got - want) <= VERIFY_TOL_MM:
                problems.append(f'{target_key} 的 {"xy"[axis]} 实测位移 {got} mm，请求 {want} mm'
                                f'（容差 {VERIFY_TOL_MM} mm）')
    for key in sorted(set(before) & set(after)):
        if key == target_key:
            continue
        for axis, (was, now) in enumerate(zip(before[key], after[key])):
            if not abs(now - was) <= VERIFY_TOL_MM:
                problems.append(f'{key} 跟着动了（{"xyxy"[axis]}：{was} → {now}）')
    return measured, problems


def _journal_file_changes(journal: dict) -> list[dict]:
    """G3b journal 的文件条目 → history 的 ``file_changes[]``（blob 引用原样归档）。"""
    return [{'path': entry['path'],
             'before_sha256': entry['before_sha256'],
             'after_sha256': entry['after_sha256'],
             'is_binary': bool(entry.get('is_binary')),
             'before_blob': entry.get('before_blob'),
             'after_blob': entry.get('after_blob'),
             'diff': entry.get('diff')} for entry in journal['files']]


def edit_layout_and_verify(script, gid: str, value, *, state_home, config, scope: str,
                           authorized: bool, reason: str) -> dict:
    """计划 → 授权落地 → 另起进程实测 → 记 history 检查点（G4 端到端）。

    未授权只返回 ``status='PLANNED'`` 的计划：用户源码一个字节都不改（只有 G3b 的
    journal/blob 落在 ``state_home`` 里）。授权后每一步都拿事实说话——源码字节必须
    等于 after blob、目标 gid 的实测位移必须在 ``VERIFY_TOL_MM`` 内、其余测量键与科研
    载荷指纹必须一动不动；任一条不成立就以 ``MISMATCH``/``PROBE_FAILED``/``APPLY_FAILED``
    如实返回并列出 ``problems``，**绝不**报成功。通过后把这条写入记成 ``source_change``
    检查点，返回其 id。
    """
    script, config = Path(script).resolve(), Path(config).resolve()
    requested = _requested_pair(value)
    plan = plan_layout_edit(script, gid, value, state_home=state_home, reason=reason)
    answer = {'script': str(script), 'gid': gid, 'requested_mm': requested,
              'tolerance_mm': VERIFY_TOL_MM, 'plan_status': plan.get('status'),
              'written': False}
    if plan.get('status') != 'OK':
        return {**answer, 'status': plan.get('status'), 'plan': plan,
                'message': plan.get('message', '计划未通过，未写任何文件')}
    journal = plan['journal']
    if not authorized:
        return {**answer, 'status': 'PLANNED', 'journal_id': journal['id'],
                'before_sha256': plan['before_sha256'], 'after_sha256': plan['after_sha256'],
                'message': f"计划已就绪（journal {journal['id']}）；源码写入需要显式授权"}

    store = HistoryStore(script, config, scope, state_home=state_home)
    try:
        # 改写前先把磁盘上的真实世界量下来：位移是"改后减改前"，没有基线就证明不了任何事。
        try:
            baseline = _measure_geometry(script, config, scope)
        except LayoutBindingError as error:
            return {**answer, 'status': 'PROBE_FAILED', 'problems': [str(error)]}
        applied = apply_planned_edit(journal['id'], state_home=state_home, authorized=True)
        written = {**answer, 'written': True, 'journal_id': journal['id'],
                   'journal_status': applied.get('status')}
        if applied.get('status') != 'COMMITTED':
            return {**written, 'status': 'APPLY_FAILED',
                    'journal': applied.get('journal'),
                    'problems': [f"源码写入未提交：{applied.get('status')}"]}
        actual = hashlib.sha256(script.read_bytes()).hexdigest()
        try:
            observed = _measure_geometry(script, config, scope)
        except LayoutBindingError as error:
            return {**written, 'status': 'PROBE_FAILED', 'problems': [str(error)]}
        measured, problems = _verified_shift(baseline['geometry'], observed['geometry'],
                                             f'gid:{gid}', requested)
        if actual != plan['after_sha256']:
            problems.append(f'源码字节与 after blob 不符：磁盘 {actual}，'
                            f'after blob {plan["after_sha256"]}')
        if baseline['gids'] != observed['gids']:
            problems.append(f'图元身份变了：{baseline["gids"]} → {observed["gids"]}')
        if baseline['science_sha256'] != observed['science_sha256']:
            problems.append(f'科研载荷指纹变了：{baseline["science_sha256"]} → '
                            f'{observed["science_sha256"]}')

        head = store.head()
        checkpoint = store.append_source_change(
            {'kind': 'source_change', 'reason': reason, 'gid': gid,
             'requested_mm': requested, 'measured_mm': measured,
             'journal_id': journal['id'], 'problems': problems,
             'file_changes': _journal_file_changes(applied['journal'])},
            expected_head=None if head is None else head['id'],
            expected_file_sha256={entry['path']: entry['after_sha256']
                                  for entry in applied['journal']['files']})
        return {**written, 'status': 'OK' if not problems else 'MISMATCH',
                'measured_mm': measured, 'problems': problems,
                'checkpoint_id': checkpoint['id'],
                'verification': {'science_sha256_before': baseline['science_sha256'],
                                 'science_sha256_after': observed['science_sha256'],
                                 'gids': observed['gids'],
                                 'geometry_keys': len(observed['geometry'])}}
    finally:
        store.close()


def restore_layout_from_history(commit_id: str, *, script, config, scope: str, state_home,
                                authorized: bool, reason: str) -> dict:
    """把某次 ``source_change`` 检查点记录的 **before** 内容恢复回磁盘（新的前向写入）。

    ``commit_id`` 只需要这条路：检查点里归档的 ``file_changes[]`` 已经带着 before/after
    blob 与其 SHA256，递归性不看磁盘现状——当前磁盘是 before、历史内容是新写入的 after，
    走 G3b 的 ``restore_project`` 生成**新的 journal**，历史检查点与旧 journal 一个字节
    都不改。恢复本身同样落地，所以也记一个 ``source_change`` 检查点，否则 history 描述的
    "磁盘现状"会与真实磁盘对不上。``authorized`` 不为真时直接拒绝且不碰任何文件。
    """
    if not authorized:
        return {'status': 'UNAUTHORIZED', 'commit_id': commit_id,
                'message': f'拒绝恢复 {commit_id}：源码写入需要显式授权'}
    script, config = Path(script).resolve(), Path(config).resolve()
    store = HistoryStore(script, config, scope, state_home=state_home)
    try:
        changes = store.file_changes(commit_id)
        if not changes:
            return {'status': 'NO_FILE_CHANGES', 'commit_id': commit_id,
                    'message': f'{commit_id}：检查点里没有 file_changes，无从恢复'}
        wanted = [{**record, 'after_blob': record.get('before_blob'),
                   'after_sha256': record['before_sha256']} for record in changes]
        journal = restore_project(wanted, state_home=state_home, reason=reason)
        restored = {entry['path']: entry['after_sha256'] for entry in journal['files']}
        if journal.get('status') != 'COMMITTED':
            return {'status': 'RESTORE_FAILED', 'commit_id': commit_id,
                    'journal_id': journal['id'], 'journal_status': journal.get('status'),
                    'journal': journal, 'restored_sha256': restored}
        head = store.head()
        checkpoint = store.append_source_change(
            {'kind': 'source_change', 'reason': reason, 'restored_from': commit_id,
             'journal_id': journal['id'], 'file_changes': _journal_file_changes(journal)},
            expected_head=None if head is None else head['id'],
            expected_file_sha256=restored)
        return {'status': 'COMMITTED', 'commit_id': commit_id, 'journal_id': journal['id'],
                'checkpoint_id': checkpoint['id'], 'restored_sha256': restored,
                'restored_paths': sorted(restored)}
    finally:
        store.close()
