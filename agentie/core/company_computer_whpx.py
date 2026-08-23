from __future__ import annotations

"""Windows WHPX compatibility adjustments for Agentie Company Computer.

Current QEMU/WHPX builds on Windows can terminate or hang with ``Unexpected VP
exit code 4`` because of WHPX CPU/APIC handling.  For Agentie's lightweight
Linux desktop we prefer a stable hardware-accelerated configuration over host
CPU passthrough or multi-vCPU startup.

WHPX therefore uses:
* QEMU's compatible default x86 CPU model (no ``-cpu host``);
* one vCPU;
* userspace interrupt-controller emulation via ``kernel-irqchip=off``.

KVM/HVF behavior is left unchanged.
"""

from typing import Any

from agentie.core import company_computer as computer

_ORIGINAL_QEMU_ARGS = computer._qemu_args


def _whpx_safe_qemu_args(config: dict[str, Any], *, resume_snapshot: bool = False) -> list[str]:
    args = _ORIGINAL_QEMU_ARGS(config, resume_snapshot=resume_snapshot)
    profile = config.get("profile") or {}
    acceleration = config.get("acceleration") or {}
    accelerator = str(acceleration.get("accelerator") or "").lower()
    machine = str(profile.get("machine") or "").lower()

    if accelerator != "whpx" or machine in {"arm64", "aarch64"}:
        return args

    cleaned: list[str] = []
    index = 0
    while index < len(args):
        # `-cpu host` is unstable with WHPX on current Windows/QEMU builds.
        if index + 1 < len(args) and args[index] == "-cpu" and args[index + 1] == "host":
            index += 2
            continue

        # WHPX APIC failures can surface as VP exit code 4 with SMP guests.
        if index + 1 < len(args) and args[index] == "-smp":
            cleaned.extend(["-smp", "1"])
            index += 2
            continue

        # Keep WHPX acceleration but move interrupt-controller emulation out of
        # the Windows hypervisor.  This is an upstream-reported workaround for
        # WHPX VP-exit/APIC failures on Windows hosts.
        if index + 1 < len(args) and args[index] == "-accel" and args[index + 1] == "whpx":
            cleaned.extend(["-accel", "whpx,kernel-irqchip=off"])
            index += 2
            continue

        cleaned.append(args[index])
        index += 1

    return cleaned


computer._qemu_args = _whpx_safe_qemu_args
