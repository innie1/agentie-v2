from __future__ import annotations

"""Windows WHPX compatibility adjustments for Agentie Company Computer.

Current QEMU/WHPX builds on Windows can terminate with ``Unexpected VP exit
code 4`` in two relevant cases for Agentie's Linux guest:

* x86 guests launched with ``-cpu host``;
* multi-vCPU guests hitting WHPX/APIC interrupt-controller failures.

Agentie does not require host CPU passthrough, and a single hardware-accelerated
vCPU is preferable to falling back to slow TCG.  Therefore WHPX uses QEMU's
compatible default CPU model and one vCPU.  KVM/HVF behavior is left unchanged.
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

        # WHPX has an upstream APIC failure that can surface as VP exit code 4
        # with multiple vCPUs.  Keep hardware acceleration but force one vCPU
        # until upstream WHPX is reliable for this Linux guest workload.
        if index + 1 < len(args) and args[index] == "-smp":
            cleaned.extend(["-smp", "1"])
            index += 2
            continue

        cleaned.append(args[index])
        index += 1

    return cleaned


computer._qemu_args = _whpx_safe_qemu_args
