from __future__ import annotations

"""Windows WHPX compatibility adjustments for Agentie Company Computer.

The known-good Windows profile on Agentie's target machine can boot Debian far
enough for QGA, apt and systemd when it uses q35 + virtio-vga with a single
vCPU and userspace irqchip emulation.  The Debian ``genericcloud`` kernel may
lack the virtio-gpu DRM module, so guest setup upgrades that existing disk to
Debian's normal kernel instead of replacing the virtual GPU with legacy VGA.

For x86 WHPX we therefore use:
* no ``-cpu host`` passthrough;
* one vCPU;
* q35;
* ``whpx,kernel-irqchip=off``;
* ``virtio-vga``.

KVM/HVF and ARM behavior are left unchanged.
"""

import subprocess
from typing import Any

from agentie.core import company_computer as computer
from agentie.core import company_computer_debian_image as _debian_image  # registers generic image choice for new disks

_ORIGINAL_QEMU_ARGS = computer._qemu_args


def _record_effective_args(args: list[str]) -> None:
    try:
        computer.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with computer.LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write("\n=== Agentie QEMU launch ===\n")
            handle.write(subprocess.list2cmdline(args) + "\n")
    except Exception:
        pass


def _whpx_safe_qemu_args(config: dict[str, Any], *, resume_snapshot: bool = False) -> list[str]:
    args = _ORIGINAL_QEMU_ARGS(config, resume_snapshot=resume_snapshot)
    profile = config.get("profile") or {}
    acceleration = config.get("acceleration") or {}
    accelerator = str(acceleration.get("accelerator") or "").lower()
    machine = str(profile.get("machine") or "").lower()

    if accelerator != "whpx" or machine in {"arm64", "aarch64"}:
        _record_effective_args(args)
        return args

    cleaned: list[str] = []
    index = 0
    while index < len(args):
        if index + 1 < len(args) and args[index] == "-cpu" and args[index + 1] == "host":
            index += 2
            continue

        if index + 1 < len(args) and args[index] == "-smp":
            cleaned.extend(["-smp", "1"])
            index += 2
            continue

        if index + 1 < len(args) and args[index] == "-accel" and args[index + 1].startswith("whpx"):
            cleaned.extend(["-accel", "whpx,kernel-irqchip=off"])
            index += 2
            continue

        # Keep q35 and virtio-vga. This exact hardware reached the guest agent
        # reliably; the missing graphics support is repaired inside Debian by
        # installing the full kernel rather than by switching to legacy VGA.
        cleaned.append(args[index])
        index += 1

    _record_effective_args(cleaned)
    return cleaned


computer._qemu_args = _whpx_safe_qemu_args
