# SPDX-License-Identifier: GPL-2.0-only
"""Rootless build helpers. Nothing here installs packages or loads modules."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '7.2.13-200.fc44.x86_64'
BASELINE_SHA = '0ccfb082765ab8756d351eba49f9415ce5d3ddc378e8fd0d430dbe240192d241'
WIRELESS = 'drivers/net/wireless/broadcom/brcm80211/'
GROUPS = {
    'sleep': {'tb_ar_shim_mbp142': 'tb_ar_shim_mbp142.ko'},
    'audio': {'snd_hda_codec_cs8409': 'snd-hda-codec-cs8409.ko'},
    'touchbar': {'apple_ibridge': 'apple-ibridge.ko', 'apple_touchbar': 'apple-touchbar.ko'},
    'wifi': {'brcmfmac': 'brcmfmac.ko'},
}
MODULES = {name: filename for group in GROUPS.values() for name, filename in group.items()}
RUNTIME = ['kernel-core', 'kernel-modules-core', 'kernel-modules', 'kernel-modules-extra']


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def unprivileged():
    require(os.geteuid() != 0, 'Run as your ordinary user, without sudo')


def kernel(value):
    require(re.fullmatch(r'(?:7\.2\.\d+-\d+\.fc(?:44|45)|7\.3\.\d+-\d+\.fc45)\.x86_64', value),
            'Expected exact Fedora 44/45 7.2 or Fedora 45 7.3 x86_64 syntax; other families need review')
    return value


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(argv, **kwargs):
    return subprocess.check_output([str(x) for x in argv], text=True, **kwargs).strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def verify_sources():
    data = json.loads((ROOT / 'source/manifest.json').read_text())
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'source').rglob('*')
              if p.is_file() and p.name != 'manifest.json'}
    require(actual == set(data['files']), 'Source file inventory changed; review and reseal it')
    for name, digest in data['files'].items():
        require(sha(ROOT / name) == digest, 'Source changed since review: ' + name)
    return sha(ROOT / 'source/manifest.json')


def rpm_check(path, name, version, arch):
    require(path.is_file(), 'Missing package: ' + str(path))
    signature = run(['rpmkeys', '--checksig', path])
    require('digests signatures OK' in signature, 'Fedora RPM signature not verified: ' + path.name)
    fields = run(['rpm', '-qp', '--qf', '%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}|%{VENDOR}', path]).split('|')
    source_package = run(['rpm', '-qp', '--qf', '%{SOURCEPACKAGE}', path]) == '1'
    # SRPM headers describe the target architecture, not the .src.rpm suffix.
    arch_ok = source_package if arch == 'src' else not source_package and fields[3] == arch
    require(len(fields) == 5 and fields[0] == name and arch_ok and
            fields[4] == 'Fedora Project' and fields[1] + '-' + fields[2] == version,
            'RPM identity/vendor differs from the requested package: ' + path.name)
    return {'file': path.name, 'sha256': sha(path), 'identity': fields,
            'signature_verified': True}


def unpack_rpm(path, destination, patterns):
    destination.mkdir()
    with (destination / 'extraction.log').open('w') as log:
        producer = subprocess.Popen(['rpm2cpio', str(path)], stdout=subprocess.PIPE, stderr=log)
        try:
            result = subprocess.run(['cpio', '-idm', '--quiet', '--no-absolute-filenames', *patterns],
                                    stdin=producer.stdout, cwd=destination, stdout=log, stderr=log)
            producer.stdout.close()
            require(result.returncode == 0 and producer.wait() == 0, 'RPM extraction failed')
        finally:
            if producer.poll() is None:
                producer.kill()
                producer.wait()


def subset(folder, version):
    """Read selected regular files; never extract archive paths or run RPM scriptlets."""
    files, watch = {}, {}
    with tarfile.open(folder / ('linux-' + version + '.tar.xz'), 'r|xz') as archive:
        for member in archive:
            if not member.isfile() or '/' not in member.name:
                continue
            name = member.name.split('/', 1)[1]
            require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Unsafe archive path')
            keep = name.startswith(('sound/hda/', 'include/sound/', WIRELESS))
            observe = name.startswith(('drivers/pci/', 'drivers/usb/core/', 'drivers/hid/', 'kernel/power/', WIRELESS))
            if keep or observe:
                data = archive.extractfile(member).read()
                if keep:
                    files[name] = data
                if observe:
                    watch[name] = hashlib.sha256(data).hexdigest()
    patch_paths = set()
    for patch in folder.glob('*.patch'):
        for line in patch.read_text().splitlines():
            if not line.startswith('+++ b/'):
                continue
            name = line[6:].split()[0]
            patch_paths.add(name)
            require(not name.startswith(WIRELESS), 'Fedora wireless patch requires source review: ' + name)
            if name.startswith(('sound/hda/', 'include/sound/')):
                require(name == 'sound/hda/codecs/realtek/alc269.c',
                        'Fedora audio patch requires source review: ' + name)
    return files, watch, sorted(patch_paths)


def kernel_profile(version, packages):
    """Permit only the reviewed 7.3.3 signed inputs, not arbitrary 7.3 changes."""
    if not version.startswith('7.3.'):
        return None
    profile = json.loads((ROOT / 'source/kernel-compat/7.3.json').read_text())
    require(profile['schema'] == 1 and profile['baseline_kernel'] == BASELINE and
            profile['reference_kernel'] == version,
            'This 7.3 release needs a new exact source/devel compatibility review')
    for name, key in [('kernel', 'reference_source_rpm_sha256'),
                      ('kernel-devel', 'reference_devel_rpm_sha256')]:
        matches = [p for p in packages if p['identity'][0] == name and
                   p['identity'][1] + '-' + p['identity'][2] + '.x86_64' == version]
        require(len(matches) == 1 and matches[0]['sha256'] == profile[key],
                'Signed input differs from the reviewed 7.3 profile: ' + name)
    return profile


def watched_check(old, new, profile=None):
    changed = sorted(n for n in old.keys() | new.keys() if old.get(n) != new.get(n))
    if profile is None:
        require(not changed, 'Watched PCI/USB/HID/power/Wi-Fi source changed; review required: ' + ', '.join(changed[:12]))
    else:
        digest = hashlib.sha256(json.dumps(changed, separators=(',', ':')).encode()).hexdigest()
        require(len(changed) == profile['changed_watched_paths_count'] and
                digest == profile['changed_watched_paths_sha256'],
                'Watched source changes differ from the reviewed 7.3 profile')
    return changed


def prepare_wifi(work):
    """Apply every reviewed patch strictly; an upstream fix/context change must stop."""
    patches = []
    for name in ['femctrl-v3.patch', 'local-resume-extension.patch', 'cold-resume.patch']:
        path = ROOT / 'source/wifi' / name
        subprocess.run(['git', 'apply', '--check', '-p6', str(path)], cwd=work, check=True)
        subprocess.run(['git', 'apply', '-p6', str(path)], cwd=work, check=True)
        patches.append({'file': name, 'sha256': sha(path)})
    return {'patches': patches, 'patched_pcie_sha256': sha(work / 'brcmfmac/pcie.c')}


def audio_check(old, new, headers, profile=None):
    paths = ['sound/hda/' + p.relative_to(ROOT / 'source/audio').as_posix()
             for p in (ROOT / 'source/audio').rglob('*')
             if p.is_file() and p.name != 'Makefile' and
             'sound/hda/' + p.relative_to(ROOT / 'source/audio').as_posix() in old]
    require({'sound/hda/codecs/cirrus/cs8409.c', 'sound/hda/codecs/cirrus/cs8409.h'} <= set(paths),
            'Audio comparison baseline is incomplete')
    changed = [p for p in paths if old[p] != new.get(p)]
    refreshes = {}
    if profile is None:
        require(not changed, 'Private audio APIs changed; review required: ' + ', '.join(changed))
    else:
        refreshes = profile['audio_headers']
        require(set(refreshes) == {'sound/hda/common/hda_auto_parser.h', 'sound/hda/common/hda_local.h'} and
                set(changed) == set(refreshes),
                'Private audio APIs changed outside the reviewed 7.3 header profile')
        for name, hashes in refreshes.items():
            require(hashlib.sha256(old[name]).hexdigest() == hashes['baseline_sha256'] and
                    hashlib.sha256(new[name]).hexdigest() == hashes['target_sha256'],
                    'Private audio header differs from reviewed 7.3 bytes: ' + name)
    count = 0
    for name, data in new.items():
        if name.startswith('include/sound/') and (headers / name).is_file():
            require((headers / name).read_bytes() == data, 'Source/devel sound header mismatch: ' + name)
            count += 1
    require(count > 100, 'Too few public sound headers compared')
    return {'private_paths_compared': paths, 'public_headers_compared': count,
            'reviewed_private_header_refreshes': refreshes}


def destination(name, filename):
    area = ('updates/macbook-wifi' if name == 'brcmfmac' else
            'updates/macbook-audio' if name == 'snd_hda_codec_cs8409' else
            'extra/macbook-touchbar' if name.startswith('apple_') else 'extra')
    return area + '/' + filename


def build_outputs(group, build):
    found = {p.name: p for p in build.rglob('*.ko')}
    expected = set(GROUPS[group].values())
    # brcmfmac Kbuild also compiles the stock vendor helpers. Ship only our
    # override; check-dist must resolve against Fedora's packaged helpers.
    permitted_helpers = {'brcmfmac-wcc.ko', 'brcmfmac-bca.ko', 'brcmfmac-cyw.ko'} if group == 'wifi' else set()
    require(expected <= set(found) and not set(found) - expected - permitted_helpers,
            'Unexpected module outputs from ' + group)
    return {n: p for n, p in found.items() if n in expected}


def module_record(path, version, exports):
    fields = {key: run(['modinfo', '-F', key, path])
              for key in ['name', 'vermagic', 'version', 'srcversion', 'depends', 'license', 'signer']}
    require(fields['vermagic'].split()[0] == version, 'Module targets the wrong kernel')
    imports = {line.split()[-1] for line in run(['nm', '-u', path]).splitlines() if line.split()}
    missing = sorted(imports - exports - {'_GLOBAL_OFFSET_TABLE_'})
    require(not missing, 'Unresolved module symbols: ' + ', '.join(missing))
    match = re.search(r'Build ID: ([0-9a-f]+)', run(['readelf', '-n', path]))
    require(match, 'Missing ELF build ID')
    return dict(fields, file=path.name, sha256=sha(path), build_id=match.group(1),
                imports_checked=len(imports), install_relative_path=destination(fields['name'], path.name))
