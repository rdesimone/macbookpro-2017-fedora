#!/usr/bin/python3
"""Load the reviewed, kernel-specific MacBook sleep workaround before suspend."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

POLICY = Path('/etc/macbook-sleep/verified-kernels.json')
MODULE = 'tb_ar_shim_mbp142'


def prepare():
    if os.geteuid() != 0:
        raise RuntimeError('administrator privileges are required')
    if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'MacBookPro14,2':
        raise RuntimeError('this workaround is scoped to MacBookPro14,2')
    kernel = os.uname().release
    policy = json.loads(POLICY.read_text())
    record = policy['kernels'].get(kernel)
    if record is None:
        raise RuntimeError(
            f'kernel {kernel} has no reviewed sleep module; suspend is cancelled. '
            'Build and validate a matching module before enabling sleep on this kernel.')
    module_path = Path('/usr/lib/modules') / kernel / 'extra' / (MODULE + '.ko')
    info = module_path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('module must be root-owned and not group/world writable')
    if hashlib.sha256(module_path.read_bytes()).hexdigest() != record['sha256']:
        raise RuntimeError('module checksum differs from the reviewed binary')
    vermagic = subprocess.run(
        ['/usr/bin/modinfo', '-F', 'vermagic', str(module_path)],
        capture_output=True, text=True, check=True).stdout.split()[0]
    if vermagic != kernel:
        raise RuntimeError('module kernel version mismatch')
    memory_sleep = Path('/sys/power/mem_sleep')
    if 's2idle' not in memory_sleep.read_text().split() and '[s2idle]' not in memory_sleep.read_text():
        raise RuntimeError('s2idle is unavailable')
    ssds = []
    for device in Path('/sys/bus/pci/devices').glob('*'):
        if ((device / 'vendor').read_text().strip(),
                (device / 'device').read_text().strip()) == ('0x106b', '0x2003'):
            ssds.append(device)
    if len(ssds) != 1:
        raise RuntimeError('expected exactly one Apple 106b:2003 SSD controller')
    current = Path('/sys/module') / MODULE
    if not current.exists():
        chosen = subprocess.run(
            ['/usr/bin/modinfo', '-n', MODULE], capture_output=True,
            text=True, check=True).stdout.strip()
        if Path(chosen).resolve() != module_path.resolve():
            raise RuntimeError('modprobe resolves to an unexpected module file')
        subprocess.run(['/usr/bin/modprobe', MODULE], check=True)
    if ((current / 'version').read_text().strip() != record['version'] or
            (current / 'srcversion').read_text().strip() != record['srcversion']):
        raise RuntimeError('loaded module identity differs from the reviewed build')
    # The reviewed module's init succeeds only after attaching both Apple trees.
    (ssds[0] / 'd3cold_allowed').write_text('0\n')
    memory_sleep.write_text('s2idle\n')
    if ((ssds[0] / 'd3cold_allowed').read_text().strip() != '0' or
            '[s2idle]' not in memory_sleep.read_text()):
        raise RuntimeError('runtime sleep settings did not verify')
    print(f'macbook-sleep: ready on {kernel}; both controller hooks, SSD safeguard, s2idle', flush=True)


if __name__ == '__main__':
    try:
        prepare()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'macbook-sleep: refusing suspend: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
