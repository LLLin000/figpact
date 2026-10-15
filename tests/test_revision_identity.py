"""Regression tests for G7-A / P1.5 revision identity."""

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

SKILL = Path(__file__).with_name('test_intents.py')


def _load_ti():
    spec = importlib.util.spec_from_file_location('ti_p15', SKILL)
    ti = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ti)
    return ti


def _scenario():
    d = Path(tempfile.mkdtemp())
    script = d / 'plot.py'
    script.write_bytes(b'x = 1\n' + b' ' * 100)
    config = d / 'cfg.yaml'
    config.write_text('a: 1\n')
    sci = d / 'input.png'
    sci.write_bytes(b'abc')
    return d, script, config, sci


def test_touch_does_not_change_fingerprint():
    d, script, config, sci = _scenario()
    from figpact.session import script_fingerprint
    v1 = script_fingerprint(script, config, required=[sci])
    script.write_bytes(script.read_bytes())
    v2 = script_fingerprint(script, config, required=[sci])
    assert v1 == v2


def test_same_size_same_mtime_content_change_is_detected():
    d, script, config, sci = _scenario()
    from figpact.session import script_fingerprint
    original = script.read_bytes()
    v1 = script_fingerprint(script, config, required=[sci])
    new = bytearray(original)
    new[0] = ord('y') if new[0] != ord('y') else ord('z')
    new = bytes(new)
    assert len(new) == len(original)
    script.write_bytes(new)
    v2 = script_fingerprint(script, config, required=[sci])
    assert v1 != v2


def test_runtime_temp_and_stage_files_are_excluded_by_path():
    d, script, config, sci = _scenario()
    from figpact.session import script_fingerprint
    (d / '.tmp_Fig.png').write_bytes(b'x')
    stage = d / 'foo-stage-bar'
    stage.mkdir()
    (stage / 'junk.txt').write_text('j')
    v_with = script_fingerprint(script, config, required=[sci])
    os.remove(d / '.tmp_Fig.png')
    shutil.rmtree(stage)
    v_without = script_fingerprint(script, config, required=[sci])
    assert v_with == v_without


def test_scientific_png_input_is_protected_not_excluded_by_suffix():
    d, script, config, sci = _scenario()
    from figpact.session import script_fingerprint
    assert sci.suffix == '.png'
    v1 = script_fingerprint(script, config, required=[sci])
    sci.write_bytes(b'changed instrument data')
    v2 = script_fingerprint(script, config, required=[sci])
    assert v1 != v2


def test_new_protected_dependency_is_detected():
    d, script, config, sci = _scenario()
    from figpact.session import script_fingerprint
    v1 = script_fingerprint(script, config, required=[sci])
    (d / 'helper.py').write_text('value = 2\n')
    v2 = script_fingerprint(script, config, required=[sci])
    assert v1 != v2


def test_end_to_end_external_modification_rejected():
    ti = _load_ti()
    d = Path(tempfile.mkdtemp())
    session, protected = ti.make_session(d)
    with session:
        req = ti.intent(session)
        # mutate a protected file in the rebuild window
        target = list(protected)[0]
        target.write_bytes(protected[target] + b'\n# external change\n')
        result = session.evaluate(req)
        assert result.get('status') == 'STALE_REVISION', result


def test_end_to_end_repeated_evaluate_no_false_stale():
    ti = _load_ti()
    for _ in range(2):
        d = Path(tempfile.mkdtemp())
        session, protected = ti.make_session(d)
        with session:
            for _ in range(3):
                req = ti.intent(session)
                result = session.evaluate(req)
                assert result.get('status') != 'STALE_REVISION', result