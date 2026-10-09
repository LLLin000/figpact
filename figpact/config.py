"""配置与参数契约校验。"""
from pathlib import Path
from typing import Any, Optional


class ConfigError(Exception):
    """参数契约异常：未知 key / 缺 key / 非数字 / NaN·Inf / 超范围 / 非整数。"""
    pass


def check_schema(raw: dict[str, Any], schema: dict[str, Any], *, path: Optional[Path | str] = None) -> None:
    """按契约 schema 校验原始字典。不合法抛出 ConfigError，给出哪个 key、当前值、允许范围、建议值。"""
    pass


def load_config(path: Path | str, schema: dict[str, Any], *, defaults: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """读取 YAML 并校验。defaults 仅在字段缺失时补全，默认 None 缺 key 必报错。"""
    pass
