"""G25-S external-source DEVELOPMENT stress run, never a model benchmark.

Reviewed originals only. Each source runs in a fresh bounded child, using Agg,
network/process denial and write confinement. This is NOT an OS sandbox.
Retains raw failures/timeouts; never repairs upstream code, retries, or commits.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = Path(__file__).with_name('source_adapter.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                               allow_nan=False, default=str), encoding='utf-8')


def guard(directory):
    """Defense in depth for statically reviewed code, not hostile native code."""
    def inside(value):
        if isinstance(value, int) or value is None:
            return True
        return Path(os.fsdecode(value)).resolve().is_relative_to(directory)

    def audit(event, args):
        if event.startswith(('socket.', 'subprocess.', 'os.system', 'os.exec', 'os.spawn')):
            raise PermissionError(f'G25S blocked network/process: {event}')
        if event == 'open':
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(x in mode for x in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and not inside(path):
                raise PermissionError(f'G25S blocked write outside run: {path}')
        if event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'):
            if not inside(args[0]):
                raise PermissionError(f'G25S blocked filesystem operation: {event} {args[0]}')
        if event in ('os.rename', 'os.replace'):
            if not inside(args[0]) or not inside(args[1]):
                raise PermissionError(f'G25S blocked rename: {args[:2]}')
    sys.addaudithook(audit)


def child(record, directory):
    sys.path.insert(0, str(ROOT))
    source = directory / 'original.py'
    os.environ['G25S_SOURCE'] = str(source)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    # Initialize font cache before guarding; its directory is this run's cache.
    from matplotlib import font_manager
    font_manager.findfont('DejaVu Sans')
    guard(directory)
    from tools.g25s.source_adapter import original_figures
    from figpact import style_overlay as ov
    from figpact.inspector_style import StyleSession
    from figpact.plan_context import discover_overlay
    from figpact.edit_plan import check_plan
    result: dict[str, Any] = {'id': record['id'], 'split': 'DEVELOPMENT_EXPOSED',
              'model_called': False, 'independent_signoff': False,
              'python': sys.version, 'matplotlib': matplotlib.__version__,
              'numpy': np.__version__, 'source_sha256_before': sha(source),
              'adapter_sha256': sha(ADAPTER), 'figures': []}
    save(directory / 'environment.json', result)
    try:
        figures = original_figures()
        if not figures:
            raise RuntimeError('original leaves no open figure; no source rewrite attempted')
        result['original_figure_count'] = len(figures)
        for index, fig in enumerate(figures):
            fig.canvas.draw()
            fig.savefig(directory / f'baseline-{index}.png', dpi=90)
            result['figures'].append({'scope': f'fig{index}', 'axes_count': len(fig.axes),
                'projections': [a.name for a in fig.axes],
                'artist_types': sorted({type(a).__name__ for a in fig.findobj()}),
                'probes': []})
        plt.close('all')
        save(directory / 'results.json', result)
        for f in result['figures']:
            scope = f['scope']
            dest = directory / scope
            dest.mkdir(exist_ok=True)
            overlay = dest / 'official.json'
            try:
                targets = ov.inventory(ADAPTER, None, scope)
                save(dest / 'inventory.json', targets)
                eligible = [t for t in targets if t.get('eligible') and t.get('unique')]
                f['inventory_count'] = len(targets)
                f['eligible_roles'] = sorted({t['role'] for t in eligible})
                # Exercise the real language-plan adapter, not a copied context.
                try:
                    sess = StyleSession(script=ADAPTER, config=None, scope=scope, overlay=overlay)
                    context = discover_overlay(sess)
                    save(dest / 'context.json', context)
                    plan = {'status': 'READY', 'route': 'overlay', 'scope': scope,
                            'revision': context['revision'], 'edits': [],
                            'preserve': ['science', 'view'], 'reason': 'development boundary probe'}
                    if context['controls']:
                        control = context['controls'][0]
                        plan['edits'] = [{'control_id': control['id'], 'value': control['current']}]
                        for name, patch in [('wrong-scope', {'scope': scope + '-foreign'}),
                                            ('stale-revision', {'revision': 'stale'}),
                                            ('native-no-authority', {'route': 'native'}),
                                            ('science-control', {'edits': [{'control_id': 'science.data', 'value': 2}]}),
                                            ('duplicate-control', {'edits': plan['edits'] * 2})]:
                            try:
                                check_plan({**plan, **patch}, context)
                                f['probes'].append({'name': name, 'boundary': 'check_plan', 'rejected': False})
                            except ValueError as error:
                                f['probes'].append({'name': name, 'boundary': 'check_plan', 'rejected': True, 'error': str(error)})
                except Exception as error:
                    f['context_error'] = f'{type(error).__name__}: {error}'
                    (dest / 'context-error.log').write_text(traceback.format_exc(), encoding='utf-8')
                selected = []
                for role in ('axis.title', 'axis.tick', 'curve.linewidth'):
                    matches = [t for t in eligible if t['role'] == role]
                    if matches:
                        selected.append(matches[0])
                for n, target in enumerate(selected):
                    current = target['current']
                    base = (current.get('uniform') if target['role'] == 'axis.tick'
                            else current.get(target['property']))
                    if not isinstance(base, (float, int)):
                        f['probes'].append({'name': target['role'], 'skipped': 'non-numeric current'})
                        continue
                    changed = min(float(base) + .5, 5.5 if target['property'] == 'linewidth' else 23.5)
                    if changed == base:
                        changed = float(base) - .5
                    cases = [('change', changed)]
                    if n == 0:
                        cases += [('no-op', float(base)), ('out-of-range', -1.0)]
                    for name, value in cases:
                        probe = {'name': f'{target["role"]}:{name}', 'target_id': target['id'],
                                 'base_value': base, 'requested_value': value, 'boundary': 'inspect_candidate'}
                        try:
                            receipt = ov.inspect_candidate(ADAPTER, None, scope,
                                edits=[{'target_id': target['id'], 'value': value}], overlay=overlay)
                            save(dest / f'{n}-{name}-receipt.json', receipt)
                            probe.update({key: receipt.get(key) for key in
                                ('local_edit_state', 'figure_verification_state', 'source_commit_state',
                                 'science_unchanged', 'local_problems', 'qa_delta')})
                        except Exception as error:
                            probe['error'] = f'{type(error).__name__}: {error}'
                            (dest / f'{n}-{name}-error.log').write_text(traceback.format_exc(), encoding='utf-8')
                        probe['official_overlay_absent'] = not overlay.exists()
                        f['probes'].append(probe)
                        save(directory / 'results.json', result)
            except Exception as error:
                f['inventory_error'] = f'{type(error).__name__}: {error}'
                (dest / 'inventory-error.log').write_text(traceback.format_exc(), encoding='utf-8')
            finally:
                plt.close('all')
                save(directory / 'results.json', result)
    except Exception as error:
        result['baseline_error'] = f'{type(error).__name__}: {error}'
        (directory / 'baseline-error.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        result['source_sha256_after'] = sha(source)
        result['source_unchanged'] = result['source_sha256_before'] == result['source_sha256_after']
        save(directory / 'results.json', result)
    return result


def execute(record, out, timeout):
    directory = out / record['id']
    directory.mkdir(parents=True, exist_ok=False)
    original = ROOT / record['local_path']
    if sha(original) != record['sha256']:
        raise ValueError(f'source hash mismatch: {original}')
    shutil.copyfile(original, directory / 'original.py')
    save(directory / 'source-record.json', record)
    # Preserve reviewed upstream ../../figures writes within this run only.
    work = directory / 'work' / 'code'
    work.mkdir(parents=True)
    for folder in ('ornaments', 'layout', 'showcases', 'scales-projections'):
        (directory / 'figures' / folder).mkdir(parents=True)
    env = dict(os.environ, MPLBACKEND='Agg', PYTHONDONTWRITEBYTECODE='1',
               MPLCONFIGDIR=str(directory / 'mpl-cache'), TEMP=str(directory), TMP=str(directory))
    cmd = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()),
           '--child', str(directory)]
    start = time.time()
    state: dict[str, Any]
    with (directory / 'stdout.log').open('w', encoding='utf-8') as stdout, \
         (directory / 'stderr.log').open('w', encoding='utf-8') as stderr:
        try:
            completed = subprocess.run(cmd, cwd=work, env=env, stdout=stdout,
                                       stderr=stderr, timeout=timeout)
            state = {'exit_code': completed.returncode, 'timed_out': False}
        except subprocess.TimeoutExpired:
            state = {'exit_code': None, 'timed_out': True}
    state.update(id=record['id'], elapsed_seconds=round(time.time() - start, 2),
                 original_source_unchanged=sha(original) == record['sha256'])
    save(directory / 'process.json', state)
    print(json.dumps(state), flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', type=Path)
    parser.add_argument('--manifests', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    if args.child:
        directory = args.child.resolve()
        child(json.loads((directory / 'source-record.json').read_text(encoding='utf-8')), directory)
        return
    if not args.manifests or args.output is None:
        parser.error('--manifests and --output required')
    records = []
    for path in args.manifests:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        records.extend(manifest['sources'])
    ids = [r['id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate source ids')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'run-plan.json', {'kind': 'G25-S development stress', 'model_called': False,
        'independent_signoff': False, 'sources': records, 'timeout_per_source': args.timeout,
        'runner_sha256': sha(__file__), 'adapter_sha256': sha(ADAPTER),
        'scope_identity': 'ordinal entire original Figure; not persistent semantic panel identity',
        'probe_policy': 'all original figures; first eligible target per role, plus no-op/range and real plan-adapter negatives',
        'isolation': 'fresh child per source, write-confined Python audit + network/process denial; NOT OS sandbox'})
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda record: execute(record, out, args.timeout), records))
    save(out / 'process-summary.json', results)


if __name__ == '__main__':
    main()
