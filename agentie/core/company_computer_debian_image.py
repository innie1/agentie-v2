from __future__ import annotations

"""Choose Debian's generic image for new graphical Company Computers.

Debian documents that ``genericcloud`` uses a cloud kernel with many device
drivers disabled, while ``generic`` uses the standard kernel and is recommended
for maximum compatibility. Agentie's Company Computer is a graphical QEMU VM,
so new disks should use ``generic`` rather than ``genericcloud``.

Existing persistent QCOW2 disks are never recreated or replaced by this module.
"""

from pathlib import Path
from typing import Any

from agentie.core import company_computer as computer


def _debian_filename(profile: dict[str, Any]) -> str:
    arch = computer.DEBIAN_ARCH.get(profile["machine"])
    if not arch:
        raise computer.ComputerError(f"Unsupported host architecture: {profile['machine']}.")
    return f"debian-13-generic-{arch}.qcow2"


def _debian_url(profile: dict[str, Any]) -> str:
    return "https://cloud.debian.org/images/cloud/trixie/latest/" + _debian_filename(profile)


# Use a separate cache name so an already-downloaded genericcloud base image can
# never be silently reused when creating a future generic-kernel guest.
computer.BASE_IMAGE = computer.RUNTIME_DIR / "debian-generic-base.qcow2"
computer._debian_filename = _debian_filename
computer._debian_url = _debian_url
