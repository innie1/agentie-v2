from __future__ import annotations

"""Provisioning overrides for the Windows VirtualBox Company Computer backend.

This focused module keeps first-install concerns out of the lifecycle module:
- downloads Debian's compressed generic image rather than a 3 GB raw download;
- uses the full generic kernel/graphics image, not the cloud-minimal kernel;
- installs the exact VirtualBox Guest Additions shipped by the host install;
- attaches only localhost NAT forwards and the two provisioning DVDs;
- preserves/migrates the user's existing Company Computer disk.
"""

import os
import shutil
import tarfile
from pathlib import Path
from typing import Any

from agentie.core import company_computer_virtualbox as vbox

SEED_VERSION = 4
ARCHIVE_NAME = "debian-13-generic-amd64.tar.xz"
RAW_MEMBER_NAME = "debian-13-generic-amd64.raw"
ARCHIVE = vbox.DOWNLOADS_DIR / ARCHIVE_NAME
VM_CONFIG_VERSION = "2026-08-vbox-v4"
VM_CONFIG_MARKER = vbox.ROOT / "virtualbox-profile.version"


def guest_additions_iso() -> Path:
    binary = vbox.vbox_binary()
    if not binary:
        raise vbox.ComputerError("VirtualBox is not installed yet.")
    candidates = [
        Path(binary).resolve().parent / "VBoxGuestAdditions.iso",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Oracle" / "VirtualBox" / "VBoxGuestAdditions.iso",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise vbox.ComputerError(
        "VirtualBox is installed, but VBoxGuestAdditions.iso was not found. Repair the VirtualBox installation and retry Agentie Computer."
    )


def _ensure_base_raw(profile: dict[str, Any]) -> Path:
    machine = str(profile.get("machine") or "").lower()
    if machine not in {"amd64", "x86_64"}:
        raise vbox.ComputerError("The Windows VirtualBox backend currently supports x86-64 Windows hosts only.")
    if vbox.VBOX_BASE_RAW.exists():
        return vbox.VBOX_BASE_RAW
    vbox.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        vbox._download(
            "https://cloud.debian.org/images/cloud/trixie/latest/" + ARCHIVE_NAME,
            ARCHIVE,
            timeout=1200,
        )
    vbox._verify_download(ARCHIVE_NAME, ARCHIVE)
    partial = vbox.VBOX_BASE_RAW.with_suffix(".raw.part")
    partial.unlink(missing_ok=True)
    try:
        with tarfile.open(ARCHIVE, mode="r:xz") as bundle:
            members = [m for m in bundle.getmembers() if m.isfile() and Path(m.name).name.endswith(".raw")]
            preferred = next((m for m in members if Path(m.name).name == RAW_MEMBER_NAME), None)
            member = preferred or (max(members, key=lambda item: int(item.size)) if members else None)
            if member is None:
                raise vbox.ComputerError("The verified Debian archive did not contain a raw disk image.")
            source = bundle.extractfile(member)
            if source is None:
                raise vbox.ComputerError("Could not read the Debian raw disk from its verified archive.")
            with source, partial.open("wb") as output:
                shutil.copyfileobj(source, output, length=4 * 1024 * 1024)
        partial.replace(vbox.VBOX_BASE_RAW)
        return vbox.VBOX_BASE_RAW
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def ensure_disk(profile: dict[str, Any] | None = None) -> Path:
    if vbox.DISK.exists():
        _ensure_final_medium_registered(vbox.DISK)
        return vbox.DISK
    info = profile or vbox.host_profile()
    vbox.ROOT.mkdir(parents=True, exist_ok=True)
    if vbox.OLD_QCOW2.exists():
        vbox._ensure_qcow2_backup()
        return vbox._migrate_existing_qcow2()
    raw = _ensure_base_raw(info)
    try:
        vbox._run_checked(["convertfromraw", str(raw), str(vbox.DISK), "--format", "VDI"], stage="disk_create", timeout=1800)
        vbox._run_checked(["modifymedium", "disk", str(vbox.DISK), "--resize", "12288"], stage="disk_resize", timeout=180)
    finally:
        # The verified compressed archive remains cached; the expanded ~3 GB raw
        # staging file is not useful after VDI creation.
        raw.unlink(missing_ok=True)
    return vbox.DISK


def _ensure_final_medium_registered(disk: Path) -> None:
    info = vbox._run(["showmediuminfo", "disk", str(disk)], timeout=60)
    if info.returncode != 0:
        vbox._run_checked(["openmedium", "disk", str(disk)], stage="disk_register_final", timeout=60)
    vbox._run_checked(["showmediuminfo", "disk", str(disk)], stage="disk_verify_final", timeout=60)


def _cloud_init_user_data() -> str:
    _, password = vbox.guest_credentials()
    return f"""#cloud-config
hostname: agentie-computer
manage_etc_hosts: true
users:
  - name: agentie
    gecos: Agentie
    groups: [audio, video, plugdev]
    shell: /bin/bash
chpasswd:
  list: |
    agentie:{password}
  expire: false
disable_root: true
ssh_pwauth: false
package_update: true
packages:
  - xserver-xorg
  - xserver-xorg-core
  - xserver-xorg-video-all
  - openbox
  - dbus-x11
  - pcmanfm
  - xterm
  - chromium
  - x11vnc
  - xdotool
  - curl
  - ca-certificates
  - fonts-dejavu-core
  - build-essential
  - dkms
  - linux-headers-amd64
write_files:
  - path: /home/agentie/.agentie-desktop-session.sh
    owner: agentie:agentie
    permissions: '0755'
    content: |
      #!/bin/bash
      set -eu
      export DISPLAY=:0
      export HOME=/home/agentie
      export XDG_RUNTIME_DIR=/tmp/runtime-agentie
      mkdir -p "$XDG_RUNTIME_DIR"
      chmod 0700 "$XDG_RUNTIME_DIR"
      for i in $(seq 1 160); do
        DISPLAY=:0 xdotool getdisplaygeometry >/dev/null 2>&1 && break
        sleep .25
      done
      DISPLAY=:0 xdotool getdisplaygeometry >/dev/null 2>&1
      exec dbus-run-session -- sh -lc '
        pcmanfm --desktop --profile LXDE >/tmp/pcmanfm.log 2>&1 &
        chromium --user-data-dir=/home/agentie/.config/chromium-agentie --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --no-first-run --no-default-browser-check --restore-last-session about:blank >/tmp/chromium.log 2>&1 &
        exec openbox --sm-disable >/tmp/openbox.log 2>&1
      '
  - path: /etc/systemd/system/agentie-xorg.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Agentie Xorg display server
      After=systemd-user-sessions.service cloud-final.service
      [Service]
      Type=simple
      ExecStart=/usr/bin/Xorg :0 -noreset -nolisten tcp -ac vt1
      Restart=always
      RestartSec=2
      TTYPath=/dev/tty1
      StandardInput=tty-force
      TTYReset=yes
      TTYVHangup=yes
      [Install]
      WantedBy=graphical.target
  - path: /etc/systemd/system/agentie-desktop.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Agentie lightweight desktop session
      Requires=agentie-xorg.service
      After=agentie-xorg.service network-online.target
      Wants=network-online.target
      [Service]
      Type=simple
      User=agentie
      Environment=HOME=/home/agentie
      Environment=DISPLAY=:0
      Environment=XDG_RUNTIME_DIR=/tmp/runtime-agentie
      WorkingDirectory=/home/agentie
      ExecStart=/home/agentie/.agentie-desktop-session.sh
      Restart=on-failure
      RestartSec=2
      [Install]
      WantedBy=graphical.target
  - path: /etc/systemd/system/agentie-vnc.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Agentie local VNC display
      Requires=agentie-xorg.service
      After=agentie-xorg.service
      [Service]
      Type=simple
      User=agentie
      Environment=DISPLAY=:0
      ExecStart=/usr/bin/x11vnc -display :0 -forever -shared -nopw -rfbport {vbox.VNC_GUEST_PORT}
      Restart=always
      RestartSec=2
      [Install]
      WantedBy=graphical.target
runcmd:
  - [mkdir, -p, /home/agentie/Downloads]
  - [mkdir, -p, /home/agentie/Desktop]
  - [mkdir, -p, /tmp/runtime-agentie]
  - [chown, -R, "agentie:agentie", /home/agentie]
  - [chown, "agentie:agentie", /tmp/runtime-agentie]
  - [chmod, "0700", /tmp/runtime-agentie]
  - [bash, -lc, "set -eu; mkdir -p /mnt/vboxadd; mount -o ro /dev/sr1 /mnt/vboxadd; test -f /mnt/vboxadd/VBoxLinuxAdditions.run; sh /mnt/vboxadd/VBoxLinuxAdditions.run --nox11"]
  - [systemctl, daemon-reload]
  - [systemctl, enable, agentie-xorg.service]
  - [systemctl, enable, agentie-desktop.service]
  - [systemctl, enable, agentie-vnc.service]
  - [systemctl, set-default, graphical.target]
  - [systemctl, restart, agentie-xorg.service]
  - [systemctl, restart, agentie-desktop.service]
  - [systemctl, restart, agentie-vnc.service]
  - [gpasswd, -d, agentie, sudo]
final_message: "Agentie Computer guest is ready."
"""


def _set_nat_rule(name: str, host_port: int, guest_port: int) -> None:
    # Delete is best-effort because a fresh VM has no rule yet.
    vbox._run(["modifyvm", vbox.VM_NAME, "--natpf1", "delete", name], timeout=30)
    vbox._run_checked(
        ["modifyvm", vbox.VM_NAME, "--natpf1", f"{name},tcp,127.0.0.1,{host_port},,{guest_port}"],
        stage=f"nat_{name}", timeout=30,
    )


def _configure_common(profile: dict[str, Any]) -> None:
    vbox._run_checked([
        "modifyvm", vbox.VM_NAME,
        "--memory", str(profile["vm_ram_mb"]),
        "--cpus", str(profile["vm_vcpus"]),
        "--nic1", "nat",
        "--graphicscontroller", "vmsvga",
        "--vram", "64",
        "--audio-enabled", "off",
        "--clipboard-mode", "disabled",
        "--draganddrop", "disabled",
    ], stage="vm_configure")
    _set_nat_rule("cdp", vbox.CDP_PORT, vbox.CDP_PORT)
    _set_nat_rule("vnc", vbox.VNC_HOST_PORT, vbox.VNC_GUEST_PORT)


def _create_vm(profile: dict[str, Any]) -> None:
    additions = guest_additions_iso()
    machine_root = _machine_root()
    legacy_root = _default_machine_root()
    if legacy_root != machine_root:
        _preserve_stale_machine_folder(legacy_root)
    _preserve_stale_machine_folder(machine_root)
    vbox._run_checked([
        "createvm", "--name", vbox.VM_NAME, "--ostype", "Debian_64",
        "--basefolder", str(machine_root), "--register",
    ], stage="vm_create")
    _configure_common(profile)
    vbox._run_checked(["storagectl", vbox.VM_NAME, "--name", "SATA", "--add", "sata", "--controller", "IntelAhci"], stage="storage_controller")
    vbox._run_checked(["storageattach", vbox.VM_NAME, "--storagectl", "SATA", "--port", "0", "--device", "0", "--type", "hdd", "--medium", str(vbox.DISK)], stage="disk_attach")
    vbox._run_checked(["storageattach", vbox.VM_NAME, "--storagectl", "SATA", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", str(vbox.SEED_ISO)], stage="seed_attach")
    vbox._run_checked(["storageattach", vbox.VM_NAME, "--storagectl", "SATA", "--port", "2", "--device", "0", "--type", "dvddrive", "--medium", str(additions)], stage="guest_additions_attach")
    VM_CONFIG_MARKER.write_text(VM_CONFIG_VERSION + "\n", encoding="utf-8")


def _machine_root() -> Path:
    return vbox.ROOT / "virtualbox-machines"


def _default_machine_root() -> Path:
    result = vbox._run(["list", "systemproperties"], timeout=30)
    if result.returncode == 0:
        for line in (result.stdout or "").splitlines():
            if line.lower().startswith("default machine folder:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return Path(value)
    return _machine_root()


def _preserve_stale_machine_folder(machine_root: Path) -> Path | None:
    """Move an unregistered settings folder aside without deleting its files."""
    stale = machine_root / vbox.VM_NAME
    if vbox._vm_exists() or not stale.exists():
        return None
    suffix = 1
    preserved = machine_root / f"{vbox.VM_NAME}.stale-{suffix}"
    while preserved.exists():
        suffix += 1
        preserved = machine_root / f"{vbox.VM_NAME}.stale-{suffix}"
    machine_root.mkdir(parents=True, exist_ok=True)
    stale.replace(preserved)
    return preserved


def _repair_existing_vm(profile: dict[str, Any]) -> None:
    try:
        current = VM_CONFIG_MARKER.read_text(encoding="utf-8").strip()
    except Exception:
        current = ""
    if current == VM_CONFIG_VERSION:
        return
    state = vbox._vm_state()
    if state not in {"poweroff", "aborted", "missing"}:
        # A saved/running user session is never discarded merely to apply an
        # update. The current disk/session is preserved and configuration is
        # applied the next time the VM is fully stopped.
        return
    additions = guest_additions_iso()
    _configure_common(profile)
    vbox._run_checked(["storageattach", vbox.VM_NAME, "--storagectl", "SATA", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", str(vbox.SEED_ISO)], stage="seed_refresh")
    vbox._run_checked(["storageattach", vbox.VM_NAME, "--storagectl", "SATA", "--port", "2", "--device", "0", "--type", "dvddrive", "--medium", str(additions)], stage="guest_additions_refresh")
    VM_CONFIG_MARKER.write_text(VM_CONFIG_VERSION + "\n", encoding="utf-8")


def prepare() -> dict[str, Any]:
    profile = vbox.host_profile()
    if profile.get("system") != "windows":
        raise vbox.ComputerError("VirtualBox backend is selected only for Windows.")
    vbox._update(state="PREPARING", readiness_stage="virtualbox", last_error=None, needs_restart=False)
    vbox.vbox_binary() or vbox.install_virtualbox()
    guest_additions_iso()  # verify the host install is complete before creating anything
    vbox.ensure_novnc()
    vbox.ensure_seed_iso()
    vbox.ensure_disk(profile)
    vbox._start_display_server()
    if not vbox._vm_exists():
        vbox._create_vm(profile)
    else:
        _repair_existing_vm(profile)
    return {"profile": profile, "vbox": vbox.vbox_binary(), "guest_additions_iso": str(guest_additions_iso())}


def register() -> None:
    # Bump the seed filename so users who briefly ran the earlier prototype do
    # not reuse an ISO whose Guest Additions package path was not production-safe.
    vbox.SEED_VERSION = SEED_VERSION
    vbox.SEED_ISO = vbox.ROOT / f"cloud-init-vbox-v{SEED_VERSION}.iso"
    vbox._cloud_init_user_data = _cloud_init_user_data
    vbox._ensure_base_raw = _ensure_base_raw
    vbox.ensure_disk = ensure_disk
    vbox._create_vm = _create_vm
    vbox.prepare = prepare


register()
