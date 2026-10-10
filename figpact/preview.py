"""A scoped review renders once. It is not a full publication check.

GUI 面保持兼容：`preview(script=, config=, scope=, patch=, mode=)`、`revision(script, config)`、
`load_plot(script, config)` 的名字与返回结构不变。渲染本体走 `FigureSession`，
原生脚本（load_science/build_scene）与旧脚本（build_figure_and_registry）同一套路径。
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import yaml

from figpact.session import FigureSession, load_module, source_revision


def revision(script, config) -> str:
    """配置、脚本或其目录内数据源变化的合指纹（GUI 用它判断候选是否过期）。"""
    return source_revision(script, config)


def load_plot(script, config):
    """只导入定义，不建 Figure（GUI 用它做配置校验）。"""
    return load_module(script, config)


def render_once(script, config, scope, patch=None):
    from figpact.cli import _deep_merge_dict
    with tempfile.TemporaryDirectory(prefix='figpact-preview-') as td:
        config = Path(config).resolve()
        if patch:
            data = yaml.safe_load(config.read_text(encoding='utf8'))
            _deep_merge_dict(data, patch)
            candidate = Path(td) / 'candidate.yaml'
            candidate.write_text(yaml.safe_dump(data), encoding='utf8')
            config = candidate
        with FigureSession(script, config, scope) as session:
            payload = session.render_preview()
        return {key: payload[key] for key in
                ('scope', 'png', 'inventory', 'qa', 'qa_kind', 'relations', 'space')}


def preview(*, script, config, scope, patch=None, mode='review'):
    if mode != 'review':
        raise ValueError('preview only supports review; publication requires full strict')
    if patch is not None and not isinstance(patch, dict):
        raise ValueError('patch 必须是映射')
    t = time.perf_counter()
    req = {'script': str(Path(script).resolve()), 'config': str(Path(config).resolve()),
           'scope': scope, 'patch': patch}
    res = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'figpact.preview'],
                         input=json.dumps(req), text=True, encoding='utf8', capture_output=True,
                         cwd=str(Path(__file__).parent.parent), timeout=120)
    if res.returncode:
        raise ValueError(res.stderr.strip() or res.stdout.strip())
    result = json.loads(res.stdout)
    result.update(seconds=time.perf_counter()-t, revision=revision(script, config))
    return result


if __name__ == '__main__':
    request = json.load(sys.stdin)
    json.dump(render_once(**request), sys.stdout, ensure_ascii=False)
