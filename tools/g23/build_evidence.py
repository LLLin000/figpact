"""Record actual verification builds without coalescing or replacing evidence.

As-built hashes are observational (no manifest hook and no extra Figure draw).
Authoritative audit snapshot hashes are recorded only when the real verifier
later creates them. Equal hashes never authorize reuse or skip any build.
"""
from __future__ import annotations

import argparse
from collections import Counter
import functools
import gc
import hashlib
import json
from pathlib import Path
import sys
import time
import weakref
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str,
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def chain():
    frame = sys._getframe(1)
    calls = []
    while frame is not None:
        file = Path(frame.f_code.co_filename)
        if file.parent.name == 'figpact':
            calls.append(file.stem + '.' + frame.f_code.co_name)
        frame = frame.f_back
    return list(reversed(calls))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('fresh private output directory required')
    args.output_dir.mkdir(parents=True)
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib._pylab_helpers import Gcf
    from figpact import final_size, style_overlay, science, change_audit
    from figpact.inspector_style import StyleSession

    builds, snapshots, operations = [], [], []
    phase = 'startup'
    live = weakref.WeakKeyDictionary()
    original_build = final_size._build_figure
    original_snapshots = style_overlay._snapshots

    @functools.wraps(original_build)
    def observed_build(module, cfg, scope):
        record: dict[str, Any] = {'build': len(builds), 'operation': phase, 'chain': chain()}
        builds.append(record)
        inputs: dict[str, Any] = {'scope': scope, 'config': cfg, 'files': {}}
        try:
            paths = [Path(module.__file__)]
            hook: Any = getattr(module, 'science_inputs', None)
            if callable(hook):
                paths.extend(Path(p) for p in hook())
            style = getattr(module, 'fs', None)
            if style is not None and getattr(style, '__file__', None):
                paths.append(Path(style.__file__))
            for path in paths:
                inputs['files'][str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
            record['input_sha256'] = digest(inputs)
            record['input_file_count'] = len(inputs['files'])
        except Exception as error:
            record['input_unmeasured'] = f'{type(error).__name__}: {error}'
        start = time.perf_counter()
        try:
            result = original_build(module, cfg, scope)
        finally:
            record['build_seconds'] = time.perf_counter() - start
        (fig, reg), resolved = result
        live[fig] = record
        record['resolved_scope'] = resolved
        # Pure content/view reads only: do not invoke manifest or QA/draw early.
        state = {'science_without_declarations': science.capture_science(fig, reg),
                 'view': change_audit._view_snapshot(fig),
                 'size_inches': list(fig.get_size_inches())}
        record['as_built_observational_sha256'] = digest(state)
        record['authoritative_snapshots'] = []
        return result

    @functools.wraps(original_snapshots)
    def observed_snapshots(fig, *a, **kw):
        start = time.perf_counter()
        result = original_snapshots(fig, *a, **kw)
        entry = {'operation': phase, 'chain': chain(), 'snapshot_seconds': time.perf_counter() - start,
                 'snapshot_sha256': digest(result), 'science_digest': result['science'].get('digest'),
                 'view_sha256': digest(result['view']), 'qa_records_sha256': digest(result['qa_records'])}
        record = live.get(fig)
        if record is not None:
            entry['build'] = record['build']
            record['authoritative_snapshots'].append(len(snapshots))
        snapshots.append(entry)
        return result

    final_size._build_figure = observed_build
    style_overlay._snapshots = observed_snapshots
    session = None
    try:
        session = StyleSession(script=args.script, config=args.config, scope='main',
                               overlay=args.output_dir / 'style.json')
        frame = session.snapshot()
        target = next(t for t in frame['style']['targets'] if t['label'] == 'ylabel')
        phase = 'preview'
        result, code = session.preview({'frame_revision': frame['frame_revision'],
                                       'target_id': target['target_id'], 'value': float(target['current_pt']) + 0.2})
        assert code == 200, result
        pending = result['style']['pending']
        operations.append({'operation': phase, 'http': code, 'status': result['status']})
        phase = 'commit'
        result, code = session.commit({'candidate_id': pending['candidate_id'],
                                      'frame_revision': pending['base_frame_revision'],
                                      'expected_sha256': pending['expected_sha256'],
                                      'save_draft': bool(pending.get('is_draft'))})
        assert code == 200 and result['status'] == 'COMMITTED_DRAFT', result
        operations.append({'operation': phase, 'http': code, 'status': result['status']})
        session._drop_pending()
        session = None
        phase = 'restart'
        session = StyleSession(script=args.script, config=args.config, scope='main',
                               overlay=args.output_dir / 'style.json')
        restored = session.snapshot()
        assert next(t for t in restored['style']['targets'] if t['target_id'] == target['target_id'])['saved_pt'] == float(target['current_pt']) + 0.2
        session._drop_pending()
        session = None
    finally:
        final_size._build_figure = original_build
        style_overlay._snapshots = original_snapshots
        if session is not None:
            session._drop_pending()
        gc.collect()
        result = {'builds': builds, 'snapshots': snapshots, 'operations': operations,
                  'counts': dict(Counter(b['operation'] for b in builds)),
                  'managed_figures_after_gc': len(Gcf.get_all_fig_managers()),
                  'limits': 'Observed hashes/time are not reuse authority. Extra hashing changes elapsed time; no performance benchmark. Probe does not close any Figure globally.'}
        (args.output_dir / 'build_evidence.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    assert result['counts'] == {'startup': 2, 'preview': 12, 'commit': 12, 'restart': 11}, result['counts']
    assert result['managed_figures_after_gc'] == 0
    assert all('input_sha256' in b and 'as_built_observational_sha256' in b for b in builds)
    print(json.dumps({'counts': result['counts'], 'audit_snapshots': len(snapshots),
                      'managed_after_gc': result['managed_figures_after_gc']}, indent=2))


if __name__ == '__main__':
    main()
