"""逐文件原子发布（每份产物先写同目录临时文件再 os.replace）与人工豁免管理。"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from figpact.qa import diagnose, diagnostic_key

#: 试算沙箱开关。设了它 = 这一次只许写沙箱，正式输出一个字节都不许动。
#: 发布目标由**引擎**持有：任何走 `publish()` 的脚本都被自动改道，
#: 不必逐脚本去改调用点。`figpact try` 就是靠它跑试算的。
PROBE_ENV = "FIGPACT_PROBE_DIR"


def probe_dir() -> Optional[Path]:
    """当前试算沙箱目录；没设 `FIGPACT_PROBE_DIR` 时返回 None（= 正式输出）。"""
    val = os.environ.get(PROBE_ENV, "").strip()
    return Path(val) if val else None


def staging_dir(prefix: str = "figpact-") -> Path:
    """创建临时暂存目录。"""
    return Path(tempfile.mkdtemp(prefix=prefix))


def _rooted(root: Path, relative: Path, what: str) -> Path:
    """`root/relative` 解析后的真实路径；逃出 root（`..`、绝对路径、符号链接）直接拒绝。"""
    resolved = (root / relative).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"{what}的相对路径逃出允许的根：{relative} → {resolved}（根 {root}）")
    return resolved


def publish(staging: Path | str, target: Path | str) -> list[str]:
    """把暂存目录下的产物**逐个**原子替换进目标目录（每份先写同目录临时文件再 os.replace）。

    目录结构按相对路径保留：`panels/figure.png` 落在 `<目标>/panels/figure.png`，缺失的父目录
    按需创建，临时文件写在目标文件**自己的目录**里（所以每一步仍是同目录 rename）。返回的是相对
    路径（平铺产物的返回值与以前逐字相同）。

    这是**逐文件**替换，不是一批产物的崩溃一致事务：中途失败时，已经替换掉的产物保持新内容，
    还没轮到的保持旧内容。来源与目标在写每一个文件之前分别解析，任何逃出各自根的路径
    （`..`、绝对路径、指向根外的符号链接）当场拒绝，那个文件一个字节都不落。
    试算模式下 `target` 被沙箱目录顶掉 —— 这是 try 不会覆盖正式输出的底线。
    """
    src_root = Path(staging).resolve()
    dst_root = (probe_dir() or Path(target)).resolve()
    dst_root.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for src in sorted(src_root.rglob("*"), key=lambda p: p.relative_to(src_root).as_posix()):
        if not src.is_file():
            continue
        relative = src.relative_to(src_root)
        source = _rooted(src_root, relative, "暂存产物")
        dst = _rooted(dst_root, relative, "正式产物")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_dst = dst.parent / f".tmp_{dst.name}"
        shutil.copyfile(source, tmp_dst)
        os.replace(tmp_dst, dst)
        written.append(relative.as_posix())
    return written


class Exemptions:
    """人工豁免记录管理器。

    键是**结构化诊断 key**（规则 + 作用域 + 对象 id），不是把数字抹成 # 的文本签名：
    豁免「3p68」的排版缺陷**不会**顺带豁免「2p02」。
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> dict[tuple, str]:
        """加载 {诊断 key: 理由}，无 reason 或非结构化记录的条目不认。"""
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        out: dict[tuple, str] = {}
        for item in data.get("exemptions", []):
            reason = str(item.get("reason", "")).strip()
            rule_id = str(item.get("rule_id", "")).strip()
            if not reason or not rule_id:
                continue
            scope = str(item.get("scope", "")).strip()
            ids = tuple(str(v) for v in item.get("object_ids", []) or [])
            out[(rule_id, scope, tuple(sorted(ids)))] = reason
        return out

    def write(self, blockers: list[str], reason: str) -> None:
        """记录新的豁免。reason 为空抛出 ValueError。"""
        clean_reason = str(reason).strip()
        if not clean_reason:
            raise ValueError("豁免理由 (reason) 不能为空")

        existing = self.load()
        for b in blockers:
            key = diagnostic_key(diagnose(b))
            if key[0] == "UNCLASSIFIED":
                # 认不出来的文本不签字：签下去就是给一整片未知区域发通行证。
                print(f"[豁免] 跳过无法结构化的条目：{str(b)[:60]}")
                continue
            existing[key] = clean_reason

        payload = {
            "exemptions": [
                {"rule_id": k[0], "scope": k[1], "object_ids": list(k[2]), "reason": r}
                for k, r in sorted(existing.items())
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
