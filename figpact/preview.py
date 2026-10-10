"""A scoped review renders once. It is not a full publication check."""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import yaml


def revision(script, config) -> str:
    """Invalidate previews when configuration, source, or instrument inputs change."""
    script, config = Path(script).resolve(), Path(config).resolve()
    h = hashlib.sha256(config.read_bytes())
    roots = (script.parent, Path(__file__).parent)
    for root in roots:
        for p in sorted(root.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:
                continue
            if p.suffix.lower() in {'.png', '.pdf', '.svg', '.tif', '.tiff', '.md', '.json', '.pyc'}:
                continue
            stat = p.stat()
            h.update(f'{p}:{stat.st_size}:{stat.st_mtime_ns}'.encode('utf8'))
    return h.hexdigest()


def load_plot(script, config):
    """Import definitions only; the Figure is constructed by the caller."""
    import matplotlib
    matplotlib.use('Agg')
    script, config = Path(script).resolve(), Path(config).resolve()
    sys.path.insert(0, str(script.parent))
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.modules.pop('figure_style', None)
    spec = importlib.util.spec_from_file_location('figpact_plot', script)
    mod = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = [str(script), '--config', str(config), '--inventory']
    try:
        with redirect_stdout(io.StringIO()):
            spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def render_loaded(mod, scope):
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from figpact.inventory import inventory
    from figpact.qa import blocking_problems
    if scope not in mod.SCOPES:
        raise ValueError(f'未知 scope: {scope}')
    fig = None
    try:
        with redirect_stdout(io.StringIO()):
            fig, reg = mod.build_figure_and_registry(scope)
            check = getattr(mod, 'preview_qa', getattr(mod, 'blocking_problems', blocking_problems))
            qa = list(check(fig, scope) if hasattr(mod, 'preview_qa') else check(fig))
            inv = inventory(fig, reg)
            buf = io.BytesIO()
            with mpl.rc_context({'savefig.bbox': None}):
                fig.savefig(buf, format='png', dpi=fig.dpi, bbox_inches=None)
        return {'scope': scope, 'png': base64.b64encode(buf.getvalue()).decode('ascii'),
                'inventory': inv, 'qa': qa, 'qa_kind': 'preview_qa'}
    finally:
        if fig is not None:
            plt.close(fig)


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
        mod = load_plot(script, config)
        return render_loaded(mod, scope)


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
