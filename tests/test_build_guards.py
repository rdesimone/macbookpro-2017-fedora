# SPDX-License-Identifier: GPL-2.0-only
"""Regression checks for build boundaries; never compile, install or load code."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common


class Guards(unittest.TestCase):
    def test_exact_kernel_scope(self):
        self.assertEqual(common.kernel('7.2.15-200.fc44.x86_64'), '7.2.15-200.fc44.x86_64')
        self.assertEqual(common.kernel('7.3.3-300.fc45.x86_64'), '7.3.3-300.fc45.x86_64')
        for bad in ['latest', '7.2.15', '../../etc', '7.3.1-1.fc44.x86_64', '7.4.1-1.fc45.x86_64', '7.2.15-1.fc46.x86_64']:
            with self.assertRaises(RuntimeError):
                common.kernel(bad)

    def test_root_build_is_rejected(self):
        with patch('common.os.geteuid', return_value=0), self.assertRaises(RuntimeError):
            common.unprivileged()

    def test_changed_and_unlisted_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'source').mkdir()
            f = root / 'source/driver.c'; f.write_text('reviewed')
            (root / 'source/manifest.json').write_text(json.dumps({'files': {'source/driver.c': common.sha(f)}}))
            with patch('common.ROOT', root):
                common.verify_sources()
                f.write_text('modified')
                with self.assertRaises(RuntimeError): common.verify_sources()
                f.write_text('reviewed'); (root / 'source/extra.c').write_text('unreviewed')
                with self.assertRaises(RuntimeError): common.verify_sources()

    def test_source_rpm_uses_source_flag_not_arch_suffix(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'kernel.src.rpm'; p.write_bytes(b'fixture')
            outputs = ['digests signatures OK', 'kernel|7.2.15|200.fc44|x86_64|Fedora Project', '1']
            with patch('common.run', side_effect=outputs):
                common.rpm_check(p, 'kernel', '7.2.15-200.fc44', 'src')
            with patch('common.run', side_effect=outputs[:-1] + ['0']), self.assertRaises(RuntimeError):
                common.rpm_check(p, 'kernel', '7.2.15-200.fc44', 'src')

    def test_unsigned_or_wrong_version_rpm_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'kernel.rpm'; p.write_bytes(b'fixture')
            with patch('common.run', return_value='NOKEY'), self.assertRaises(RuntimeError):
                common.rpm_check(p, 'kernel', '7.2.15-200.fc44', 'src')
            with patch('common.run', side_effect=['digests signatures OK', 'kernel|7.2.14|200.fc44|x86_64|Fedora Project', '1']), self.assertRaises(RuntimeError):
                common.rpm_check(p, 'kernel', '7.2.15-200.fc44', 'src')

    def test_private_audio_api_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); d = root / 'source/audio/codecs/cirrus'; d.mkdir(parents=True)
            for name in ['cs8409.c', 'cs8409.h']: (d / name).write_text('snapshot')
            old = {'sound/hda/codecs/cirrus/' + n: b'baseline' for n in ['cs8409.c', 'cs8409.h']}
            new = dict(old); new['sound/hda/codecs/cirrus/cs8409.h'] = b'changed structure'
            with patch('common.ROOT', root), self.assertRaisesRegex(RuntimeError, 'Private audio APIs changed'):
                common.audio_check(old, new, root)

    def test_output_locations_preserve_stock_module_tree(self):
        for name, filename in common.MODULES.items():
            path = Path(common.destination(name, filename))
            self.assertFalse(path.is_absolute())
            self.assertNotIn('kernel', path.parts)
            self.assertNotIn('..', path.parts)
        self.assertEqual(len(common.MODULES), 5)

    def test_wifi_stock_helper_is_not_shipped_and_unknown_outputs_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            for name in ['brcmfmac.ko', 'brcmfmac-wcc.ko', 'brcmfmac-bca.ko', 'brcmfmac-cyw.ko']:
                (p / name).touch()
            self.assertEqual(set(common.build_outputs('wifi', p)), {'brcmfmac.ko'})
            (p / 'unreviewed.ko').touch()
            with self.assertRaises(RuntimeError): common.build_outputs('wifi', p)

    def test_wrong_vermagic_and_missing_imports_are_rejected(self):
        with patch('common.run', side_effect=['example', '7.2.14-200.fc44.x86_64', '', '', '', 'GPL', '']), self.assertRaisesRegex(RuntimeError, 'wrong kernel'):
            common.module_record(Path('fixture.ko'), '7.2.15-200.fc44.x86_64', set())
        with patch('common.run', side_effect=['example', '7.2.15-200.fc44.x86_64 SMP', '', '', '', 'GPL', '', ' U missing_export']), self.assertRaisesRegex(RuntimeError, 'Unresolved module symbols'):
            common.module_record(Path('fixture.ko'), '7.2.15-200.fc44.x86_64', set())


if __name__ == '__main__':
    unittest.main()
