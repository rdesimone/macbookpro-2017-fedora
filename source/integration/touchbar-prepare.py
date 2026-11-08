#!/usr/bin/python3
"""Prepare the reviewed exact-kernel T1 Touch Bar at boot; never rebind USB or HID."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
KERNEL = '7.2.13-200.fc44.x86_64'
MODULES = {
    'apple-touchbar': ('e100df0adda71cb1f91ceda43ff57b57abaf23f0185f989738dd9d857b322c84',
                      '9bac481c9f6bd62e85cdc2a9b850de84cb4a5d5c'),
    'apple-ibridge': ('ef4ad538c5ead306269c1e552848b6349ef659e5d46cb8a9e5e2610770e0f988',
                     '1fdedc35fbbc906f3e1d65093a195175d775f47f'),
}


def build_id(module):
    b = (Path('/sys/module') / module / 'notes/.note.gnu.build-id').read_bytes()
    names = int.from_bytes(b[:4], 'little')
    size = int.from_bytes(b[4:8], 'little')
    offset = 12 + ((names + 3) // 4) * 4
    return b[offset:offset + size].hex()


def driver(device):
    p = device / 'driver'
    return p.resolve().name if p.exists() else None


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def log(message):
    print(message, flush=True)


def main():
    require(os.geteuid() == 0, 'Administrator privileges required')
    if os.uname().release != KERNEL:
        log('macbook-touchbar: no reviewed modules for kernel ' + os.uname().release + '; leaving stock drivers')
        return
    require(Path('/sys/class/dmi/id/product_name').read_text().strip() == 'MacBookPro14,2',
            'Unexpected hardware model')
    usbs = []
    for unused in range(50):
        usbs = [p for p in Path('/sys/bus/usb/devices').glob('*')
                if (p / 'idVendor').exists() and (p / 'idProduct').exists() and
                (p / 'idVendor').read_text().strip() == '05ac' and
                (p / 'idProduct').read_text().strip() == '8600']
        if len(usbs) == 1 and (usbs[0] / 'bConfigurationValue').read_text().strip() == '1':
            break
        time.sleep(0.2)
    require(len(usbs) == 1, 'Expected exactly one already-booted T1 iBridge')
    usb = usbs[0]
    require((usb / 'bConfigurationValue').read_text().strip() == '1',
            'T1 must already use camera-compatible configuration 1')
    ifaces = {str(n): Path('/sys/bus/usb/devices') / (usb.name + ':1.' + str(n))
              for n in range(4)}
    before = {n: driver(p) for n, p in ifaces.items()}
    hids = [p for p in Path('/sys/bus/hid/devices').glob('*05AC:8600*')
            if p.resolve().parent == ifaces['2'].resolve()]
    require(len(hids) == 1, 'Expected one keyboard/mode HID')
    hid = hids[0]
    require(driver(hid) in ('hid-generic', 'apple-ibridge-hid'), 'Keyboard HID has an unexpected driver')
    require(hashlib.sha256((hid / 'report_descriptor').read_bytes()).hexdigest() ==
            '22b74ab4b9cf60b06746281f3810a5cc655d11400fe8da8c6feef6beacd1a296',
            'Keyboard HID descriptor changed')
    other_hids = {p.name: driver(p) for p in Path('/sys/bus/hid/devices').glob('*05AC:8600*')
                  if p != hid}
    payloads = {}
    for module, (digest, unused) in MODULES.items():
        p = Path('/usr/lib/modules') / KERNEL / 'extra/macbook-touchbar' / (module + '.ko')
        info = p.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'Unsafe module ownership/permissions')
        require(hashlib.sha256(p.read_bytes()).hexdigest() == digest, 'Module checksum mismatch')
        chosen = subprocess.check_output(['/usr/bin/modinfo', '-n', module], text=True).strip()
        require(Path(chosen).resolve() == p.resolve(), 'Module lookup resolves to another file')
        vermagic = subprocess.check_output(['/usr/bin/modinfo', '-F', 'vermagic', str(p)],
                                          text=True).split()[0]
        require(vermagic == KERNEL, 'Module kernel mismatch')
        if (Path('/sys/module') / module.replace('-', '_')).exists():
            require(build_id(module.replace('-', '_')) == MODULES[module][1],
                    'An unexpected module is already loaded')
        payloads[module] = p
    original_power = (usb / 'power/control').read_text().strip()
    log('PREFLIGHT ' + json.dumps({'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'usb': usb.name, 'keyboard_hid': hid.name, 'usb_bindings': before,
        'other_hid_bindings': other_hids, 'original_usb_power_control': original_power}))
    # Only disable runtime autosuspend for this T1; system suspend remains available.
    (usb / 'power/control').write_text('on\n')
    for module, options in [
            ('apple-touchbar', ['fnmode=1', 'idle_timeout=300', 'dim_timeout=-2']),
            ('apple-ibridge', ['skip_acpi_power=1'])]:
        if not (Path('/sys/module') / module.replace('-', '_')).exists():
            log('Loading reviewed ' + module)
            subprocess.run(['/usr/bin/modprobe', module] + options, check=True, timeout=15)
    for module, (_, expected_id) in MODULES.items():
        require(build_id(module.replace('-', '_')) == expected_id, 'Loaded build ID differs')
    require(Path('/sys/module/apple_ibridge/parameters/skip_acpi_power').read_text().strip() == '1',
            'ACPI guard not set')
    for unused in range(30):
        nodes = list(hid.glob('*/fnmode'))
        if nodes:
            break
        time.sleep(0.1)
    require(driver(hid) == 'apple-ibridge-hid', 'iBridge keyboard driver did not bind')
    require(len(nodes) == 1 and nodes[0].read_text().strip() == '1',
            'Touch Bar mode control was not created')
    # UVC probe can enable parent autosuspend after our earlier write.
    # The T1 interface-bind udev rule also reapplies this policy after probes.
    (usb / 'power/control').write_text('on\n')
    require((usb / 'power/control').read_text().strip() == 'on', 'T1 runtime policy not retained')
    log('RESULT ' + json.dumps({'reviewed_touchbar_ready': True, 'system_installation': True,
        'keyboard_hid': hid.name, 'keyboard_driver': driver(hid), 'fnmode_path': str(nodes[0]),
        'fnmode': nodes[0].read_text().strip(), 'usb_power_control': (usb / 'power/control').read_text().strip(),
        'current_usb_bindings': {n: driver(p) for n, p in ifaces.items()},
        'other_hid_bindings': {name: driver(Path('/sys/bus/hid/devices') / name) for name in other_hids}}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print('macbook-touchbar preparation stopped: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
