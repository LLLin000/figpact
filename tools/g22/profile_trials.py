"""G22 serial G20-protocol trials; actual operation timings, no verifier changes.

Reuse G20's complete workflow and exclusive phase hooks. Old benchmark global
cleanup is replaced by an ownership assertion, not used to hide leaked Figures.
Only run performance collection when other tests/experiments have finished.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import functools
import gc
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--summary', type=Path, required=True)
    for name in ('ftir', 'nmr'):
        parser.add_argument('--' + name + '-script', type=Path, required=True)
        parser.add_argument('--' + name + '-config', type=Path, required=True)
    parser.add_argument('--cck8-pure-script', type=Path, required=True)
    parser.add_argument('--cck8-full-script', type=Path)
    parser.add_argument('--cck8-full-env', type=Path)
    parser.add_argument('--rounds', type=int, choices=(1, 5), default=5)
    args = parser.parse_args()
    if args.output_dir.exists() or args.summary.exists():
        parser.error('fresh output and summary paths required')
    args.output_dir.mkdir(parents=True)

    import matplotlib
    matplotlib.use('Agg')
    from matplotlib._pylab_helpers import Gcf
    from figpact.inspector_style import StyleSession
    spec = importlib.util.spec_from_file_location('g20_protocol', ROOT / 'tools/g20/run_g20.py')
    assert spec is not None and spec.loader is not None
    protocol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(protocol)
    baseline = set(Gcf.get_all_fig_managers())

    def ownership_check():
        gc.collect()
        assert set(Gcf.get_all_fig_managers()) == baseline, 'benchmark retained pyplot Figures'
    setattr(protocol, '_close_all', ownership_check)

    events = []
    originals = {}
    for name in ('__init__', 'snapshot', 'preview', 'commit'):
        original = getattr(StyleSession, name)
        originals[name] = original
        def measured(fn, label):
            @functools.wraps(fn)
            def call(*a, **kw):
                start = time.perf_counter()
                try:
                    return fn(*a, **kw)
                finally:
                    events.append({'operation': label, 'seconds': time.perf_counter() - start})
            return call
        setattr(StyleSession, name, measured(original, name))

    original_phases = protocol.phases_plus
    round_events = []
    @contextmanager
    def phases(stats):
        offset = len(events)
        try:
            with original_phases(stats) as result:
                yield result
        finally:
            round_events.append(events[offset:])
    setattr(protocol, 'phases_plus', phases)

    def percentiles(values):
        return {'n': len(values), 'p50': protocol.percentile(values, 0.5),
                'p95': protocol.percentile(values, 0.95)}

    inputs: list[tuple[str, Path, Path | None, dict[str, str] | None]] = [
        ('ftir', args.ftir_script, args.ftir_config, None),
        ('nmr', args.nmr_script, args.nmr_config, None)]
    if args.cck8_full_script:
        if args.cck8_full_env is None:
            parser.error('full wrapper requires its archive-copy directory')
        inputs.append(('cck8-full', args.cck8_full_script, None,
                       {'G19_ARCHIVE_COPY': str(args.cck8_full_env.resolve())}))
    inputs.append(('cck8-pure', args.cck8_pure_script, None, None))
    samples = {}
    try:
        for name, script, config, env in inputs:
            outdir = args.output_dir / name
            outdir.mkdir()
            round_events.clear()
            data = protocol._run(name, script.resolve(), config.resolve() if config else None,
                                 'main', outdir, args.rounds, 'axis.title', env)
            assert len(data['rounds']) == args.rounds == len(round_events)
            operation_values = defaultdict(list)
            public_rows = []
            for i, row in enumerate(data['rounds']):
                # Use the actual persisted response, not status-derived assumptions
                # or G20's historical extraction/backfill code.
                response = json.loads((outdir / f'round-{i}.commit.json').read_text(encoding='utf-8'))
                receipt = protocol._receipt(response)
                expected = 'COMMITTED_DRAFT' if name in ('ftir', 'nmr') else 'COMMITTED'
                assert row.get('error') is None and response['status'] == expected, row
                assert receipt['local_edit_state'] == 'PASS', receipt
                assert receipt['source_commit_state'] == expected, receipt
                assert row['restart_matches_committed'] is True, row
                assert row['further_edit']['http'] == 200, row
                assert row['external_conflict']['status'] == 'OVERLAY_CONFLICT', row
                assert row['external_conflict_bytes_preserved'] is True, row
                grouped = defaultdict(list)
                for event in round_events[i]:
                    grouped[event['operation']].append(event['seconds'])
                assert len(grouped['__init__']) == len(grouped['snapshot']) == 3, grouped
                assert len(grouped['preview']) == 3 and len(grouped['commit']) == 1, grouped
                operations = {
                    'startup_and_snapshot_s': grouped['__init__'][0] + grouped['snapshot'][0],
                    'preview_s': grouped['preview'][0],
                    'commit_s': grouped['commit'][0],
                    'restart_and_snapshot_s': grouped['__init__'][1] + grouped['snapshot'][1],
                    'continued_preview_s': grouped['preview'][1],
                    'conflict_session_and_probe_s': grouped['__init__'][2] + grouped['snapshot'][2] + grouped['preview'][2]}
                for key, value in operations.items():
                    operation_values[key].append(value)
                public_rows.append({'round': i, 'status': response['status'],
                    'local': receipt['local_edit_state'], 'whole': receipt['figure_verification_state'],
                    'operations': operations, 'total_s': row['total_s'],
                    'phase_calls': row['phase_calls'], 'exclusive_phases_s': row['exclusive_phases_s'],
                    'other_s': row['other_s'], 'restart_matches': True, 'conflict_refused': True,
                    'source_exports': {key: row['source_exports'][key] for key in
                                       ('fs_export_calls', 'fs_export_s', 'savefig_calls', 'savefig_s')}})
            samples[name] = {'summary': data['summary'],
                             'operations': {key: percentiles(values) for key, values in operation_values.items()},
                             'rounds': public_rows}
            (outdir / 'operation_events.json').write_text(json.dumps(round_events, indent=2), encoding='utf-8')
            ownership_check()
    finally:
        for name, fn in originals.items():
            setattr(StyleSession, name, fn)
        setattr(protocol, 'phases_plus', original_phases)
    result = {'rounds_per_sample': args.rounds, 'samples': samples,
              'protocol': 'G20 full workflow, same target axis.title +1pt, serial same process; no global cleanup; extra operation instrumentation',
              'limits': 'Not an optimization of verifier counts. Extra timing hooks add instrumentation overhead. No status inferred from missing evidence.'}
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({name: {'operations': data['operations'], 'total': data['summary']['total_s']}
                      for name, data in samples.items()}, indent=2))


if __name__ == '__main__':
    main()
