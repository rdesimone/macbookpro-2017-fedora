# Fedora on a 2017 MacBook Pro

Source code, patches and manual build/install instructions for the fixes used on **one MacBookPro14,2: the 13-inch MacBook Pro (2017, four Thunderbolt 3 ports, Touch Bar)**.

**Tested environment:** Fedora 45 running `7.2.15-200.fc44.x86_64` with five matching custom modules. The `fc44` suffix is intentional: this accepted Fedora kernel was retained during the Fedora 45 userspace upgrade. The separate `7.2.15-300.fc45` build has not been tested. Detailed sleep/wake tests preceded the OS upgrade; startup checks and an owner quick functional check passed afterward. These results cover one machine and specific builds, not every Fedora 45/kernel update.

**Experimental software, provided without warranty. Compatibility with similar Macs is not guaranteed. Try it at your own risk.** Have an installed, working recovery kernel and an independent way to read these instructions before changing drivers. A successful build does not prove hardware compatibility.

Fedora supplies the complete kernel. We build five additional/replacement **modules**, not a complete custom kernel. Sources largely come from the upstream projects credited below, with model-specific adaptations. No upstream authorship is claimed. This repository was assembled with Codex assistance.

## What is included

| Area | Module | Purpose |
| --- | --- | --- |
| Sleep/wake | `tb_ar_shim_mbp142` | Saves/restores both Alpine Ridge Thunderbolt controller trees across sleep |
| Audio | `snd_hda_codec_cs8409` | Apple-specific CS8409 initialization, including working internal speakers |
| Touch Bar | `apple_ibridge` | Connects Linux to the T1 bridge, with guarded power handling |
| Touch Bar | `apple_touchbar` | Standard controls and held-Fn function keys |
| Wi-Fi | `brcmfmac` | Restores radio front-end control state during initialization/resume, addressing loss of usable 5 GHz |

The two Touch Bar modules share one source directory and build command. Startup services, the sleep helper and narrow USB power rules are separate integration files, not more kernel modules. The camera uses Fedora's existing UVC driver; no camera module is built here. Touch ID is outside this project.

```text
README.md                 all operating instructions and attribution
LICENSE                   GPL version 2 for original project code
LICENSES/                 retained upstream licence texts
source/
  sleep/                  model-specific controller workaround
  audio/                  reviewed CS8409 code and required HDA headers
  touchbar/               bridge + Touch Bar source
  wifi/                   patches for matching Fedora brcmfmac source
  integration/            startup/sleep templates and USB power rules
  manifest.json           reviewed source identities
scripts/                  fetch, build and isolated verification commands
broadcom/                 reference to externally obtained board configuration
local/                    downloaded/extracted inputs and build logs (ignored)
dist/<exact-kernel>/       five .ko files, receipts, integration files (ignored)
```

There are no packaged firmware blobs, personalized board files, prebuilt modules or historical recovery archives in Git. `source/manifest.json` describes the selected source snapshot; changes to it require source review. Git history starts with this simplified project.

## 1. Prerequisites and exact target

Use Fedora 44/45 on x86_64. The current scripts deliberately stop outside the 7.2 kernel family or when watched source/API changes need review. They are manual build tools, not an unattended updater. They never install packages, load modules, edit `/etc` or `/boot`, suspend, reboot, or approve a kernel.

On a fresh development machine, install the build utilities explicitly:

```sh
sudo dnf5 install gcc make binutils elfutils-libelf-devel openssl-devel \
    python3 git patch rpm-build cpio kmod dnf5-plugins curl ethtool
```

The installed GCC major version must match the target kernel's compiler. A mismatch stops the build. The original builds used GCC 16.2.1; a different compiler package/build directory can change binary hashes and ELF build IDs. These instructions do not claim bit-for-bit reproducibility. Unsigned out-of-tree modules require a system that permits them; if signature enforcement applies, arrange proper module signing/key enrollment rather than disabling enforcement.

Check the hardware and choose an **exact** kernel release:

```sh
cat /sys/class/dmi/id/product_name
uname -r
KERNEL=7.2.15-200.fc44.x86_64
```

`KERNEL` is a task variable. Set it deliberately for every build/install terminal session. Do not substitute whatever upstream kernel source happens to be newest.

## 2. Obtain matching Fedora kernel code

From the repository root, as your ordinary user:

```sh
python3 scripts/fetch-kernel "$KERNEL"
```

This downloads the exact signed Fedora source/development RPMs, four matching runtime module RPMs for isolated checks, and the pinned `7.2.13-200.fc44` comparison source. It verifies signatures, package identities and the baseline digest; extracts without running package scriptlets; compares private/public audio interfaces and watched PCI/USB/HID/power/Wi-Fi sources; and prepares the matching Broadcom source. Local source outputs are under `local/kernel/$KERNEL/`. It does not install the kernel.

Alternatively, provide a directory containing those exact already-downloaded packages:

```sh
python3 scripts/fetch-kernel "$KERNEL" --rpms-dir /path/to/signed-fedora-rpms
```

The required filenames are `kernel-devel-$KERNEL.rpm`, `kernel-<version-release>.src.rpm`, `kernel-7.2.13-200.fc44.src.rpm`, and `kernel-core`, `kernel-modules-core`, `kernel-modules`, `kernel-modules-extra` RPMs named with the full target release/architecture. Source RPM metadata describes its target architecture even though its filename ends in `.src.rpm`; the script verifies the source-package flag as well.

Stable mirrors may no longer retain an exact older RPM. If a package/key is missing, a signature fails or source comparison stops, investigate and obtain the exact signed input from a trusted Fedora archive/build source. Do not use `--nogpgcheck`, a different version or a bypass flag. The baseline is needed to detect changes to the audio driver's private interfaces; it is not the kernel you must boot.

## 3. Build the modules

Build everything:

```sh
python3 scripts/build-module all "$KERNEL"
```

Or build source groups individually in the same checkout:

```sh
python3 scripts/build-module sleep "$KERNEL"       # tb_ar_shim_mbp142.ko
python3 scripts/build-module audio "$KERNEL"       # snd-hda-codec-cs8409.ko
python3 scripts/build-module touchbar "$KERNEL"    # apple-ibridge.ko AND apple-touchbar.ko
python3 scripts/build-module wifi "$KERNEL"        # brcmfmac.ko
```

Choose `all` or the individual sequence; do not run both over existing builds. Sources are copied into fresh `local/build/$KERNEL/<group>/` directories. The Wi-Fi patches are applied strictly to matching Fedora source. API/patch/build/import/vermagic failures stop the command and retain the failed tree/logs for diagnosis. Existing group outputs are not overwritten automatically. Investigate a failure, then deliberately remove only that disposable checkout's failed build/dist directories or use a fresh checkout for the corrected run.

Logs remain in `local/build/`. Upstream Wi-Fi Kbuild also compiles the stock WCC/BCA/CYW vendor helpers; only our `brcmfmac.ko` override is distributed in `dist`, and the offline check resolves its dependency against Fedora's packaged helper. The audio code retains its known unused-variable/table warning exceptions; other compiler errors remain fatal. Missing optional BTF tooling can cause a BTF-skipped notice. Neither those notices nor a successful compiler run establish runtime support.

Once all five are built, `dist/$KERNEL/` contains the modules, `build.json`, `SHA256SUMS` and rendered `integration/` files. Build paths are mapped to a generic source location in compiler debug/file references. These new binaries are candidates; the earlier machine tests refer to the previously installed builds from the same reviewed sources.

## 4. Verify without changing the running system

```sh
python3 scripts/check-dist "$KERNEL"
```

This verifies source/output identities and all five vermagic values, extracts the signed Fedora runtime module packages into `local/checks/`, runs **offline** `depmod`, and uses `modprobe --show-depends` to check module selection/dependencies there. It never loads a module or changes the live module index. A passing result is recorded in `dist/$KERNEL/offline-check.json`. Any failure stops preparation; do not install a partial/failed distribution.

The source/tooling checks can also be run without a kernel build:

```sh
python3 -m unittest discover -s tests -v
```

**Implementation verification, 8 November 2026:** all five modules built from this simplified layout for `7.2.15-200.fc44.x86_64` using signed cached Fedora inputs. Their exact-kernel identities, exported-symbol checks and isolated dependency resolution passed; nine build-boundary regression tests passed, and the generated systemd unit passed syntax verification. No newly built module or generated integration file was installed or loaded. The new build procedure and generated integration have not received a new boot/hardware/sleep trial. This is separate from the earlier working-machine validation above.

## 5. Manual installation reference

**This section is for a deliberately reviewed new installation. It is not a replacement for the private machine-specific kernel updater already running on the development Mac.** This project has not installed or boot-tested its newly rendered integration on another machine. Inspect existing hooks/services, preserve their originals and resolve conflicts before using these commands. Do not install this public setup over the private updater's services/policy as a routine update.

First retain an installed known-working kernel with matching modules and record its exact normal boot-menu entry. Install a new Fedora kernel alongside it separately, using its exact signed RPM set and preserving recovery. Do not let package retention remove the fallback. Keep that known-working entry as the normal boot default during a first trial; select the candidate deliberately for one boot. Module copying below neither installs a kernel nor selects a boot entry. Do not delete stock Fedora drivers, copy modules between kernel versions or force-load a mismatched module.

After reviewing successful `build.json` and `offline-check.json`, copy modules from `dist/$KERNEL/` to these separate override locations:

| Built file | Destination beneath `/usr/lib/modules/$KERNEL/` |
| --- | --- |
| `tb_ar_shim_mbp142.ko` | `extra/tb_ar_shim_mbp142.ko` |
| `snd-hda-codec-cs8409.ko` | `updates/macbook-audio/snd-hda-codec-cs8409.ko` |
| `apple-ibridge.ko` | `extra/macbook-touchbar/apple-ibridge.ko` |
| `apple-touchbar.ko` | `extra/macbook-touchbar/apple-touchbar.ko` |
| `brcmfmac.ko` | `updates/macbook-wifi/brcmfmac.ko` |

Confirm `$KERNEL` again and back up any existing destination files before proceeding. Each command must succeed before the next:

```sh
sudo install -D -o root -g root -m 0644 "dist/$KERNEL/tb_ar_shim_mbp142.ko" \
    "/usr/lib/modules/$KERNEL/extra/tb_ar_shim_mbp142.ko"
sudo install -D -o root -g root -m 0644 "dist/$KERNEL/snd-hda-codec-cs8409.ko" \
    "/usr/lib/modules/$KERNEL/updates/macbook-audio/snd-hda-codec-cs8409.ko"
sudo install -D -o root -g root -m 0644 "dist/$KERNEL/apple-ibridge.ko" \
    "/usr/lib/modules/$KERNEL/extra/macbook-touchbar/apple-ibridge.ko"
sudo install -D -o root -g root -m 0644 "dist/$KERNEL/apple-touchbar.ko" \
    "/usr/lib/modules/$KERNEL/extra/macbook-touchbar/apple-touchbar.ko"
sudo install -D -o root -g root -m 0644 "dist/$KERNEL/brcmfmac.ko" \
    "/usr/lib/modules/$KERNEL/updates/macbook-wifi/brcmfmac.ko"
sudo restorecon -RF "/usr/lib/modules/$KERNEL/extra" "/usr/lib/modules/$KERNEL/updates"
sudo depmod -a "$KERNEL"
```

Check all five with `modinfo -k "$KERNEL" -n MODULE_NAME` and `modprobe -S "$KERNEL" --show-depends MODULE_NAME`; their paths must select these overrides. Inspect the target initramfs using `lsinitrd -k "$KERNEL"`: a competing stock audio/Touch Bar/Wi-Fi module or an embedded older board file needs deliberate resolution before reboot. The tested installation did not need an initramfs rebuild; do not blindly copy that assumption or rebuild an image containing an unreviewed driver.

### Startup and power integration

Copy the rendered exact-kernel helper files as ordinary root-owned data, invoked through isolated Python:

```sh
sudo install -d -o root -g root -m 0755 "/usr/local/lib/macbookpro-2017-fedora/$KERNEL"
sudo install -o root -g root -m 0644 "dist/$KERNEL/integration/boot.py" \
    "dist/$KERNEL/integration/touchbar-prepare.py" "dist/$KERNEL/integration/sleep-prepare.py" \
    "dist/$KERNEL/integration/manifest.json" "dist/$KERNEL/integration/sleep-policy.json" \
    "/usr/local/lib/macbookpro-2017-fedora/$KERNEL/"
sudo install -o root -g root -m 0644 "dist/$KERNEL/integration/macbookpro-2017-fedora.service" \
    /etc/systemd/system/macbookpro-2017-fedora.service
sudo install -o root -g root -m 0644 "dist/$KERNEL/integration/"*.rules /etc/udev/rules.d/
sudo restorecon -RF /usr/local/lib/macbookpro-2017-fedora /etc/systemd/system/macbookpro-2017-fedora.service /etc/udev/rules.d
sudo systemctl daemon-reload
sudo systemctl enable macbookpro-2017-fedora.service
sudo udevadm control --reload-rules
```

The rules keep the T1 device and only the two external USB controllers out of runtime autosuspend, and prevent T1 from waking the system. The service loads/verifies exact Wi-Fi/audio identities and prepares the Touch Bar with guarded ACPI handling; it never reconfigures T1 USB or forces HID rebinding. Do not start it live to replace active drivers; use the planned candidate boot. No arbitrary passwordless administrator permissions are added.

**Keep automatic suspend disabled during an unvalidated first boot.** Save its current GNOME settings, then turn automatic suspend off in Settings → Power. Do not close the lid during initial validation. After a healthy candidate boot, a deliberate manual sleep trial needs the exact generated pre-suspend helper and s2idle configuration. For the initial trial, use the following runtime-only guard (it disappears on reboot) after checking that it does not conflict with existing suspend hooks:

```sh
sudo install -d -m 0755 /run/systemd/system/systemd-suspend.service.d /run/systemd/sleep.conf.d
sudo install -m 0644 "dist/$KERNEL/integration/80-macbookpro-2017-prepare.conf" \
    /run/systemd/system/systemd-suspend.service.d/80-macbookpro-2017-prepare.conf
sudo install -m 0644 "dist/$KERNEL/integration/80-macbookpro-2017-s2idle.conf" \
    /run/systemd/sleep.conf.d/80-macbookpro-2017-s2idle.conf
sudo systemctl daemon-reload
```

The helper checks model, exact kernel, ownership, hashes and module identity, loads the sleep workaround on demand, guards the Apple SSD's D3cold state and selects s2idle. It fails before ordinary systemd sleep if a check fails. It is an exact local trial policy, not a claim that compilation validated the hardware. Direct root power/sysfs operations bypass this guard.

Test manually during normal use: internal audio, Touch Bar Fn/brightness/volume, actual Wi-Fi traffic, USB-C accessories, and one saved-work sleep/wake. Check the service result and loaded driver identities against `dist/$KERNEL/build.json`. Only after your own successful trial should you deliberately make the candidate the normal boot entry, restore automatic suspend preferences, and copy the two trial `.conf` files to the corresponding `/etc/systemd/system/systemd-suspend.service.d/` and `/etc/systemd/sleep.conf.d/` directories. Create those directories first and reload systemd. An unreviewed future kernel will fail this exact-kernel sleep guard until matching support is deliberately installed.

### Recovery and kernel updates

If the candidate misbehaves, reboot and select the retained known-working kernel from GRUB. The boot service runs only on its exact configured kernel. Keep your fallback's drivers and original policies intact; restoring only a kernel version does not undo unrelated configuration changes. Restore backed-up hook/service/rule files, remove only this project's newly added files where appropriate, restore original preferences, reload systemd/udev, and regenerate the affected kernel's module index after removing its overrides. If you deliberately altered an initramfs, include its restoration in recovery.

Do not select a new kernel without matching modules. Run the fetch/build/check procedure for its exact release and review stops. This public project has no DKMS/akmods or automatic kernel adoption. Fedora's package retention and boot-default behavior remain separate concerns; retain recovery explicitly. On the original machine, kernel updates continue through its existing private guarded updater; these public instructions do not change that installation.

## Broadcom board file: download, personalize, install

This `.txt` file is **configuration data**, not the patched Wi-Fi module. Its original redistribution licence remains unverified, so the file is not shipped here or relicensed under our GPL. [This pinned public copy](https://github.com/jsoyer/MacBookPro14-2/blob/cf41a0e65e11ef55b3bdcf4bdd460dcb2ac7db8e/firmware/brcm/brcmfmac43602-pcie.txt) matches the tested board file after replacing its MAC-address line. Matching a public copy does not establish original authorship or permission to redistribute it.

```sh
mkdir -p local/broadcom
curl --fail --location --proto '=https' --tlsv1.2 \
    'https://raw.githubusercontent.com/jsoyer/MacBookPro14-2/cf41a0e65e11ef55b3bdcf4bdd460dcb2ac7db8e/firmware/brcm/brcmfmac43602-pcie.txt' \
    -o local/broadcom/brcmfmac43602-pcie.txt
git hash-object local/broadcom/brcmfmac43602-pcie.txt
```

**Before editing**, the blob identity must be `bd7af7c6f01df3ccee1471d36cb8df15d618a6aa`. Stop if it differs. Open the local file in a text editor and replace its existing `macaddr=` value with **your own permanent Wi-Fi MAC address**, in `AA:BB:CC:DD:EE:FF` form. Do not install the downloaded address or an `XX:XX:XX:XX:XX:XX` placeholder. Do not commit the downloaded/personalized file.

If the interface already exists, find it with `nmcli device status` and query its permanent address using `ethtool -P wlp2s0` (substitute your interface). Do not use a randomized connection address. If a reliable permanent address is unavailable, obtain it from that same machine's macOS hardware information first. Leave the other calibration/regulatory values unchanged.

The exact destination is **`/usr/lib/firmware/brcm/brcmfmac43602-pcie.Apple Inc.-MacBookPro14,2.txt`**. Keep fallback networking available. Review a symlink or package-owned destination before replacing it. After verifying your edited file, back up an existing regular destination and install it; run each command successfully before the next:

```sh
brcm_target='/usr/lib/firmware/brcm/brcmfmac43602-pcie.Apple Inc.-MacBookPro14,2.txt'
sudo install -d -o root -g root -m 0700 /var/backups/macbook-brcm
brcm_backup_dir=$(sudo mktemp -d /var/backups/macbook-brcm/backup.XXXXXXXX)
if test -e "$brcm_target" || test -L "$brcm_target"; then
    sudo cp -a -- "$brcm_target" "$brcm_backup_dir/original"
fi
printf 'Retain the recovery directory: %s\n' "$brcm_backup_dir"
sudo install -D -o root -g root -m 0644 local/broadcom/brcmfmac43602-pcie.txt "$brcm_target"
sudo restorecon -F -- "$brcm_target"
```

Restart normally when ready, then verify actual Wi-Fi traffic and band/frequency. Do not unload a driver carrying your current connection. Do not replace `.bin` firmware or unrelated Broadcom files. Inspect an existing initramfs if it contains an embedded copy; copying a board file does not refresh that image. For rollback, restore the recorded original and its ownership/SELinux label, or remove only the added file if none existed, then restart when ready. Also restore any deliberately changed initramfs.

### Where the approximately 150 Mbit/s improvement happened

The board file stayed unchanged. A restart with the original driver could already reach about 156 Mbit/s, but sleep could lose usable 5 GHz. The patched `brcmfmac` restores a radio front-end (FEM) control bit before firmware initialization; our extension also restores it on the hot-resume path and reselects the PCIe register window. A controlled patched-driver startup measured 155.6 Mbit/s. These changes are in `source/wifi/*.patch`, applied to the matching Fedora `brcmfmac/pcie.c`.

Temporary board-flag and Wi-Fi power-policy experiments were restored. This is a hardware initialization/resume fix, not an access-point-specific tuning profile or a speed guarantee. An overnight connected-but-no-internet incident was later recovered by reconnecting; its cause remains unresolved. Long-term reliability and every access point/accessory combination are not established.

## Source attribution and licences

| Area | Upstream / selected revision | Changes carried here |
| --- | --- | --- |
| Sleep | [orospakr/linux-apple-alpine-ridge-suspend](https://github.com/orospakr/linux-apple-alpine-ridge-suspend/tree/155ffe3a4a963bc8d84df72fa53f14eb16ea9a60) | Separate controller contexts, exact-model/two-tree guards, explicit loading |
| Audio | [davidjo/snd_hda_macbookpro](https://github.com/davidjo/snd_hda_macbookpro/tree/89b22ff90b86468b186706861dd18663562defa7) + signed Fedora 7.2.13 source | Preserved community Apple initialization and matching HDA dependencies; patch context refreshed for Fedora layout |
| Touch Bar | [AJ-dev-i60/t1-touchbar](https://github.com/AJ-dev-i60/t1-touchbar/tree/20d65c7b0fe6d05ea9734f869b27384a62de5109), [monomyth resume revision](https://github.com/monomyth/t1-touchbar/tree/a33c7eb27777339c047b8f532d1e6baebaec46bd) | Resume fixes and narrow model/HID/interface/power guards; Ronald Tschalär and other notices retained |
| Wi-Fi | Matching Fedora/Linux `brcmfmac`; [Sergey Armodin's v3 proposal](https://lore.kernel.org/linux-wireless/20261101172011.1591620-1-dolph-in@yandex.ru/) | Local hot-resume FEM restoration, register-window restoration and read-back diagnostics for Apple subsystem `0157`; not a published upstream v4 |

Original project scripts/adaptations are licensed under **GPL-2.0-only**. Existing file notices retain their original terms, including GPL-2.0-or-later audio files and ISC Broadcom code. The licence texts are in `LICENSE`/`LICENSES/`. The Wi-Fi patches include context from ISC-licensed driver code; retain its ISC notices and the upstream attribution when applying them. Original local additions are GPL-2.0-only. The external board configuration is excluded and is not covered by this project's licence. Kernel source downloads carry their own original licences/notices; no complete Linux source archive is committed here.

Source comments containing historical draft/unvalidated labels describe the initial review stage and are preserved verbatim. The bounded later validation described at the top does not certify a newly compiled binary. This project is a documented account of a specific working setup, not a warranty of safety or compatibility.
