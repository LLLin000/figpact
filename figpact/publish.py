"""原子发布与人工豁免管理。"""
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


def publish(staging: Path | str, target: Path | str) -> list[str]:
    """将暂存目录下的产物原子替换到目标目录（先写临时文件再 os.replace）。

    试算模式下 `target` 被沙箱目录顶掉 —— 这是 try 不会覆盖正式输出的底线。
    """
    src_dir = Path(staging)
    dst_dir = probe_dir() or Path(target)
    dst_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        dst = dst_dir / src.name
        # 原子替换：同目录下写临时文件然后 os.replace
        tmp_dst = dst_dir / f".tmp_{src.name}"
        shutil.copyfile(src, tmp_dst)
        os.replace(tmp_dst, dst)
        written.append(src.name)
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
