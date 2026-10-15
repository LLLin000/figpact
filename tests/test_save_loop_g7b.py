"""G7-B 保存闭环三条新增回归：
1) NMR 端到端旅程（evaluate→accept→save→重新打开）
2) 取消/拒绝授权磁盘字节不变
3) 双状态回执字段存在
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)
import matplotlib.pyplot as plt
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _copy_nmr(tmp: Path) -> Path:
    src = ROOT / 'examples' / 'nmr'
    shutil.copy2(src / '08 NMR.py', tmp / '08 NMR.py')
    shutil.copy2(src / 'nmr.yaml', tmp / 'nmr.yaml')
    shutil.copy2(src / 'figure_style.py', tmp / 'figure_style.py')
    shutil.copytree(src / '核磁原始数据', tmp / '核磁原始数据')
    return tmp / '08 NMR.py'


def _normalize_config(tmp: Path) -> None:
    # 与示例内部 prepare_config 等价的落盘形态，避免 save 路径在空映射上 KeyError。
    import importlib.util
    spec = importlib.util.spec_from_file_location('nmr_mod_g7b', tmp / '08 NMR.py')
    # 执行模块会跑 CONFIG=... 与打印；包住。
    mod = importlib.util.module_from_spec(spec)
    sys.modules['nmr_mod_g7b'] = mod
    spec.loader.exec_module(mod)
    raw = yaml.safe_load((tmp / 'nmr.yaml').read_text(encoding='utf-8'))
    prepared = mod.prepare_config(raw)
    (tmp / 'nmr.yaml').write_text(
        yaml.safe_dump(prepared, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding='utf-8')


TARGET = 'fig2_nmr.main.peak.vancho.3p91'


def test_nmr_full_journey(tmp_path):
    script_dir = tmp_path / 'nmr'
    script_dir.mkdir()
    script = _copy_nmr(script_dir)
    _normalize_config(script_dir)
    config = script.with_name('nmr.yaml')

    from figpact.intents import IntentSession
    from figpact.science import compare_science

    before_script = script.read_bytes()
    before_config = config.read_bytes()

    session = IntentSession(script=script, config=config, scope='main', dpi=600)
    frame = session.snapshot()
    nodes = {n['id']: n for n in json.loads(frame['scene_json'])['nodes']}
    assert TARGET in nodes, '目标峰位 GID 不存在'

    follow = [g for g in (nodes[TARGET].get('linked_guide_gid'),) if g]
    opid = str(uuid.uuid4())
    request = {
        'operation_id': opid, **frame['session'], 'scope': 'main',
        'target_gid': TARGET, 'operation': 'translate', 'delta_mm': [0.0, 0.15],
        'tolerance_mm': 0.01,
        'preserve': {'science': True, 'follow_gids': follow, 'fixed_gids': []},
        'demonstration': {'display_only': True}}
    result = session.evaluate(request)
    print('NMR evaluate status:', result['status'])
    print('NMR measured_delta_mm:', result.get('measured_delta_mm'))
    print('NMR error_mm:', result.get('error_mm'))
    assert result['status'] == 'OK', result
    assert abs(result['error_mm']) <= 0.01

    dec = session.decide({'operation_id': opid, 'decision': 'accept', **session.snapshot()['session']})
    print('NMR decide:', dec['status'], dec.get('message'))
    assert dec['status'] == 'OK'
    sci0 = session._science

    home = script_dir / '.figpact-state'
    out = session.save_accepted_changes(authorized=True, state_home=home)
    print('NMR SAVE:', out)
    assert out['status'] == 'OK'
    assert out['source_commit_state'] == 'COMMITTED'
    assert out['figure_verification_state'] == 'PASS'

    after_script = script.read_bytes()
    after_config = config.read_bytes()
    print('NMR script sha before/after:', hashlib.sha256(before_script).hexdigest(), hashlib.sha256(after_script).hexdigest())
    print('NMR config changed:', before_config != after_config)
    assert before_script == after_script, '非授权脚本被写'
    assert before_config != after_config, '配置未落盘'
    cfg = yaml.safe_load(config.read_text(encoding='utf-8'))
    print('NMR saved value:', cfg['peak_label_shifts_mm']['main']['peak.vancho.3p91'])
    session.close()

    session2 = IntentSession(script=script, config=config, scope='main', dpi=600)
    sci1 = session2._science
    print('NMR science compare:', compare_science(sci0, sci1))
    assert not compare_science(sci0, sci1), '科学指纹改变'
    session2.close()


def test_cancel_refusal_disk_unchanged(tmp_path):
    # 拒绝授权
    d = tmp_path
    p = d / 'nmr.yaml'
    script_dir = d / 'nmr'
    script_dir.mkdir()
    script = _copy_nmr(script_dir)
    _normalize_config(script_dir)
    config = script.with_name('nmr.yaml')
    before = config.read_bytes()

    from figpact.intents import IntentSession
    session = IntentSession(script=script, config=config, scope='main', dpi=600)
    frame = session.snapshot()
    opid = str(uuid.uuid4())
    # evaluate + accept 一个真实候选，再拒绝授权保存
    nodes = {n['id']: n for n in json.loads(frame['scene_json'])['nodes']}
    follow = [g for g in (nodes[TARGET].get('linked_guide_gid'),) if g]
    request = {
        'operation_id': opid, **frame['session'], 'scope': 'main',
        'target_gid': TARGET, 'operation': 'translate', 'delta_mm': [0.0, 0.15],
        'tolerance_mm': 0.01,
        'preserve': {'science': True, 'follow_gids': follow, 'fixed_gids': []},
        'demonstration': {'display_only': True}}
    assert session.evaluate(request)['status'] == 'OK'
    assert session.decide({'operation_id': opid, 'decision': 'accept', **session.snapshot()['session']})['status'] == 'OK'

    out = session.save_accepted_changes(authorized=False)
    print('REFUSED save:', out)
    assert out['status'] == 'REFUSED'
    assert out['source_commit_state'] == 'NOT_WRITTEN'
    assert config.read_bytes() == before, '拒绝授权后磁盘被写'
    session.close()

    # cancel 路径：不保存，直接取消候选也不写盘
    session2 = IntentSession(script=script, config=config, scope='main', dpi=600)
    frame2 = session2.snapshot()
    opid2 = str(uuid.uuid4())
    nodes2 = {n['id']: n for n in json.loads(frame2['scene_json'])['nodes']}
    follow2 = [g for g in (nodes2[TARGET].get('linked_guide_gid'),) if g]
    req2 = {
        'operation_id': opid2, **frame2['session'], 'scope': 'main',
        'target_gid': TARGET, 'operation': 'translate', 'delta_mm': [0.0, 0.15],
        'tolerance_mm': 0.01,
        'preserve': {'science': True, 'follow_gids': follow2, 'fixed_gids': []},
        'demonstration': {'display_only': True}}
    assert session2.evaluate(req2)['status'] == 'OK'
    before2 = config.read_bytes()
    c = session2.decide({'operation_id': opid2, 'decision': 'cancel', **session2.snapshot()['session']})
    print('CANCEL decide:', c['status'])
    assert c['status'] == 'OK'
    assert config.read_bytes() == before2, '取消后磁盘变化'
    session2.close()


def test_dual_state_receipt(tmp_path):
    script_dir = tmp_path / 'nmr'
    script_dir.mkdir()
    script = _copy_nmr(script_dir)
    _normalize_config(script_dir)
    config = script.with_name('nmr.yaml')

    from figpact.intents import IntentSession
    session = IntentSession(script=script, config=config, scope='main', dpi=600)
    frame = session.snapshot()
    nodes = {n['id']: n for n in json.loads(frame['scene_json'])['nodes']}
    follow = [g for g in (nodes[TARGET].get('linked_guide_gid'),) if g]
    opid = str(uuid.uuid4())
    request = {
        'operation_id': opid, **frame['session'], 'scope': 'main',
        'target_gid': TARGET, 'operation': 'translate', 'delta_mm': [0.0, 0.15],
        'tolerance_mm': 0.01,
        'preserve': {'science': True, 'follow_gids': follow, 'fixed_gids': []},
        'demonstration': {'display_only': True}}
    assert session.evaluate(request)['status'] == 'OK'
    assert session.decide({'operation_id': opid, 'decision': 'accept', **session.snapshot()['session']})['status'] == 'OK'

    out = session.save_accepted_changes(authorized=True)
    print('DUAL receipt:', out.get('source_commit_state'), out.get('figure_verification_state'))
    assert 'source_commit_state' in out
    assert 'figure_verification_state' in out
    assert set((out['source_commit_state'], out['figure_verification_state'])) >= {'COMMITTED'}
    # 措辞规则：只有 COMMITTED+PASS 才是"已保存并通过验证"
    committed = out['source_commit_state'] == 'COMMITTED'
    verified = out['figure_verification_state'] == 'PASS'
    wording_claim_verified = committed and verified
    if committed and not verified:
        # 不能被表述成"源码未修改"
        assert out.get('status') != 'REFUSED', '已提交但被误报未修改'
    print('wording_claim_verified:', wording_claim_verified)
    session.close()
