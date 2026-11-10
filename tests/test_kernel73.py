# SPDX-License-Identifier: GPL-2.0-only
"""Exact-input 7.3 profile and real Wi-Fi patch tests; no live driver changes."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import common


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = json.loads((ROOT/'source/kernel-compat/7.3.json').read_text())
        self.path = self.root/'source/kernel-compat/7.3.json'
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(self.profile))
        self.mock = patch('common.ROOT', self.root); self.mock.start(); self.addCleanup(self.mock.stop)
        self.packages = [
            {'identity': ['kernel', '7.3.3', '300.fc45', 'x86_64', 'Fedora Project'],
             'sha256': self.profile['reference_source_rpm_sha256']},
            {'identity': ['kernel-devel', '7.3.3', '300.fc45', 'x86_64', 'Fedora Project'],
             'sha256': self.profile['reference_devel_rpm_sha256']},
        ]

    def test_exact_reviewed_inputs_pass(self):
        self.assertEqual(common.kernel_profile('7.3.3-300.fc45.x86_64', self.packages), self.profile)

    def test_changed_source_or_devel_stops(self):
        for i in range(2):
            packages = copy.deepcopy(self.packages); packages[i]['sha256'] = '0'*64
            with self.subTest(package=i), self.assertRaises(RuntimeError):
                common.kernel_profile('7.3.3-300.fc45.x86_64', packages)

    def test_missing_or_duplicate_inputs_stop(self):
        for packages in [self.packages[:1], self.packages+[self.packages[0]]]:
            with self.assertRaises(RuntimeError): common.kernel_profile('7.3.3-300.fc45.x86_64', packages)

    def test_another_73_release_needs_review(self):
        with self.assertRaisesRegex(RuntimeError, 'new exact source/devel'):
            common.kernel_profile('7.3.4-300.fc45.x86_64', self.packages)

    def test_72_does_not_use_73_exception(self):
        self.assertIsNone(common.kernel_profile('7.2.15-200.fc44.x86_64', self.packages))
        with self.assertRaises(RuntimeError): common.watched_check({'driver': 'old'}, {'driver': 'new'})

    def test_watched_changes_must_match_review(self):
        self.profile['changed_watched_paths_count'] = 1
        self.profile['changed_watched_paths_sha256'] = hashlib.sha256(b'["driver"]').hexdigest()
        self.assertEqual(common.watched_check({'driver':'old'}, {'driver':'new'}, self.profile), ['driver'])
        for old, new in [({'other':'old'}, {'other':'new'}), ({}, {}), ({'driver':'old'}, {'driver':'new','extra':'new'})]:
            with self.assertRaises(RuntimeError): common.watched_check(old, new, self.profile)


class Audio73Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.headers = self.root/'headers'
        self.profile = json.loads((ROOT/'source/kernel-compat/7.3.json').read_text())
        self.old = {}; self.new = {}
        paths = list(self.profile['audio_headers'])+['sound/hda/codecs/cirrus/cs8409.c','sound/hda/codecs/cirrus/cs8409.h']
        for name in paths:
            p = self.root/'source/audio'/name.removeprefix('sound/hda/')
            p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'preserved')
            self.old[name] = b'old'; self.new[name] = b'new' if name in self.profile['audio_headers'] else b'old'
            if name in self.profile['audio_headers']:
                self.profile['audio_headers'][name] = {'baseline_sha256':hashlib.sha256(b'old').hexdigest(),
                                                       'target_sha256':hashlib.sha256(b'new').hexdigest()}
        for i in range(101):
            name = f'include/sound/test{i}.h'; self.new[name] = b'public'
            p = self.headers/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'public')
        self.mock = patch('common.ROOT', self.root); self.mock.start(); self.addCleanup(self.mock.stop)

    def test_only_two_reviewed_headers_pass_and_source_is_preserved(self):
        r = common.audio_check(self.old,self.new,self.headers,self.profile)
        self.assertEqual(set(r['reviewed_private_header_refreshes']),set(self.profile['audio_headers']))
        self.assertEqual(r['public_headers_compared'],101)
        self.assertTrue(all(p.read_bytes()==b'preserved' for p in (self.root/'source/audio').rglob('*') if p.is_file()))

    def test_any_other_private_change_stops(self):
        self.new['sound/hda/codecs/cirrus/cs8409.h'] = b'changed'
        with self.assertRaises(RuntimeError): common.audio_check(self.old,self.new,self.headers,self.profile)

    def test_different_header_bytes_stop(self):
        self.new['sound/hda/common/hda_local.h'] = b'newer API'
        with self.assertRaises(RuntimeError): common.audio_check(self.old,self.new,self.headers,self.profile)

    def test_missing_or_extra_profile_header_stops(self):
        self.profile['audio_headers'].pop('sound/hda/common/hda_local.h')
        with self.assertRaises(RuntimeError): common.audio_check(self.old,self.new,self.headers,self.profile)

    def test_public_header_mismatch_stops(self):
        (self.headers/'include/sound/test0.h').write_bytes(b'wrong')
        with self.assertRaises(RuntimeError): common.audio_check(self.old,self.new,self.headers,self.profile)


class Wifi73Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT/'source/wifi',self.root/'source/wifi')
        files = {p.relative_to(self.root).as_posix(): common.sha(p) for p in (self.root/'source/wifi').iterdir()}
        (self.root/'source/manifest.json').write_text(json.dumps({'files':files}))
        self.mock = patch('common.ROOT',self.root); self.mock.start(); self.addCleanup(self.mock.stop)

    def prepare(self, text=None, name='work'):
        work = self.root/name
        (work/'brcmfmac').mkdir(parents=True)
        (work/'brcmfmac/pcie.c').write_text(text if text is not None else (ROOT/'tests/fixtures/pcie.c').read_text())
        common.verify_sources()
        return work,common.prepare_wifi(work)

    def test_all_three_patches_and_scoped_cold_path(self):
        work,r = self.prepare()
        self.assertEqual([p['file'] for p in r['patches']],['femctrl-v3.patch','local-resume-extension.patch','cold-resume.patch'])
        self.assertEqual(r['patches'][-1]['sha256'],'507ad90bf317f6edca48b344f543b83b8c9d05f9336c7342a19d5c6afb3bdc72')
        text = (work/'brcmfmac/pcie.c').read_text()
        for guard in ['#include <linux/dmi.h>', 'devinfo->ci->chip == BRCM_CC_43602_CHIP_ID',
                      'devinfo->pdev->subsystem_vendor == PCI_VENDOR_ID_APPLE',
                      'devinfo->pdev->subsystem_device == 0x0157', 'dmi_match(DMI_PRODUCT_NAME, "MacBookPro14,2")']:
            self.assertIn(guard,text)
        cold = text.index('MacBookPro14,2: reinitializing BCM43602 after resume')
        select = text.index('brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);',cold)
        cleanup = text.index('goto cleanup;',select)
        self.assertLess(cleanup,text.index('if (brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->intmask) != 0)'))

    def test_tampered_patch_stops_source_verification(self):
        p = self.root/'source/wifi/cold-resume.patch'; p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaisesRegex(RuntimeError,'Source changed since review'): self.prepare()

    def test_changed_upstream_context_stops(self):
        text = (ROOT/'tests/fixtures/pcie.c').read_text().replace('#include <linux/pci.h>','#include <linux/pci-changed.h>')
        with self.assertRaises(subprocess.CalledProcessError): self.prepare(text)

    def test_upstream_already_patched_stops(self):
        work,r = self.prepare()
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare((work/'brcmfmac/pcie.c').read_text(),name='already')


if __name__ == '__main__':
    unittest.main()
