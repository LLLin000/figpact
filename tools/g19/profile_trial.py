"""Measure existing verification without caching or omitting work.

Synchronous timings are exclusive: child phase time is subtracted from its
parent. Instrumentation wraps functions only in this trial process and restores
them after each run. No product state or verifier is replaced.
"""
import argparse
from contextlib import contextmanager
import functools
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@contextmanager
def phases():
    from figpact import final_size, style_identity, style_overlay, change_audit, qa, source_writes, inspector
    from matplotlib.figure import Figure
    hooks = [(final_size,'_import_script','import'),(final_size,'_build_figure','build'),
             (style_identity,'inventory','identity'),(style_identity,'resolve','identity'),
             (style_overlay,'_verify_pair','audit'),(change_audit,'geometry_snapshot','audit'),
             (style_overlay,'_snapshots','audit'),(qa,'blocking_problems','qa'),
             (qa,'check_glyph_floor','qa'),(style_overlay,'_min_plain_fontsize','qa'),
             (source_writes,'_write_json','save'),(style_overlay,'_write_new_exclusive','save'),
             (inspector,'capture_figure','render'),(Figure,'savefig','render')]
    totals={name:0.0 for name in ('import','build','identity','audit','qa','save','render')}
    counts={name:0 for name in totals}
    stack=[]
    originals=[]
    def wrap(fn,phase):
        @functools.wraps(fn)
        def measured(*a,**kw):
            start=time.perf_counter(); entry=[0.0]; stack.append(entry)
            counts[phase]+=1
            try:
                return fn(*a,**kw)
            finally:
                elapsed=time.perf_counter()-start; stack.pop()
                totals[phase]+=elapsed-entry[0]
                if stack: stack[-1][0]+=elapsed
        return measured
    try:
        for owner,name,phase in hooks:
            if not hasattr(owner,name): continue
            fn=getattr(owner,name); originals.append((owner,name,fn)); setattr(owner,name,wrap(fn,phase))
        yield totals, counts
    finally:
        for owner,name,fn in reversed(originals): setattr(owner,name,fn)


def percentile(values,q):
    values=sorted(values)
    k=(len(values)-1)*q; lo=math.floor(k); hi=math.ceil(k)
    return values[lo]+(values[hi]-values[lo])*(k-lo)


def main():
    import matplotlib
    matplotlib.use('Agg')
    from figpact.inspector_style import StyleSession
    ap=argparse.ArgumentParser()
    ap.add_argument('--script',type=Path,required=True)
    ap.add_argument('--config',type=Path)
    ap.add_argument('--scope',default='main')
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--rounds',type=int,default=5)
    ap.add_argument('--role',default='axis.title',choices=['axis.title','axis.tick','curve.linewidth'])
    args=ap.parse_args()
    if args.rounds<3: ap.error('at least 3 actual rounds required')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    rows=[]
    for i in range(args.rounds):
        overlay=args.output_dir/f'round-{i}.json'
        if overlay.exists(): raise ValueError('Use a fresh output directory')
        with phases() as (timing, counts):
            row: dict[str, object]
            start=time.perf_counter()
            try:
                sess=StyleSession(script=args.script,config=args.config,scope=args.scope,overlay=overlay)
                frame=sess.snapshot()
                targets=[t for t in frame['style']['targets'] if args.role in t['target_id'] or
                         (args.role=='axis.title' and t['label'] in ('xlabel','ylabel')) or
                         (args.role=='axis.tick' and 'tick' in t['label']) or
                         (args.role=='curve.linewidth' and t['property']=='linewidth')]
                if not targets: raise ValueError('No exact eligible target for requested role')
                t=targets[0]; value=(float(t['current_pt'])+1 if t['property']=='fontsize' else float(t['current_pt'])+.2)
                pstart=time.perf_counter()
                preview,code=sess.preview({'frame_revision':frame['frame_revision'],'target_id':t['target_id'],'value':value})
                preview_s=time.perf_counter()-pstart
                commit_s=None; result=preview
                if code==200:
                    p=preview['style']['pending']; cstart=time.perf_counter()
                    result,code=sess.commit({'candidate_id':p['candidate_id'],'frame_revision':p['base_frame_revision'],'expected_sha256':p['expected_sha256']})
                    commit_s=time.perf_counter()-cstart
                row={'round':i,'http':code,'status':result.get('status'),'preview_s':preview_s,'commit_s':commit_s}
                (args.output_dir/f'round-{i}.receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as e:
                row={'round':i,'status':'BLOCKED','error':f'{type(e).__name__}: {e}'}
            row['total_s']=time.perf_counter()-start
            row['exclusive_phases_s']=dict(timing)
            row['phase_calls']=dict(counts)
            row['other_s']=max(0,row['total_s']-sum(timing.values()))
            rows.append(row)
    summary={}
    for metric in ('total_s','preview_s','commit_s'):
        values=[r[metric] for r in rows if isinstance(r.get(metric),(float,int))]
        summary[metric]={'n':len(values),'p50':percentile(values,.5),'p95':percentile(values,.95)} if values else {'n':0,'p50':None,'p95':None}
    for phase in ('import','build','identity','audit','qa','save','render'):
        vals=[r['exclusive_phases_s'][phase] for r in rows]
        calls=sum(r['phase_calls'][phase] for r in rows)
        summary[phase]={'n':len(vals) if calls else 0,'calls':calls,'p50':percentile(vals,.5) if calls else None,'p95':percentile(vals,.95) if calls else None}
    result={'rounds':rows,'summary':summary,'method':'exclusive nested monotonic timings; serial same-host warm-process repeated trials; no verifier bypass; failures counted separately','script':str(args.script),'scope':args.scope}
    (args.output_dir/'timings.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
