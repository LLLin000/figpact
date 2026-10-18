"""G17: fresh-process CLI sequence; all saved targets survive incremental edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT/'tools/g15/B/g15b_barchart_decl.py'
ENV = dict(os.environ, PYTHONPATH=str(ROOT), MPLBACKEND='Agg', PYTHONDONTWRITEBYTECODE='1')


def call(args, dest):
    command=[sys.executable,'-B','-X','utf8','-m','figpact','overlay',*args]
    p=subprocess.run(command,cwd=ROOT,env=ENV,text=True,capture_output=True,timeout=180)
    dest.with_suffix('.stdout.json').write_text(p.stdout,encoding='utf-8')
    dest.with_suffix('.stderr.log').write_text(p.stderr,encoding='utf-8')
    return p.returncode,json.loads(p.stdout)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output-dir',type=Path,required=True)
    out=ap.parse_args().output_dir.resolve()
    out.mkdir(parents=True,exist_ok=True)
    overlay=out/'style.json'
    assert not overlay.exists(),'Use a fresh output directory'
    common=['--script',str(SCRIPT),'--scope','main']
    code,inv=call(['inventory',*common],out/'inventory')
    assert code==0,inv
    A=next(t['id'] for t in inv['targets'] if t['role']=='axis.title' and t['selector']['axis']=='y')
    B=next(t['id'] for t in inv['targets'] if t['role']=='axis.tick' and t['selector']['axis']=='x')
    before=SCRIPT.read_bytes()
    records=[]
    for name,upserts,removals,expected in [
        ('A',[(A,8)],[],{A:8}),
        ('B',[(B,8)],[],{A:8,B:8}),
        ('update_A',[(A,9)],[],{A:9,B:8}),
        ('remove_A',[],[A],{B:8}),
    ]:
        args=['apply',*common,'--overlay',str(overlay)]
        if overlay.exists():
            args+=['--expected-sha256',hashlib.sha256(overlay.read_bytes()).hexdigest()]
        if upserts:
            edits=out/(name+'.edits.json')
            edits.write_text(json.dumps([{'target_id':t,'value':v} for t,v in upserts]),encoding='utf-8')
            args+=['--edits',str(edits)]
        for target in removals:
            args+=['--remove',target]
        code,r=call(args,out/name)
        assert code==0 and r['source_commit_state']=='COMMITTED',r
        assert r['local_edit_state']==r['figure_verification_state']=='PASS',r
        saved=json.loads(overlay.read_text(encoding='utf-8'))
        assert {t['id']:t['value'] for t in saved['targets']}==expected,saved
        replay_code,replay=call(['render',str(overlay),'--output',str(out/(name+'.png'))],out/(name+'_restart'))
        assert replay_code==0 and replay['local_edit_state']==replay['figure_verification_state']=='PASS',replay
        probe='''
import sys,json
from figpact.style_overlay import load
f,_,r=load(sys.argv[1]); assert r['local_edit_state']=='PASS',r
print(json.dumps({'ylabel':f.axes[0].yaxis.label.get_fontsize(),'xticks':[t.get_fontsize() for t in f.axes[0].get_xticklabels()]}))
'''
        p=subprocess.run([sys.executable,'-B','-X','utf8','-c',probe,str(overlay)],cwd=ROOT,env=ENV,text=True,capture_output=True,timeout=180)
        assert p.returncode==0,p.stdout+p.stderr
        values=json.loads(p.stdout)
        assert values['ylabel']==expected.get(A,10),values
        assert all(v==expected.get(B,10) for v in values['xticks']),values
        records.append({'step':name,'targets':expected,'values':values,'receipt':r,'restart':replay})
    stable=overlay.read_bytes()
    code,bad=call(['apply',*common,'--overlay',str(overlay),'--expected-sha256','0'*64,'--remove',B],out/'stale')
    assert code==1 and overlay.read_bytes()==stable,bad
    assert SCRIPT.read_bytes()==before
    (out/'results.json').write_text(json.dumps({'condition':'G17 composable R2','steps':records,'stale_refused_bytes_unchanged':True,'source_unchanged':True},indent=2),encoding='utf-8')
    print(json.dumps([{'step':r['step'],'values':r['values'],'whole_QA':r['receipt']['figure_verification_state']} for r in records],indent=2))


if __name__=='__main__':
    main()
