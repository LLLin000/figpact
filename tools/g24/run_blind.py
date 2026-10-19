"""Prepare contract-only model packets, then trial untouched first responses.

No inference transport and no answer key enters packets. --responses points to a
folder of <case-id>.json replies from a stateless external model. Preparation and
trial may use fresh sessions; genuine live source/revision checks remain in force.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from figpact.agent_api import AgentSession
from figpact.edit_plan import combine_contexts, request_packet, check_plan, trial_plan
from figpact.inspector_style import StyleSession
from figpact.plan_context import discover_native, discover_overlay


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def resolve(value, roots):
    if value is None:
        return None
    for key, root in roots.items():
        value = value.replace('${' + key + '}', str(root))
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


@contextmanager
def opened(descriptor, directory, roots):
    script, config = (resolve(descriptor.get(key), roots) for key in ('script', 'config'))
    scope = descriptor['scope']
    sessions, contexts = {}, []
    directory.mkdir(parents=True, exist_ok=True)
    try:
        for route in descriptor['routes']:
            if route == 'native':
                session = AgentSession(script, config, scope)
                sessions[route] = session
                contexts.append(discover_native(session))
            else:
                session = StyleSession(script=script, config=config, scope=scope,
                                       overlay=directory / 'official-style.json')
                sessions[route] = session
                contexts.append(discover_overlay(session))
        yield sessions, combine_contexts(contexts)
    finally:
        if 'native' in sessions:
            sessions['native'].close()
        if 'overlay' in sessions:
            session = sessions['overlay']
            pending = session.snapshot().get('style', {}).get('candidate_id')
            if pending:
                session.cancel({'candidate_id': pending})


def run(args):
    from tools.g24.score import load_cases
    manifest = load_cases(args.cases)
    roots = {'NMR_ROOT': args.nmr_root, 'FTIR_ROOT': args.ftir_root}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = []
    inference = (json.loads((out / 'inference.json').read_text(encoding='utf-8'))
                 if (out / 'inference.json').exists() else {})
    stem = 'trials' if args.responses else 'prepared'
    if args.session is None:
        pieces = []
        for name in manifest['sessions']:
            command = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()),
                       '--cases', str(args.cases), '--output', str(out),
                       '--nmr-root', str(args.nmr_root), '--ftir-root', str(args.ftir_root),
                       '--session', name]
            if args.responses:
                command += ['--responses', str(args.responses)]
            subprocess.run(command, check=True, cwd=ROOT)
            pieces.append(json.loads((out / f'{stem}-{name}.json').read_text(encoding='utf-8')))
        result = {**pieces[0], 'trials': [r for p in pieces for r in p['trials']],
                  'session_isolation': 'fresh Python process per session, in preparation and trial'}
        save(out / f'{stem}.json', result)
        return result
    for name, descriptor in manifest['sessions'].items():
        if name != args.session:
            continue
        cases = [c for c in manifest['cases'] if c['session'] == name]
        if not cases:
            continue
        with opened(descriptor, out / 'sessions' / name, roots) as (sessions, context):
            protected = {resolve(descriptor['script'], roots)}
            if descriptor.get('config'):
                protected.add(resolve(descriptor['config'], roots))
            for base in context['route_contexts'].values():
                protected.update(Path(v[0]) for v in base.get('source', {}).get('dependencies', {}).values())
            def hashes():
                return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
            before = hashes()
            for case in cases:
                cid = case['id']
                packet_path = out / 'packets' / (cid + '.json')
                if args.responses is None:
                    save(packet_path, request_packet(case['request'], context))
                    print(f'{cid}: prepared', flush=True)
                    continue
                started = time.perf_counter()
                record = {'id': cid, 'attempt': 1, 'round': inference.get('round', 1),
                          'request': case['request']}
                try:
                    raw = (args.responses / (cid + '.json')).read_text(encoding='utf-8')
                    record['raw_response'] = raw
                    plan = json.loads(raw)
                    record['plan'] = plan
                    # Prepared source context must still match, not just model echo.
                    previous = json.loads(packet_path.read_text(encoding='utf-8'))['input']['context']
                    if previous['revision'] != context['revision']:
                        raise ValueError('prepared contract drifted before candidate trial')
                    by_id = {c['id']: c for c in context['controls']}
                    record['resolved_edits'] = [{**by_id[e['control_id']], 'value': e['value']}
                                                for e in plan.get('edits', [])
                                                if isinstance(e, dict) and e.get('control_id') in by_id]
                    check_plan(plan, context)
                    record['validation'] = trial_plan(sessions, context, plan)
                except Exception as error:
                    record['error'] = f'{type(error).__name__}: {error}'
                record['protected_files_before'] = before
                record['protected_files_after'] = hashes()
                record['source_unchanged'] = record['protected_files_after'] == before
                record['official_overlay_absent'] = not (out / 'sessions' / name / 'official-style.json').exists()
                if not record['source_unchanged'] or not record['official_overlay_absent']:
                    record['error'] = 'Unexpected persistent file modification'
                record['trial_seconds'] = time.perf_counter() - started
                record['saved'] = False
                record['publication_verified'] = False
                records.append(record)
                save(out / 'trials' / (cid + '.json'), record)
                print(f'{cid}: {record.get("error") or record.get("plan", {}).get("status")}', flush=True)
                # A trial is ephemeral; next instruction starts from original state.
                if 'overlay' in sessions:
                    pending = sessions['overlay'].snapshot().get('style', {}).get('candidate_id')
                    if pending:
                        sessions['overlay'].cancel({'candidate_id': pending})
                if 'native' in sessions and record.get('plan', {}).get('route') == 'native':
                    sessions['native'].close()
                    native = AgentSession(resolve(descriptor['script'], roots),
                                          resolve(descriptor['config'], roots), descriptor['scope'])
                    sessions['native'] = native
    provenance = {'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                  'planner_sha256': hashlib.sha256((ROOT / 'figpact/edit_plan.py').read_bytes()).hexdigest(),
                  'model_transport': 'external first-response files; no built-in inference or retries',
                  'inference': inference,
                  'trials': records}
    save(out / f'{stem}-{args.session}.json', provenance)
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'tools/g24/blind_cases.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--responses', type=Path)
    parser.add_argument('--nmr-root', type=Path, default=ROOT / 'examples/nmr')
    parser.add_argument('--ftir-root', type=Path, default=ROOT / 'examples/ftir')
    parser.add_argument('--session', help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.environ.setdefault('PYTHONPATH', str(ROOT))
    run(args)


if __name__ == '__main__':
    main()
