"""Observe actual build purposes and Figure retention; never replace verification.

Run in a fresh process, with a fresh private output directory. RSS includes
Python/native allocations and allocator retention; it is not a leak verdict.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import json
from pathlib import Path
import sys
import weakref

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--script', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--edits', type=int, default=3)
    args = ap.parse_args()
    if args.edits < 1 or args.output_dir.exists():
        ap.error('positive edit count and fresh output directory required')
    args.output_dir.mkdir(parents=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib._pylab_helpers import Gcf
    import psutil
    from figpact.inspector_style import StyleSession

    process = psutil.Process()
    phase = 'startup'
    builds, created, refs, samples = [], [], [], []

    def stack(frame):
        names = []
        while frame is not None:
            filename = Path(frame.f_code.co_filename)
            if filename.parent.name == 'figpact':
                names.append(filename.stem + '.' + frame.f_code.co_name)
            frame = frame.f_back
        return list(reversed(names))

    def profile(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == '_build_figure' and Path(frame.f_code.co_filename).name == 'final_size.py':
            builds.append({'phase': phase, 'chain': stack(frame)})

    original_init = Figure.__init__
    def observed_init(self, *a, **kw):
        original_init(self, *a, **kw)
        refs.append(weakref.ref(self))
        created.append({'phase': phase, 'chain': stack(sys._getframe(1))})

    def sample(label):
        before_gc = sum(r() is not None for r in refs)
        rss_before = process.memory_info().rss
        gc.collect()
        samples.append({'phase': label, 'managed': len(Gcf.get_all_fig_managers()),
                        'created': len(refs), 'live_before_gc': before_gc,
                        'live_after_gc': sum(r() is not None for r in refs),
                        'rss_before_gc': rss_before, 'rss_after_gc': process.memory_info().rss})

    old_profile = sys.getprofile()
    Figure.__init__ = observed_init
    sys.setprofile(profile)
    session = None
    try:
        sample('before')
        session = StyleSession(script=args.script, config=args.config, scope='main', overlay=args.output_dir / 'style.json')
        sample(phase)
        for i in range(args.edits):
            frame = session.snapshot()
            target = next(t for t in frame['style']['targets'] if t['label'] == 'ylabel')
            phase = f'preview-{i}'
            result, code = session.preview({'frame_revision': frame['frame_revision'], 'target_id': target['target_id'], 'value': float(target['current_pt']) + 0.2})
            assert code == 200, result
            pending = result['style']['pending']
            sample(phase)
            phase = f'commit-{i}'
            result, code = session.commit({'candidate_id': pending['candidate_id'], 'frame_revision': pending['base_frame_revision'], 'expected_sha256': pending['expected_sha256'], 'save_draft': bool(pending.get('is_draft'))})
            assert code == 200 and result['status'] in ('COMMITTED', 'COMMITTED_DRAFT'), result
            sample(phase)
        session._drop_pending()
        session = None
        sample('released-session')
    finally:
        sys.setprofile(old_profile)
        Figure.__init__ = original_init
        if session is not None:
            session._drop_pending()
        # Observation ended; this cleanup is not part of the reported samples.
        plt.close('all')
    result = {'purpose': 'observational only; no verification/cache changes',
              'builds': builds, 'figure_creations': created, 'samples': samples,
              'build_counts': dict(Counter(b['phase'] for b in builds)),
              'limits': 'GC between actions changes retention/timing; RSS is not proof of live-object leakage; no timing comparisons'}
    (args.output_dir / 'trace.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'build_counts': result['build_counts'], 'samples': samples}, indent=2))


if __name__ == '__main__':
    main()
