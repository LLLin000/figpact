"""原生夹具的公共管路：CLI、构建、渲染、QA、strict、契约记录构造与校验。

原生夹具脚本（`native_*.py`）只声明**自己那张图是什么**，共用这里的：

- `run(module)`：`--config / --list-params / --inventory / --inspect / --strict / --out / --probe`
  六件事，独立可用（不依赖任何引擎会话）。产物一律先写 staging，
  最后一步交给 `figpact.publish.publish()` 发布——试算隔离由那条共享路径管。
- `param / node / group / relation`：契约记录的唯一构造入口（键名与共享契约一致）。
- `validate_contract`：记录级自检（路径存在、gid 存在、枚举合法、输出相对）。

导入本模块**不建 Figure、不写文件、不渲染**。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (后端必须先钉死)
import numpy as np  # noqa: E402

from figpact import inventory as figpact_inventory  # noqa: E402
from figpact import publish  # noqa: E402
from figpact import qa  # noqa: E402
from tests.fixtures import fixture_data

FIXTURES_DIR = Path(__file__).resolve().parent
REPO_ROOT = FIXTURES_DIR.parents[1]

#: 记录级枚举（共享契约）。缺省/未声明一律按 fail-closed 处理，绝不当成可编辑。
MUTABILITY = ("EDITABLE", "DERIVED", "FIXED_STYLE", "LOCKED_SCIENCE")
OPERATIONS = ("translate", "rebuild", "resize")
RELATION_KINDS = ("align", "gap", "clearance", "contain", "equal_size", "distribute")
#: science_policy 只有这两个（共享契约）：装饰性引导几何 = LAYOUT，科学内容 = LOCKED_SCIENCE。
SCIENCE_POLICY = ("LOCKED_SCIENCE", "LAYOUT")


# ── 小工具 ──────────────────────────────────────────────────────────────────
def file_digest(path: Path | str) -> str:
    """配置文件的内容指纹（基线修订号）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_science_inputs(module) -> tuple[Path, ...]:
    """声明的科学输入文件：逐条校验存在并返回绝对路径。

    `.png/.pdf/.json` 也可能是**科学的输入**（显微原图、仪器报告、处理元数据），
    所以这里按声明逐条认，不按扩展名一刀切；声明了却不存在 = 直接报错。
    生成式夹具（本仓五个都是）声明空元组——来源是种子 + 生成函数。
    """
    declared = None
    hook = getattr(module, "science_inputs", None)
    if callable(hook):
        declared = hook()
    elif hasattr(module, "SCIENCE_INPUTS"):
        declared = module.SCIENCE_INPUTS
    if declared is None:
        return ()
    resolved: list[Path] = []
    for item in declared:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            raise FileNotFoundError(f"{module.FIGURE_ID}：声明的科学输入不存在：{path}")
        resolved.append(path.resolve())
    outputs = set()
    for scope in getattr(module, "SCOPES", ()):  # 产物与输入不许撞名（按精确路径认，不按扩展名）
        try:
            outputs.update(module.layout_contract(scope)["outputs"])
        except Exception:
            continue
    clash = [p.name for p in resolved if p.name in outputs]
    if clash:
        raise ValueError(f"{module.FIGURE_ID}：科学输入与声明产物同名：{clash}")
    return tuple(resolved)


def artists_by_gid(fig) -> dict:
    """图里所有带 gid 的 Artist：{gid: artist}（科学自检按 gid 找真实对象）。"""
    found = fig.findobj(lambda obj: bool(getattr(obj, "get_gid", None) and obj.get_gid()))
    return {art.get_gid(): art for art in found if art.get_gid()}


def get_path(data: Any, path: list) -> Any:
    """按精确路径取值；任一段缺失抛 KeyError（不做模糊匹配）。"""
    node = data
    for segment in path:
        if isinstance(node, dict):
            if segment not in node:
                raise KeyError(f"路径段 {segment!r} 不存在")
            node = node[segment]
        elif isinstance(node, (list, tuple)):
            node = node[int(segment)]
        else:
            raise KeyError(f"路径段 {segment!r} 无法继续下探（{type(node).__name__}）")
    return node


def print_param_table(config: dict, scalars: dict, groups: dict, describe: dict) -> None:
    """人类/模型用的参数清单：按可见对象分组，打印当前值与允许范围。"""
    printed: set[str] = set()
    for title, keys in groups.items():
        print(f"=== {title} ===")
        for key in keys:
            desc, unit = describe.get(key, ("—", "—"))
            lo, hi = scalars[key][1], scalars[key][2]
            print(f"  {key:<20}{desc:<22}{unit:<6}当前 {config[key]!r:<8}范围 [{lo}, {hi}]")
            printed.add(key)
    leftovers = [k for k in scalars if k not in printed and k != "shifts_mm"]
    if leftovers:
        print("=== 其他 (Other) ===")
        for key in leftovers:
            print(f"  {key:<20}{'—':<22}{'—':<6}当前 {config[key]!r}")


def measurement_env() -> dict[str, Any]:
    """实测环境记录：渲染/字体环境是测量的一部分，不能靠猜。"""
    import matplotlib.font_manager as fm

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "matplotlib": matplotlib.__version__,
        "numpy": np.__version__,
        "backend": matplotlib.get_backend(),
        "rc_figure_dpi": float(matplotlib.rcParams["figure.dpi"]),
        "font_families": sorted({f.name for f in fm.fontManager.ttflist})[:8],
        "font_family_sample_size": len(fm.fontManager.ttflist),
    }


# ── 契约记录构造 ────────────────────────────────────────────────────────────
def param(key: str, path: list, *, unit: str, mutability: str, scopes: list[str],
          objects: list[str], operation: str, axis: str | None = None, scale: float = 1.0,
          minimum: float | None = None, maximum: float | None = None,
          expected: dict | None = None) -> dict:
    """一条参数记录。GID 里的点**从不**被拆开，路径永远是精确段数组。"""
    record = {
        "key": key,
        "path": list(path),
        "unit": unit,
        "mutability": mutability,
        "scopes": list(scopes),
        "objects": list(objects),
        "operation": operation,
        "axis": axis,
        "scale": float(scale),
        "expected": expected if expected is not None else {},
    }
    if minimum is not None:
        record["min"] = float(minimum)
    if maximum is not None:
        record["max"] = float(maximum)
    return record


def expect(kind: str, *, objects: list[str], axis: str | None = None,
           preserve: list[str] | None = None) -> dict:
    """`expected` 子记录：打算发生的效果 + 必须守住的东西。"""
    record = {
        "kind": kind,
        "objects": list(objects),
        "preserve": list(preserve or ()),
    }
    if axis is not None:
        record["axis"] = axis
    return record


def node(gid: str, *, type_name: str, parent: str | None, editable: bool,
         science_policy: str, label: str = "") -> dict:
    """一个节点的元数据：只发出被共享校验器认可的四个键。

    未声明的节点默认不可编辑 + LOCKED_SCIENCE（fail closed）。
    `label` 只写给读代码的人看，**不进记录**：契约记录的键集合会被逐键校验，
    多一个键就让整条记录被拒，所以这里不夹带任何自造字段。
    """
    return {
        "type": type_name,
        "parent": parent,
        "editable": bool(editable),
        "science_policy": science_policy,
    }


def contract_record(module, scope: str, *, parameters: list, nodes: dict, groups: list,
                    relations: list, outputs: list, source: dict | None = None) -> dict:
    """契约记录的**唯一对外形状**（键集合被 fail-closed 校验，多一个都不行）。

    允许的键：`scope / version / source / validation_error / out_of_scope /
    parameters / relations / groups / nodes / outputs`。夹具自己的补充信息一律
    塞进 `source`，不许平铺到顶层。
    """
    return {
        "scope": scope,
        "version": 1,
        "source": {
            "figure_id": getattr(module, "FIGURE_ID", ""),
            "script": Path(getattr(module, "__file__", "")).name,
            "config": Path(getattr(module, "CONFIG_PATH", "")).name,
            **(source or {}),
        },
        "parameters": list(parameters),
        "nodes": dict(nodes),
        "groups": list(groups),
        "relations": list(relations),
        "outputs": list(outputs),
    }


def group(gid: str, *, parent: str | None, members: list[str]) -> dict:
    return {"id": gid, "parent": parent, "members": list(members)}


def relation(rid: str, kind: str, objects: list[str], *, axis: str, anchor: str | None = None,
             method: str | None = None, controlled_by: list[list] | None = None,
             move: list[str] | None = None, target_mm: float | None = None) -> dict:
    """一条关系记录。`controlled_by` 是精确路径数组的列表，不是字符串。"""
    record = {
        "id": rid,
        "kind": kind,
        "objects": list(objects),
        "axis": axis,
        "controlled_by": [list(p) for p in (controlled_by or ())],
        "move": list(move or ()),
    }
    if anchor is not None:
        record["anchor"] = anchor
    if method is not None:
        record["method"] = method
    if target_mm is not None:
        record["target_mm"] = float(target_mm)
    return record


# ── 契约记录自检 ────────────────────────────────────────────────────────────
def validate_contract(contract: dict, *, config: dict | None = None,
                      scopes: tuple[str, ...] = (), gids: list[str] | None = None,
                      config_name: str = "配置") -> list[str]:
    """记录级自检：返回问题列表（空 = 通过）。不校验科学宣称，只校验可查性。

    守的是"别的 agent 不用读绘图源码也能按这些记录下手"：路径真的存在、
    gid 真的被构建出来、枚举合法、输出是相对路径。
    """
    problems: list[str] = []
    known = set(gids) if gids is not None else None

    if not isinstance(contract, dict):
        return ["契约必须是字典"]

    seen_paths: list[tuple] = []
    for record in contract.get("parameters", ()):
        key = record.get("key", "<无 key>")
        path = record.get("path")
        if not isinstance(path, list) or not path or not all(isinstance(s, (str, int)) for s in path):
            problems.append(f"参数 {key}：path 必须是精确段数组，得到 {path!r}")
            continue
        seen_paths.append(tuple(path))
        if record.get("mutability") not in MUTABILITY:
            problems.append(f"参数 {key}：mutability {record.get('mutability')!r} 不在 {MUTABILITY}")
        if not isinstance(record.get("unit"), str) or not record.get("unit"):
            problems.append(f"参数 {key}：unit 必填")
        if record.get("operation") not in OPERATIONS:
            problems.append(f"参数 {key}：operation {record.get('operation')!r} 不在 {OPERATIONS}")
        if record.get("operation") == "translate" and record.get("axis") not in ("x", "y"):
            problems.append(f"参数 {key}：纯位移必须声明 axis x|y")
        if record.get("axis") is not None and record.get("axis") not in ("x", "y"):
            problems.append(f"参数 {key}：axis {record.get('axis')!r} 非法")
        declared_scopes = record.get("scopes") or []
        if scopes and not set(declared_scopes) <= set(scopes):
            problems.append(f"参数 {key}：scopes {declared_scopes} 有本脚本不存在的 scope")
        if known is not None and not set(record.get("objects") or ()) <= known:
            missing = sorted(set(record.get("objects") or ()) - known)
            problems.append(f"参数 {key}：objects 里有未构建的 gid {missing}")
        if config is not None:
            try:
                get_path(config, path)
            except KeyError as exc:
                problems.append(f"参数 {key}：路径 {path} 在 {config_name} 里不存在（{exc}）")

    group_ids = {g.get("id") for g in contract.get("groups", ())}
    parent_ids = group_ids | set(contract.get("nodes", {}))
    for record in contract.get("nodes", {}).items() if isinstance(contract.get("nodes"), dict) else ():
        gid, meta = record
        if known is not None and gid not in known:
            problems.append(f"节点 {gid}：不在本次构建出的 gid 里")
        if meta.get("science_policy") not in SCIENCE_POLICY:
            problems.append(f"节点 {gid}：science_policy {meta.get('science_policy')!r} 不在 {SCIENCE_POLICY}")
        if not isinstance(meta.get("editable"), bool):
            problems.append(f"节点 {gid}：editable 必须是 bool")
        parent = meta.get("parent")
        if parent is not None and parent not in parent_ids:
            problems.append(f"节点 {gid}：parent {parent!r} 不是已声明的节点或组")

    for grp in contract.get("groups", ()):
        if grp.get("parent") is not None and grp.get("parent") not in parent_ids:
            problems.append(f"组 {grp.get('id')}：parent {grp.get('parent')!r} 未声明")
        if known is not None and not set(grp.get("members") or ()) <= known:
            missing = sorted(set(grp.get("members") or ()) - known)
            problems.append(f"组 {grp.get('id')}：members 里有未构建的 gid {missing}")

    for record in contract.get("relations", ()):
        rid = record.get("id", "<无 id>")
        if record.get("kind") not in RELATION_KINDS:
            problems.append(f"关系 {rid}：kind {record.get('kind')!r} 不在 {RELATION_KINDS}")
        if record.get("axis") not in ("x", "y"):
            problems.append(f"关系 {rid}：axis 必须是 x|y")
        if known is not None and not set(record.get("objects") or ()) <= known:
            missing = sorted(set(record.get("objects") or ()) - known)
            problems.append(f"关系 {rid}：objects 里有未构建的 gid {missing}")
        if known is not None and not set(record.get("move") or ()) <= known:
            missing = sorted(set(record.get("move") or ()) - known)
            problems.append(f"关系 {rid}：move 里有未构建的 gid {missing}")
        for path in record.get("controlled_by") or ():
            if not isinstance(path, list) or not path:
                problems.append(f"关系 {rid}：controlled_by 必须是精确段数组")
                continue
            if config is not None:
                try:
                    get_path(config, path)
                except KeyError as exc:
                    problems.append(f"关系 {rid}：controlled_by {path} 在 {config_name} 里不存在（{exc}）")

    outputs = contract.get("outputs") or []
    if not outputs:
        problems.append("契约：outputs 不得为空")
    for name in outputs:
        p = Path(str(name))
        if p.is_absolute() or ".." in p.parts:
            problems.append(f"契约：输出 {name!r} 必须是相对文件名")
    if len(set(outputs)) != len(outputs):
        problems.append("契约：outputs 有重复项")
    return problems


# ── 构建 / 渲染 ─────────────────────────────────────────────────────────────
def build_all(module, config: dict) -> list[tuple[str, Any, Any]]:
    """按声明的 scope 顺序构建全部 scope：每个 scope 一张独立 Figure。"""
    science = module.load_science()
    built = []
    for scope in module.SCOPES:
        fig, reg = module.build_scene(science, config, scope)
        built.append((scope, fig, reg))
    return built


def _qa_problems(module, science, fig) -> list[str]:
    """阻断项 = 现有 QA 的完整判定 + 夹具自己的科学自检（不弱化任何一项）。"""
    problems = list(qa.blocking_problems(fig))
    selfcheck = getattr(module, "science_selfcheck", None)
    if selfcheck is not None:
        for problem in selfcheck(science, fig=fig):
            if problem not in problems:
                problems.append(problem)
    return problems


def _render_outputs(fig, staging: Path, outputs: list[str], dpi: float) -> list[str]:
    written = []
    for name in outputs:
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, dpi=dpi)
        written.append(name)
    return written


def _inspect(module, config: dict, gid: str) -> int:
    scope = next((s for s in module.SCOPES if f".{s}." in gid), None)
    if scope is None:
        print(f"未找到 gid：{gid}（scope 不在 {list(module.SCOPES)} 里）")
        return 1
    science = module.load_science()
    fig, reg = module.build_scene(science, config, scope)
    artist = reg.get(gid)
    if artist is None:
        print(f"未找到 gid：{gid}")
        plt.close(fig)
        return 1
    contract = module.layout_contract(scope)
    payload = {
        "gid": gid,
        "scope": scope,
        "type": type(artist).__name__,
        "params": reg.params_of(gid),
        "node": contract["nodes"].get(gid, {"type": type(artist).__name__, "parent": None,
                                            "editable": False, "science_policy": "LOCKED_SCIENCE"}),
        "parameters_touching_it": [p["key"] for p in contract["parameters"] if gid in p["objects"]],
        "relations_touching_it": [r["id"] for r in contract["relations"]
                                  if gid in r["objects"] or gid in r["move"]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    plt.close(fig)
    return 0


def _inventory(module, config: dict, config_path: Path) -> int:
    payload: dict[str, Any] = {
        "figure_id": module.FIGURE_ID,
        "config": str(config_path),
        "config_revision": file_digest(config_path),
        "measurement": measurement_env(),
        "scopes": {},
    }
    for scope, fig, reg in build_all(module, config):
        contract = module.layout_contract(scope)
        payload["scopes"][scope] = {
            "inventory": figpact_inventory(fig, reg),
            "contract": contract,
            "contract_problems": validate_contract(contract, config=config, scopes=module.SCOPES,
                                                   gids=sorted(reg.all()), config_name=config_path.name),
            "outputs": contract["outputs"],
        }
        plt.close(fig)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _render(module, config: dict, config_path: Path, args: argparse.Namespace) -> int:
    explicit_out = args.out or args.probe
    if explicit_out:
        out_dir = Path(explicit_out).expanduser().resolve()
    else:
        out_dir = publish.probe_dir() or Path(tempfile.mkdtemp(prefix=f"figpact-native-{module.FIGURE_ID}-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    science = module.load_science()
    staging = Path(tempfile.mkdtemp(prefix=f"figpact-native-stage-{module.FIGURE_ID}-"))
    dpi = float(config["render_dpi"])
    print(f"[原生] {module.FIGURE_ID} · 配置 {config_path.name}（{file_digest(config_path)[:12]}）· "
          f"画布 {config['canvas_w_mm']}×{config['canvas_h_mm']} mm · {dpi:g} dpi")
    # 科学输入**当场**校验并取指纹：不读缓存里的声明（源文件改了就该看得出来）。
    sources = resolve_science_inputs(module)
    if sources:
        for path in sources:
            print(f"[科学输入] {path} sha256={file_digest(path)[:16]}")
    else:
        print(f"[科学输入] {module.FIGURE_ID}: 无外部科学输入文件（生成式载荷，种子 {fixture_data.SEED}）")

    problems: list[tuple[str, list[str]]] = []
    written_total: list[str] = []
    # 共享同一份产物名的作用域 = 同一张图（例：compare_raw / compare_processed）。
    # 产物按名字去重只写一次，QA 也只跑一次；作用域仍然逐个出现在报告里。
    rendered: dict[tuple[str, ...], list[str]] = {}
    try:
        for scope, fig, reg in build_all(module, config):
            outputs = tuple(module.layout_contract(scope)["outputs"])
            if outputs in rendered:
                print(f"[原生] {scope}: 与同图作用域共享产物 {list(outputs)}（按名字去重）")
            else:
                rendered[outputs] = _qa_problems(module, science, fig)
                written_total.extend(_render_outputs(fig, staging, list(outputs), dpi))
            problems.append((scope, rendered[outputs]))
            plt.close(fig)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    for scope, scope_problems in problems:
        if scope_problems:
            print(f"[QA] {module.FIGURE_ID} {scope}: {len(scope_problems)} 处阻断项")
            for problem in scope_problems:
                print(f"      {problem}")
        else:
            print(f"[QA] {module.FIGURE_ID} {scope}: 无阻断项 ✓")

    blocking = [p for _, ps in problems for p in ps]
    if blocking and args.strict:
        print(f"[验收] **未豁免**阻断项 {len(blocking)} 条：**拒绝发布**，{out_dir} 内正式输出未被覆盖")
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    published = publish.publish(staging, out_dir)
    shutil.rmtree(staging, ignore_errors=True)
    where = "试算沙箱" if publish.probe_dir() or args.probe else "输出目录"
    print(f"[验收] 已发布 {len(published)} 个文件到{where} {out_dir}"
          f"（声明 {len(written_total)} 个输出）")
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────
def parse_args(module, argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name, add_help=True, allow_abbrev=False,
        description=f"{module.FIGURE_ID} 原生夹具：渲染 / 清点 / 契约查询 / 严格验收")
    ap.add_argument("--config", default=None, help="配置文件路径（默认：脚本旁边的同名 YAML）")
    ap.add_argument("--list-params", action="store_true", help="打印参数清单后退出")
    ap.add_argument("--inventory", action="store_true", help="打印可见图元清单 + 布局契约（JSON）")
    ap.add_argument("--inspect", default=None, metavar="GID", help="查一个 gid 的绑定与契约记录")
    ap.add_argument("--strict", action="store_true", help="有阻断项则退出码非零且不发布")
    ap.add_argument("--out", default=None, help="正式输出目录（默认：临时目录）")
    ap.add_argument("--probe", default=None, help="试算沙箱目录（等价于 FIGPACT_PROBE_DIR）")
    return ap.parse_args(argv)


def run(module, argv: list[str] | None = None) -> int:
    """夹具 CLI 的唯一入口：返回进程退出码。"""
    # Windows 上 stdout 被重定向时会退回区域编码（GBK/cp1252）；QA 行里有
    # ✗ / «» / 上下标，一句 print 就是 UnicodeEncodeError 打死进程（退出码同样是 1，
    # 调用方会以为是"严格模式拒绝了这张图"）。先把流钉成 UTF-8 再输出任何东西。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pythonw 下是 None，或非 TextIOWrapper
            pass

    args = parse_args(module, argv)
    config_path = Path(args.config).expanduser() if args.config else Path(module.CONFIG_PATH)
    config = module.load_config(config_path)

    if args.list_params:
        module.list_params(config_path)
        return 0
    if args.inspect:
        return _inspect(module, config, args.inspect)
    if args.inventory:
        return _inventory(module, config, config_path)
    return _render(module, config, config_path, args)
