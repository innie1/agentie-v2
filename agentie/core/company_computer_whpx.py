from __future__ import annotations

"""Windows WHPX compatibility adjustments for Agentie Company Computer.

Recent QEMU/WHPX builds on Windows can terminate with ``Unexpected VP exit
code 4`` when an x86 guest is launched with ``-cpu host``.  Agentie does not
need host CPU passthrough for its lightweight Debian desktop, so on WHPX we
let QEMU use its compatible default CPU model instead.  KVM/HVF behavior is
left unchanged.
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

    if accelerator == "whpx" and machine not in {"arm64", "aarch64"}:
        # QEMU's WHPX backend on current Windows builds can crash when the
        # x86 guest uses `-cpu host`.  Remove only that exact pair and retain
        # every other VM argument unchanged.
        cleaned: list[str] = []
        index = 0
        while index < len(args):
            if index + 1 < len(args) and args[index] == "-cpu" and args[index + 1] == "host":
                index += 2
                continue
            cleaned.append(args[index])
            index += 1
        return cleaned

    return args


computer._qemu_args = _whpx_safe_qemu_args
