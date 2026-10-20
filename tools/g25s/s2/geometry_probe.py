"""Record actual unsupported external Artist boundaries; no edit exemptions."""
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from figpact import scene
from figpact.registry import GidRegistry

CASES = [
    ('surface3d', 'tools/g25s/gallery/raw/mplot3d_surface3d.py', [0]),
    ('heatmap', 'tools/g25s/compatible/heatmap.py', [1, 2]),
    ('streamplot', 'tools/g25s/compatible/stream.py', [0]),
]


def main():
    results = []
    for name, relative, indices in CASES:
        plt.close('all')
        with matplotlib.rc_context(), patch.object(plt, 'show'):
            runpy.run_path(str(ROOT / relative), run_name='__main__')
        figures = [plt.figure(n) for n in plt.get_fignums()]
        for index in indices:
            snap = scene.snapshot(figures[index], GidRegistry(scope=f'fig{index}'), scope=f'fig{index}')
            blocked = {i for d in snap['diagnostics'] if d['severity'] == 'blocking' for i in d['ids']}
            results.append({'source': relative, 'case': name, 'scope': f'fig{index}',
                'blocking_diagnostics': [d for d in snap['diagnostics'] if d['severity'] == 'blocking'],
                'blocking_nodes': [n for n in snap['nodes'] if n['id'] in blocked],
                'json_finite': True, 'boundary': 'REJECTED_UNMEASURABLE' if blocked else 'MEASURED'})
    plt.close('all')
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'tools/g25s/s2/geometry-boundaries.json'
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps([{'case': r['case'], 'scope': r['scope'], 'boundary': r['boundary'],
                      'artist_types': [n['artist_type'] for n in r['blocking_nodes']]} for r in results], indent=2))


if __name__ == '__main__':
    main()
