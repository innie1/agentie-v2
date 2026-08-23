from __future__ import annotations

"""Windows WHPX compatibility adjustments for Agentie Company Computer.

Agentie's existing Debian ``genericcloud`` guest can lack the virtio-gpu DRM
module, leaving Xorg without ``/dev/dri/card0``.  Current QEMU WHPX guidance on
modern Windows also favors the simple PC machine baseline and does not require
manually forcing ``kernel-irqchip`` during normal operation.

For Agentie's lightweight Linux desktop, x86 WHPX therefore uses:
* QEMU's compatible default x86 CPU model (no ``-cpu host``);
* one vCPU;
* the broadly compatible ``pc`` machine;
* plain ``-accel whpx``;
* QEMU standard VGA instead of ``virtio-vga`` for existing persistent guests.

KVM/HVF and ARM behavior are left unchanged.
"""

import subprocess
from typing import Any

from agentie.core import company_computer as computer
from agentie.core import company_computer_debian_image as _debian_image  # registers generic image choice

_ORIGINAL_QEMU_ARGS = computer._qemu_args


def _record_effective_args(args: list[str]) -> None:
    """Write the exact effective launch line before QEMU starts."""
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
        # Host CPU passthrough has been unstable across WHPX/QEMU combinations.
        if index + 1 < len(args) and args[index] == "-cpu" and args[index + 1] == "host":
            index += 2
            continue

        # Keep startup conservative on Windows: one virtual CPU.
        if index + 1 < len(args) and args[index] == "-smp":
            cleaned.extend(["-smp", "1"])
            index += 2
            continue

        # Use the current WHPX baseline rather than the older manual irqchip
        # workaround. Modern QEMU documents plain `-accel whpx` as normal use.
        if index + 1 < len(args) and args[index] == "-accel" and args[index + 1].startswith("whpx"):
            cleaned.extend(["-accel", "whpx"])
            index += 2
            continue

        # QEMU's WHPX quick-start uses the PC machine. It is also the most
        # compatible match for the standard VGA adapter used by the old cloud
        # kernel on existing persistent Agentie disks.
        if index + 1 < len(args) and args[index] == "-machine" and args[index + 1] == "q35":
            cleaned.extend(["-machine", "pc"])
            index += 2
            continue

        # Existing genericcloud kernels may see virtio GPU PCI but never create
        # /dev/dri/card0. Standard VGA avoids requiring that DRM driver.
        if index + 1 < len(args) and args[index] == "-device" and args[index + 1] == "virtio-vga":
            cleaned.extend(["-vga", "std"])
            index += 2
            continue

        cleaned.append(args[index])
        index += 1

    _record_effective_args(cleaned)
    return cleaned


computer._qemu_args = _whpx_safe_qemu_args
