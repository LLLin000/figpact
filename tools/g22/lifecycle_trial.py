"""G22 actual FTIR repeated-edit ownership probe (3/10 cycles, failure paths).

Observers delegate to the real implementation. No global Figure cleanup,
verification replacement, caching, or timing claims. Use a fresh process and
private output directory. RSS/OS peak are observations, not leak assertions.
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--edits', type=int, choices=(3, 10), required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('fresh private output directory required')
    args.output_dir.mkdir(parents=True)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib._pylab_helpers import Gcf
    import psutil
    import numpy as np
    from figpact.inspector_style import StyleSession

    process = psutil.Process()
    external, external_ax = plt.subplots()
    external_ax.plot([0, 1], [2, 3])
    external_manager = external.canvas.manager
    baseline_managers = set(Gcf.get_all_fig_managers())
    overlay = args.output_dir / 'style.json'
    phase = 'startup'
    refs, creations, builds, samples, outcomes = [], [], [], [], []

    def chain(frame):
        result = []
        while frame is not None:
            filename = Path(frame.f_code.co_filename)
            if filename.parent.name == 'figpact':
                result.append(filename.stem + '.' + frame.f_code.co_name)
            frame = frame.f_back
        return list(reversed(result))

    def profile(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == '_build_figure' and Path(frame.f_code.co_filename).name == 'final_size.py':
            builds.append({'phase': phase, 'chain': chain(frame)})

    original_init = Figure.__init__
    def observed_init(self, *a, **kw):
        original_init(self, *a, **kw)
        refs.append(weakref.ref(self))
        creations.append({'phase': phase, 'chain': chain(sys._getframe(1))})

    def sample(label):
        before = sum(ref() is not None for ref in refs)
        gc.collect()
        managers = set(Gcf.get_all_fig_managers())
        memory = process.memory_info()
        internal_live = sum(ref() is not None for ref in refs)
        row = {'phase': label, 'created_total': len(refs),
               'internal_live_before_gc': before, 'internal_live_after_gc': internal_live,
               'managed_total': len(managers), 'managed_internal': len(managers - baseline_managers),
               'external_manager_alive': external_manager in managers,
               'rss_after_gc': memory.rss,
               'os_peak_rss': getattr(memory, 'peak_wset', None)}
        samples.append(row)
        assert managers == baseline_managers, row
        assert internal_live == 0, row
        assert external_manager in managers and np.array_equal(external_ax.lines[0].get_ydata(), [2, 3]), row

    old_profile = sys.getprofile()
    Figure.__init__ = observed_init
    sys.setprofile(profile)
    session = None
    try:
        sample('before')
        session = StyleSession(script=args.script, config=args.config, scope='main', overlay=overlay)
        sample(phase)
        first = session.snapshot()
        target = next(t for t in first['style']['targets'] if t['label'] == 'ylabel')
        base_pt = float(target['current_pt'])
        for i in range(args.edits):
            frame = session.snapshot()
            phase = f'preview-{i}'
            result, code = session.preview({'frame_revision': frame['frame_revision'],
                                           'target_id': target['target_id'],
                                           'value': base_pt + (0.2 if i % 2 == 0 else 0.4)})
            assert code == 200, result
            pending = result['style']['pending']
            sample(phase)
            phase = f'commit-{i}'
            result, code = session.commit({'candidate_id': pending['candidate_id'],
                                          'frame_revision': pending['base_frame_revision'],
                                          'expected_sha256': pending['expected_sha256'],
                                          'save_draft': bool(pending.get('is_draft'))})
            assert code == 200 and result['status'] == 'COMMITTED_DRAFT', result
            outcomes.append({'phase': phase, 'http': code, 'status': result['status']})
            sample(phase)
            if i in {0, args.edits // 2, args.edits - 1}:
                phase = f'qa-refusal-{i}'
                frame = session.snapshot()
                saved = overlay.read_bytes()
                refused, code = session.preview({'frame_revision': frame['frame_revision'],
                                                'target_id': target['target_id'], 'value': 4.0})
                assert code == 400 and refused['status'] == 'STYLE_REJECTED', refused
                assert overlay.read_bytes() == saved
                outcomes.append({'phase': phase, 'http': code, 'status': refused['status'], 'bytes_preserved': True})
                sample(phase)
        session._drop_pending()
        session = None
        sample('released-session')
    finally:
        sys.setprofile(old_profile)
        Figure.__init__ = original_init
        if session is not None:
            session._drop_pending()
        # Close only our external fixture, after ownership observations end.
        plt.close(external)
        result = {'edits': args.edits, 'outcomes': outcomes, 'samples': samples,
                  'build_counts': dict(Counter(b['phase'] for b in builds)),
                  'builds': builds, 'figure_creations': creations,
                  'limits': 'GC/profiling alter timing. RSS includes allocator retention. os_peak_rss is process lifetime peak on Windows, null if unavailable.'}
        (args.output_dir / 'lifecycle.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'edits': args.edits, 'build_counts': result['build_counts'], 'samples': samples}, indent=2))


if __name__ == '__main__':
    main()
