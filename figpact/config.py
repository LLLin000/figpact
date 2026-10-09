"""配置与参数契约校验。"""
import math
from pathlib import Path
from typing import Any, Optional
import yaml


class ConfigError(Exception):
    """参数契约异常：未知 key / 缺 key / 非数字 / NaN·Inf / 超范围 / 非整数。"""
    pass


def _number(name: str, key: str, value: Any) -> float:
    """数字校验出口：bool 不是数字，NaN/±Inf 能穿过区间比较，两者都挡掉。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name}：{key} 必须是数字，得到 {value!r}")
    if not math.isfinite(value):
        raise ConfigError(f"{name}：{key} 不能是 NaN 或 Inf，得到 {value!r}")
    return float(value)


def check_schema(raw: dict[str, Any], schema: dict[str, Any], *, path: Optional[Path | str] = None) -> None:
    """按契约 schema 校验原始字典。不合法抛出 ConfigError，给出哪个 key、当前值、允许范围、建议值。
    
    schema 支持的形式：
    - key: (type, lo, hi)   数值标量，lo 与 hi 为闭区间边界
    - key: (bool,)          布尔型
    - key: (dict,) 或其它类型
    """
    name = Path(path).name if path else "配置"
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}：顶层必须是 `key: value` 映射")

    allowed = set(schema.keys())
    # 允许额外保留 shifts_mm 或由 schema 显式声明
    raw_keys = set(raw.keys())
    if unknown := sorted(raw_keys - allowed):
        raise ConfigError(f"{name}：未知参数 {unknown}；可用：{sorted(allowed)}")
    if missing := sorted(allowed - raw_keys):
        raise ConfigError(f"{name}：缺少参数 {missing}（不设代码内默认值）")

    for key, spec in schema.items():
        val = raw[key]
        if not isinstance(spec, (tuple, list)) or len(spec) == 0:
            continue
        typ = spec[0]

        if typ is bool:
            if not isinstance(val, bool):
                raise ConfigError(f"{name}：{key} 必须是布尔值 (true/false)，得到 {val!r}")
            continue

        if typ in (int, float):
            num = _number(name, key, val)
            lo, hi = spec[1], spec[2]
            if not (lo <= num <= hi):
                sug = min(max(num, lo), hi)
                if typ is int:
                    sug = int(sug)
                raise ConfigError(
                    f"{name}：{key} = {val} 超出允许范围 [{lo}, {hi}]；建议改成 {sug}"
                )
            if typ is int and num != int(num):
                raise ConfigError(f"{name}：{key} 必须是整数，得到 {val!r}；建议改成 {int(num)}")
        elif typ is dict:
            if not isinstance(val, dict):
                raise ConfigError(f"{name}：{key} 必须是字典映射，得到 {type(val).__name__} {val!r}")


def load_config(path: Path | str, schema: dict[str, Any], *, defaults: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """读取 YAML 并校验。defaults 仅在字段缺失时补全，默认 None 缺 key 必报错。"""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ConfigError(f"配置文件不存在：{p}")
    try:
        content = p.read_text(encoding="utf-8")
        raw = yaml.safe_load(content)
    except Exception as e:
        raise ConfigError(f"{p.name}：YAML 解析失败：{e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(f"{p.name}：顶层必须是字典映射")

    # 只有字段缺失才用 defaults
    if defaults:
        for k, v in defaults.items():
            if k not in raw:
                raw[k] = v

    check_schema(raw, schema, path=p)

    out: dict[str, Any] = {}
    for key, spec in schema.items():
        val = raw[key]
        typ = spec[0]
        if typ is int:
            out[key] = int(val)
        elif typ is float:
            out[key] = float(val)
        elif typ is bool:
            out[key] = bool(val)
        else:
            out[key] = val
    return out
