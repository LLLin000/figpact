"""原子发布与人工豁免管理。"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from figpact.qa import signature

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
    """人工豁免记录管理器。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        """加载 {签名: 理由}，无 reason 的条目不认。"""
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        out = {}
        for item in data.get("exemptions", []):
            sig = str(item.get("signature", ""))
            reason = str(item.get("reason", "")).strip()
            if sig and reason:
                out[sig] = reason
        return out

    def write(self, blockers: list[str], reason: str) -> None:
        """记录新的豁免。reason 为空抛出 ValueError。"""
        clean_reason = str(reason).strip()
        if not clean_reason:
            raise ValueError("豁免理由 (reason) 不能为空")

        existing = self.load()
        for b in blockers:
            sig = signature(b)
            if sig:
                existing[sig] = clean_reason

        payload = {
            "exemptions": [
                {"signature": sig, "reason": r} for sig, r in sorted(existing.items())
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
