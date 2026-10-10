import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml
from figpact.patch import (apply_patch_text, config_revision, commit_changes,
                           undo_changes, RevisionConflict)


def catalog():
    specs = [
        ('line_width', ['line_width'], 'float', .2, 3),
        ('hama', ['shifts_mm', 'main', 'hama'], 'float', -10, 10),
        ('peak', ['peak_label_shifts_mm', 'main', 'peak.vancho.3p91'], '[dx,dy]', -10, 10),
        ('clearance', ['clearance_mm', 'main', 'hama'], 'float', 0, 100),
    ]
    return {'scopes': {'main': {'groups': [{'params': [
        {'key': key, 'path': path, '类型': kind, 'min': lo, 'max': hi}
        for key, path, kind, lo, hi in specs]}]}}}


class PatchTest(unittest.TestCase):
    def test_comments_dotted_ids_empty_flow_and_block_additions_survive(self):
        source = ('# scientific input stays locked\r\n'
                  'signal_scale: 22 # science\r\n'
                  'line_width: 0.75 # line explanation\r\n'
                  'shifts_mm: {} # scope explanation\r\n'
                  'peak_label_shifts_mm: {main: {}} # labels\r\n'
                  'clearance_mm:\r\n'
                  '  main:\r\n'
                  '    zno: 2.5 # existing pair\r\n'
                  '# next section\r\n'
                  'canvas_w_mm: 48\r\n')
        result = apply_patch_text(source, {'line_width': .9, 'shifts_mm': {'main': {'hama': .4}},
            'peak_label_shifts_mm': {'main': {'peak.vancho.3p91': [.2, -.1]}},
            'clearance_mm': {'main': {'hama': 1.5}}}, catalog())
        parsed = yaml.safe_load(result)
        self.assertEqual(parsed['line_width'], .9)
        self.assertEqual(parsed['signal_scale'], 22)
        self.assertEqual(parsed['peak_label_shifts_mm']['main'], {'peak.vancho.3p91': [.2, -.1]})
        self.assertEqual(parsed['clearance_mm']['main'], {'zno': 2.5, 'hama': 1.5})
        self.assertEqual(parsed['shifts_mm']['main']['hama'], .4)
        for line in source.splitlines():
            if line.startswith('#') or line.startswith('signal_scale:') or line.startswith('canvas_w_mm:') or 'existing pair' in line:
                self.assertIn(line+'\r\n', result)
        for comment in ('# line explanation', '# scope explanation', '# labels'):
            self.assertIn(comment+'\r\n', result)
        self.assertNotIn('\n', result.replace('\r\n', ''))

    def test_invalid_and_scientific_patches_are_refused(self):
        for changes in ({'signal_scale': 10}, {'schema_version': 1},
                        {'layout_reference': {'main': {'units_per_mm': 1}}},
                        {'line_width': True}, {'line_width': float('nan')},
                        {'line_width': 100}, {'peak_label_shifts_mm': {'main': {'peak.vancho.3p91': [1]}}}):
            with self.assertRaises(ValueError):
                apply_patch_text('line_width: .75\n', changes, catalog())

    def test_save_undo_and_stale_revision_protect_real_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);cfg = root/'plot.yaml';image = root/'plot.png';new = root/'plot.pdf'
            cfg.write_bytes(b'line_width: .75 # keep\r\n');image.write_bytes(b'original image')
            original = cfg.read_bytes();revision = config_revision(cfg)
            record = commit_changes(cfg, revision, {cfg: b'line_width: .9 # keep\r\n',
                image: b'new image', new: b'new pdf'})
            self.assertEqual(cfg.read_bytes(), b'line_width: .9 # keep\r\n')
            undo_changes(cfg, config_revision(cfg), record)
            self.assertEqual(cfg.read_bytes(), original)
            self.assertEqual(image.read_bytes(), b'original image')
            self.assertFalse(new.exists())
            cfg.write_bytes(b'line_width: 1.1 # agent edit\r\n')
            with self.assertRaises(RevisionConflict):
                commit_changes(cfg, revision, {cfg: original, image: b'wrong overwrite'})
            self.assertEqual(cfg.read_bytes(), b'line_width: 1.1 # agent edit\r\n')
            self.assertEqual(image.read_bytes(), b'original image')

    def test_failed_later_replacement_restores_config_and_earlier_images(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);cfg = root/'plot.yaml';image = root/'plot.png';locked = root/'locked.pdf'
            original = {cfg: b'original config', image: b'original image', locked: b'original pdf'}
            for path, data in original.items():path.write_bytes(data)
            replace = os.replace
            def fail_locked(source, destination):
                if Path(destination) == locked:raise PermissionError('output is open in another program')
                return replace(source, destination)
            with patch('figpact.patch.os.replace', side_effect=fail_locked):
                with self.assertRaises(PermissionError):
                    commit_changes(cfg, config_revision(cfg), {p: b'candidate' for p in original})
            for path, data in original.items():self.assertEqual(path.read_bytes(), data)
            self.assertEqual(list(root.glob('.figpact-save-*')), [])


if __name__ == '__main__':
    unittest.main()
