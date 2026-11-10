# Fedora 45 / kernel 7.3.3 update

The owner accepted a separately maintained **7.3.3-300.fc45.x86_64** installation on one MacBookPro14,2 on 10 November 2026. This public project now carries the relevant reviewed source/build changes and sanitized results. It remains a manual source/build project; it does not include the private updater, its authorizations or recovery records.

## Source compatibility changes

The original build guard correctly stopped at the kernel-family transition. The source comparison found two changed private HDA headers: `hda_auto_parser.h` removes the unused `indexp` argument from `snd_hda_get_pin_label`, and `hda_local.h` adds the unused `hda_append_suffix` inline helper. The preserved community codec calls neither function, and these two diffs do not change structure layouts. All other selected private dependencies still match; 203 public sound headers match source and devel.

[source/kernel-compat/7.3.json](../source/kernel-compat/7.3.json) pins the exact signed 7.3.3 source/devel RPM hashes, baseline/target hashes for those two headers, and the count/digest of 185 changed watched paths. Review focused on shared HID, USB core, PCI/PCIe power, suspend and brcmfmac changes; many changed paths concern unrelated hardware and are not claimed tested. The exact source hashes scope this reviewed exception. A different 7.3 release, modified input, additional private-header change or different watched-path set stops for review; no force/bypass option is provided. Existing 7.2 guards retain their original behavior.

Preparation copies only the two reviewed matching headers into an ignored staging directory, seals them with the other prepared input hashes and copies them into the fresh audio build tree. The original community audio sources/headers in Git remain unchanged. Source-signature, inventory/hash, compiler-major, vermagic, import and isolated-dependency checks remain required.

## Wi-Fi resume change

The first 7.3.3 trial completed Linux suspend but lost firmware command communication after wake. Later firmware recovery still suffered slow association and 2.4 GHz fallback; disabling power saving alone did not solve those earlier wakes. The accepted additional [cold-resume patch](../source/wifi/cold-resume.patch) is applied **after both preserved FEM patches**. It is checksum-pinned by the source manifest and restricted to BCM43602, Apple subsystem `106b:0157`, DMI `MacBookPro14,2`.

The new branch selects the PCIe register window before existing teardown, then uses the driver's cold cleanup/remove/probe path rather than trusting a retained nonzero interrupt mask. The existing firmware-download path restores FEM mode. Other models retain their prior behavior. This is a local experimental workaround, not a published upstream fix or a guarantee for similar hardware. The original Broadcom board configuration stayed unchanged and is not distributed here.

## Accepted installation observation

After a fresh reboot, the owner reported about **150 Mbit/s** Wi-Fi. After their s2idle sequence, about **100 Mbit/s**. The log interval was **19 minutes 11 seconds**, including transition work. Diagnostics showed 5220 MHz before/after, Wi-Fi power saving off, zero gateway packet loss, average gateway latency of 1.581 / 1.302 ms, a successful kernel cycle, no failed stages/selected critical faults and both controller trees restored. Firmware reinitialization and FEMCTRL restoration were observed. The owner explicitly accepted the configuration and retained the earlier 7.2.15 kernel for recovery.

The speeds are owner reports, with no recorded test endpoint/method; negotiated link rates are separate diagnostics. One successful post-reboot cycle does not establish identical speeds, precise reconnection timing, overnight or repeated-wake reliability. Earlier failed/slow wakes remain part of the result. The final cycle adds no fresh microphone, headphone, Ethernet, USB-storage, audio, Touch Bar or camera regression claim. The previously reported audio/Touch Bar/camera functionality is separate.

## Public-project verification and use

The updated public scripts independently prepared exact signed inputs, compiled **all five modules**, checked their imports/vermagic and passed the standard isolated runtime-RPM dependency check. The final Wi-Fi `pcie.c` SHA256 is `72b069fe6ae7054aacc77563d7aa4242b664893a034fd47d885feb2513854b35`, matching the accepted installation's reviewed source. The full suite has **24 passing tests**; generated helpers parse and the systemd unit passes syntax verification. See [sanitized machine observation and separate public-build evidence](../validation/kernel-7.3.3.json).

**These newly built public-project binaries and generated integration files have not been installed, booted or suspend tested.** Matching source and successful offline checks do not transfer hardware acceptance to a new binary or integration setup. No active driver, host setting, boot selection, firmware or board file was changed by this public-project update.

Follow the main README's exact fetch/build/check workflow, with `KERNEL=7.3.3-300.fc45.x86_64`, then use its deliberate manual-installation and recovery guidance only when appropriate to your machine. Preserve an installed working kernel and original hooks. This public setup must not be installed over the original machine's private guarded updater. Every later kernel still needs its own source review, matching build and owner testing; no unattended rebuild/adoption is provided. Revert this source update to undo future build changes; that does not roll back a separately installed configuration.

No personalized board files, firmware executables, prebuilt modules, private logs, network addresses, machine identifiers or private updater code were copied into this repository. Source/patch attribution and licence notices are preserved. The ISC source excerpt under `tests/fixtures/pcie.c` is only a small patch-context fixture, not a distributed or compilable driver.
