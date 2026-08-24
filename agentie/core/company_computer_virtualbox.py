from __future__ import annotations

"""Production-oriented VirtualBox backend for Agentie Company Computer on Windows.

Windows defaults to this backend through ``company_computer_backend``.  The
backend deliberately does not equate a running VM process with a ready desktop:
Guest Additions, Xorg, VNC/noVNC and Chromium CDP must all pass health checks.
The existing QEMU backend remains untouched for macOS/Linux and as an advanced
Windows override while the VirtualBox path is validated on real Windows hosts.
"""

import asyncio
import base64
import ctypes
import hashlib
import json
import os
import platform
import secrets
import shutil
import socket
import sqlite3
import string
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from agentie.core.company_computer import (
    ComputerError,
    DOWNLOADS_DIR,
    IDLE_SECONDS,
    ROOT,
    RUNTIME_DIR,
    _download,
    _start_display_server,
    ensure_novnc,
    host_profile,
    qemu_binary,
    qemu_img_binary,
)

VM_NAME = "agentie-company-computer"
DISK = ROOT / "company-computer.vdi"
OLD_QCOW2 = ROOT / "company-computer.qcow2"
OLD_QCOW2_BACKUP = ROOT / "company-computer.pre-virtualbox-backup.qcow2"
SEED_VERSION = 2
SEED_ISO = ROOT / f"cloud-init-vbox-v{SEED_VERSION}.iso"
STATE_DB = ROOT / "state_vbox.sqlite3"
CREDENTIALS_FILE = ROOT / "vbox-guest-credentials.bin"
VBOX_BASE_RAW = RUNTIME_DIR / "debian-vbox-base.raw"
VBOX_LOG = ROOT / "virtualbox.log"

CDP_PORT = int(os.getenv("AGENTIE_QEMU_CDP_PORT", "9222"))
VNC_HOST_PORT = int(os.getenv("AGENTIE_VBOX_VNC_HOST_PORT", "5901"))
VNC_GUEST_PORT = 5900
VNC_WEBSOCKET_PORT = int(os.getenv("AGENTIE_QEMU_VNC_WEBSOCKET_PORT", "5701"))
DISPLAY_HTTP_PORT = int(os.getenv("AGENTIE_QEMU_DISPLAY_HTTP_PORT", "6088"))
AUTO_INSTALL_VIRTUALBOX = os.getenv("AGENTIE_VBOX_AUTO_INSTALL", "1").strip().lower() not in {"0", "false", "no", "off"}

VALID_STATES = {
    "STOPPED", "INSTALLING", "PREPARING", "STARTING", "GUEST_READY",
    "DESKTOP_READY", "DISPLAY_READY", "BROWSER_READY", "READY",
    "AGENT_CONTROL", "USER_REQUIRED", "USER_CONTROL", "IDLE", "SUSPENDED", "ERROR",
}

_STATE_LOCK = threading.RLock()
_WS_THREAD: threading.Thread | None = None
_WS_LOOP: asyncio.AbstractEventLoop | None = None
_WS_STARTED = threading.Event()


def _now() -> float:
    return time.time()


def _db() -> sqlite3.Connection:
    ROOT.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(STATE_DB, timeout=10)


def _ensure_db() -> None:
    with closing(_db()) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS computer_state (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              state TEXT NOT NULL,
              controller_type TEXT,
              controller_agent_id TEXT,
              job_id TEXT,
              control_generation INTEGER NOT NULL DEFAULT 0,
              last_activity REAL NOT NULL,
              takeover_reason TEXT,
              browser_state TEXT,
              vm_pid INTEGER,
              last_error TEXT,
              suspended_snapshot INTEGER NOT NULL DEFAULT 0,
              readiness_stage TEXT,
              needs_restart INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(computer_state)").fetchall()}
        if "readiness_stage" not in columns:
            db.execute("ALTER TABLE computer_state ADD COLUMN readiness_stage TEXT")
        if "needs_restart" not in columns:
            db.execute("ALTER TABLE computer_state ADD COLUMN needs_restart INTEGER NOT NULL DEFAULT 0")
        db.execute(
            """
            INSERT OR IGNORE INTO computer_state
            (id,state,controller_type,controller_agent_id,job_id,control_generation,last_activity,
             takeover_reason,browser_state,vm_pid,last_error,suspended_snapshot,readiness_stage,needs_restart)
            VALUES (1,'STOPPED',NULL,NULL,NULL,0,?,NULL,'{}',NULL,NULL,0,NULL,0)
            """,
            (_now(),),
        )
        db.commit()


def _row() -> dict[str, Any]:
    _ensure_db()
    with closing(_db()) as db:
        db.row_factory = sqlite3.Row
        item = db.execute("SELECT * FROM computer_state WHERE id=1").fetchone()
    assert item is not None
    result = dict(item)
    try:
        result["browser_state"] = json.loads(result.get("browser_state") or "{}")
    except Exception:
        result["browser_state"] = {}
    result["needs_restart"] = bool(result.get("needs_restart"))
    return result


def _update(**fields: Any) -> dict[str, Any]:
    if not fields:
        return _row()
    allowed = {
        "state", "controller_type", "controller_agent_id", "job_id", "control_generation",
        "last_activity", "takeover_reason", "browser_state", "vm_pid", "last_error",
        "suspended_snapshot", "readiness_stage", "needs_restart",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown computer state fields: {', '.join(sorted(unknown))}")
    if "state" in fields and fields["state"] not in VALID_STATES:
        raise ValueError("Invalid Company Computer state.")
    values = dict(fields)
    if isinstance(values.get("browser_state"), dict):
        values["browser_state"] = json.dumps(values["browser_state"], separators=(",", ":"))
    if "needs_restart" in values:
        values["needs_restart"] = int(bool(values["needs_restart"]))
    assignments = ", ".join(f"{key}=?" for key in values)
    with closing(_db()) as db:
        db.execute(f"UPDATE computer_state SET {assignments} WHERE id=1", list(values.values()))
        db.commit()
    return _row()


def touch_activity(browser_state: dict[str, Any] | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {"last_activity": _now()}
    if browser_state is not None:
        fields["browser_state"] = browser_state
    return _update(**fields)


def _session_agent_id(session_id: str | None) -> str:
    text = str(session_id or "")
    if text.startswith("agent:"):
        parts = text.split(":")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return "agt_general"


def _port_open(port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _log(message: str) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with VBOX_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Local credential protection (Windows DPAPI)
# ---------------------------------------------------------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        return b"TEST-FALLBACK:" + base64.b64encode(data)
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, keepalive = _blob(data)
    output = _DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(source), "Agentie Company Computer", None, None, None, 0x1, ctypes.byref(output)):
        raise ComputerError("Windows could not protect the Company Computer guest credential.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        _ = keepalive


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        prefix = b"TEST-FALLBACK:"
        if not data.startswith(prefix):
            raise ComputerError("Company Computer test credential format is invalid.")
        return base64.b64decode(data[len(prefix):])
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, keepalive = _blob(data)
    output = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(output)):
        raise ComputerError("Windows could not unlock the Company Computer guest credential.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        _ = keepalive


def _guest_password() -> str:
    if CREDENTIALS_FILE.exists():
        return _dpapi_unprotect(CREDENTIALS_FILE.read_bytes()).decode("utf-8")
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(28))
    ROOT.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_bytes(_dpapi_protect(password.encode("utf-8")))
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass
    return password


def guest_credentials() -> tuple[str, str]:
    return "agentie", _guest_password()


# ---------------------------------------------------------------------------
# VirtualBox discovery/install
# ---------------------------------------------------------------------------

def vbox_binary() -> str | None:
    found = shutil.which("VBoxManage") or shutil.which("VBoxManage.exe")
    if found:
        return found
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
            if not root:
                continue
            candidate = Path(root) / "Oracle" / "VirtualBox" / "VBoxManage.exe"
            if candidate.exists():
                return str(candidate)
    return None


def install_virtualbox() -> str:
    found = vbox_binary()
    if found:
        return found
    if platform.system().lower() != "windows":
        raise ComputerError("VirtualBox is the Windows Company Computer backend only.")
    if not AUTO_INSTALL_VIRTUALBOX:
        raise ComputerError("VirtualBox is missing and automatic Company Computer installation is disabled.")
    winget = shutil.which("winget")
    if not winget:
        raise ComputerError("Windows Package Manager is unavailable, so Agentie cannot install VirtualBox automatically.")
    _update(state="INSTALLING", readiness_stage="virtualbox_install", last_error=None)
    proc = subprocess.run(
        [winget, "install", "--id", "Oracle.VirtualBox", "-e", "--silent",
         "--accept-package-agreements", "--accept-source-agreements"],
        capture_output=True, text=True, timeout=1200, shell=False,
    )
    found = vbox_binary()
    if found:
        return found
    detail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-2500:]
    needs_restart = any(word in detail.lower() for word in ("restart", "reboot", "3010"))
    _update(state="ERROR", readiness_stage="virtualbox_install", last_error=detail or "VirtualBox install did not expose VBoxManage.", needs_restart=needs_restart)
    if needs_restart:
        raise ComputerError("VirtualBox was installed but Windows needs a restart before Agentie Computer can continue.")
    raise ComputerError("Agentie could not install VirtualBox automatically. " + (detail or "VBoxManage was not found after installation."))


def _run(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    binary = vbox_binary()
    if not binary:
        raise ComputerError("VBoxManage was not found.")
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout, shell=False)


def _run_checked(args: list[str], *, stage: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    proc = _run(args, timeout=timeout)
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-1800:]
        _log(f"stage={stage} failed: {detail}")
        raise ComputerError(f"Agentie Computer setup failed at {stage}: {detail or 'VBoxManage returned an error.'}")
    return proc


def _vm_exists() -> bool:
    if not vbox_binary():
        return False
    proc = _run(["list", "vms"], timeout=20)
    return proc.returncode == 0 and f'"{VM_NAME}"' in (proc.stdout or "")


def _vm_state() -> str:
    if not _vm_exists():
        return "missing"
    proc = _run(["showvminfo", VM_NAME, "--machinereadable"], timeout=20)
    if proc.returncode != 0:
        return "unknown"
    for line in (proc.stdout or "").splitlines():
        if line.startswith("VMState="):
            return line.split("=", 1)[1].strip().strip('"').lower()
    return "unknown"


def _vm_running() -> bool:
    return _vm_state() == "running"


# ---------------------------------------------------------------------------
# Persistent disk and one-time QCOW2 migration
# ---------------------------------------------------------------------------

def _raw_filename(profile: dict[str, Any]) -> str:
    machine = str(profile.get("machine") or "").lower()
    if machine not in {"amd64", "x86_64"}:
        raise ComputerError("The Windows VirtualBox backend currently supports x86-64 Windows hosts only.")
    return "debian-13-genericcloud-amd64.raw"


def _verify_download(filename: str, path: Path) -> None:
    request = urllib.request.Request(
        "https://cloud.debian.org/images/cloud/trixie/latest/SHA512SUMS",
        headers={"User-Agent": "Agentie/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        sums = response.read().decode("utf-8", "replace")
    expected = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            expected = parts[0].lower()
            break
    if not expected:
        raise ComputerError(f"Could not verify Debian image {filename}.")
    digest = hashlib.sha512()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != expected:
        path.unlink(missing_ok=True)
        raise ComputerError("Downloaded VirtualBox base image failed SHA-512 verification.")


def _ensure_base_raw(profile: dict[str, Any]) -> Path:
    if VBOX_BASE_RAW.exists():
        return VBOX_BASE_RAW
    filename = _raw_filename(profile)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _download("https://cloud.debian.org/images/cloud/trixie/latest/" + filename, VBOX_BASE_RAW, timeout=900)
    _verify_download(filename, VBOX_BASE_RAW)
    return VBOX_BASE_RAW


def _qemu_img_for_migration() -> str | None:
    qemu = qemu_binary(host_profile())
    return qemu_img_binary(qemu)


def _convert_qcow2_to_vdi(source: Path, destination: Path) -> None:
    # Try VirtualBox's native reader first. Some builds accept QCOW2 and this
    # avoids requiring QEMU on migrated machines.
    proc = _run(["clonemedium", "disk", str(source), str(destination), "--format", "VDI"], timeout=900)
    if proc.returncode == 0 and destination.exists():
        return
    destination.unlink(missing_ok=True)
    qemu_img = _qemu_img_for_migration()
    if not qemu_img:
        raise ComputerError(
            "Agentie found your existing QEMU Company Computer and preserved it, but qemu-img is not available for the one-time migration to VirtualBox. Nothing was deleted."
        )
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    raw = DOWNLOADS_DIR / "company-computer-migration.raw"
    raw.unlink(missing_ok=True)
    try:
        convert = subprocess.run(
            [qemu_img, "convert", "-p", "-O", "raw", str(source), str(raw)],
            capture_output=True, text=True, timeout=1200, shell=False,
        )
        if convert.returncode != 0:
            raise ComputerError("Could not convert the existing Company Computer disk: " + ((convert.stderr or convert.stdout or "").strip()[-1500:]))
        _run_checked(["convertfromraw", str(raw), str(destination), "--format", "VDI"], stage="disk_migration", timeout=1200)
    finally:
        raw.unlink(missing_ok=True)


def ensure_disk(profile: dict[str, Any] | None = None) -> Path:
    if DISK.exists():
        return DISK
    info = profile or host_profile()
    ROOT.mkdir(parents=True, exist_ok=True)
    if OLD_QCOW2.exists():
        if not OLD_QCOW2_BACKUP.exists():
            shutil.copy2(OLD_QCOW2, OLD_QCOW2_BACKUP)
        _convert_qcow2_to_vdi(OLD_QCOW2, DISK)
        return DISK
    raw = _ensure_base_raw(info)
    _run_checked(["convertfromraw", str(raw), str(DISK), "--format", "VDI"], stage="disk_create", timeout=1200)
    _run_checked(["modifymedium", "disk", str(DISK), "--resize", "12288"], stage="disk_resize", timeout=120)
    return DISK


# ---------------------------------------------------------------------------
# Guest provisioning
# ---------------------------------------------------------------------------

def _cloud_init_user_data() -> str:
    _, password = guest_credentials()
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
  - virtualbox-guest-utils
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
      for i in $(seq 1 120); do
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
      After=systemd-user-sessions.service
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
      ExecStart=/usr/bin/x11vnc -display :0 -forever -shared -nopw -rfbport {VNC_GUEST_PORT}
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
  - [systemctl, daemon-reload]
  - [systemctl, enable, vboxservice.service]
  - [systemctl, enable, agentie-xorg.service]
  - [systemctl, enable, agentie-desktop.service]
  - [systemctl, enable, agentie-vnc.service]
  - [systemctl, set-default, graphical.target]
  - [systemctl, restart, vboxservice.service]
  - [systemctl, restart, agentie-xorg.service]
  - [systemctl, restart, agentie-desktop.service]
  - [systemctl, restart, agentie-vnc.service]
  - [gpasswd, -d, agentie, sudo]
final_message: "Agentie Computer guest is ready."
"""


def ensure_seed_iso() -> Path:
    if SEED_ISO.exists():
        return SEED_ISO
    try:
        import pycdlib
    except ImportError as exc:
        raise ComputerError("Agentie Computer requires pycdlib; reinstall Agentie dependencies.") from exc
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = ROOT / f"seed-vbox-v{SEED_VERSION}"
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    (temp / "user-data").write_text(_cloud_init_user_data(), encoding="utf-8")
    (temp / "meta-data").write_text("instance-id: agentie-company-computer-vbox\nlocal-hostname: agentie-computer\n", encoding="utf-8")
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, vol_ident="cidata")
    iso.add_file(str(temp / "user-data"), iso_path="/USER_DAT.;1", joliet_path="/user-data")
    iso.add_file(str(temp / "meta-data"), iso_path="/META_DAT.;1", joliet_path="/meta-data")
    iso.write(str(SEED_ISO))
    iso.close()
    shutil.rmtree(temp, ignore_errors=True)
    return SEED_ISO


def _create_vm(profile: dict[str, Any]) -> None:
    _run_checked(["createvm", "--name", VM_NAME, "--ostype", "Debian_64", "--register"], stage="vm_create")
    _run_checked([
        "modifyvm", VM_NAME,
        "--memory", str(profile["vm_ram_mb"]),
        "--cpus", str(profile["vm_vcpus"]),
        "--nic1", "nat",
        "--graphicscontroller", "vmsvga",
        "--vram", "64",
        "--audio-enabled", "off",
        "--clipboard-mode", "disabled",
        "--draganddrop", "disabled",
    ], stage="vm_configure")
    _run_checked(["modifyvm", VM_NAME, "--natpf1", f"cdp,tcp,127.0.0.1,{CDP_PORT},,{CDP_PORT}"], stage="nat_cdp")
    _run_checked(["modifyvm", VM_NAME, "--natpf1", f"vnc,tcp,127.0.0.1,{VNC_HOST_PORT},,{VNC_GUEST_PORT}"], stage="nat_vnc")
    _run_checked(["storagectl", VM_NAME, "--name", "SATA", "--add", "sata", "--controller", "IntelAhci"], stage="storage_controller")
    _run_checked(["storageattach", VM_NAME, "--storagectl", "SATA", "--port", "0", "--device", "0", "--type", "hdd", "--medium", str(DISK)], stage="disk_attach")
    _run_checked(["storageattach", VM_NAME, "--storagectl", "SATA", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", str(SEED_ISO)], stage="seed_attach")


def prepare() -> dict[str, Any]:
    profile = host_profile()
    if profile.get("system") != "windows":
        raise ComputerError("VirtualBox backend is selected only for Windows.")
    _update(state="PREPARING", readiness_stage="virtualbox", last_error=None, needs_restart=False)
    vbox_binary() or install_virtualbox()
    ensure_novnc()
    ensure_seed_iso()
    ensure_disk(profile)
    _start_display_server()
    if not _vm_exists():
        _create_vm(profile)
    return {"profile": profile, "vbox": vbox_binary()}


# ---------------------------------------------------------------------------
# Guest control + health/readiness
# ---------------------------------------------------------------------------

def guest_exec(command: list[str], timeout: int = 30) -> dict[str, Any]:
    if not command:
        raise ComputerError("Guest command cannot be empty.")
    username, password = guest_credentials()
    password_file = None
    try:
        handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(ROOT), prefix=".vbox-pass-")
        password_file = Path(handle.name)
        handle.write(password)
        handle.close()
        try:
            os.chmod(password_file, 0o600)
        except OSError:
            pass
        proc = _run([
            "guestcontrol", VM_NAME, "run",
            "--username", username,
            "--passwordfile", str(password_file),
            "--timeout", str(max(1000, int(timeout * 1000))),
            "--wait-stdout", "--wait-stderr", "--wait-exit",
            "--exe", command[0],
            "--", *command,
        ], timeout=max(10, int(timeout) + 5))
        return {
            "exitcode": int(proc.returncode),
            "out-data": base64.b64encode((proc.stdout or "").encode()).decode(),
            "err-data": base64.b64encode((proc.stderr or "").encode()).decode(),
        }
    except subprocess.TimeoutExpired as exc:
        raise ComputerError("VirtualBox guest command timed out.") from exc
    finally:
        if password_file is not None:
            password_file.unlink(missing_ok=True)


def _guest_ok(command: list[str], timeout: int = 10) -> bool:
    try:
        return int(guest_exec(command, timeout=timeout).get("exitcode") or 0) == 0
    except Exception:
        return False


def _cdp_ready() -> bool:
    if not _port_open(CDP_PORT):
        return False
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{CDP_PORT}/json/version", headers={"User-Agent": "Agentie/1.0"})
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        return bool(payload.get("Browser") or payload.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _wait(stage: str, predicate: Callable[[], bool], timeout: int, message: str) -> None:
    _update(state=stage if stage in VALID_STATES else "STARTING", readiness_stage=stage.lower(), last_error=None)
    deadline = time.time() + max(1, int(timeout))
    while time.time() < deadline:
        if not _vm_running():
            raise ComputerError(f"Agentie Computer stopped while waiting for {stage.lower()}.")
        if predicate():
            return
        time.sleep(1)
    raise ComputerError(message)


def _start_vnc_websocket_bridge() -> None:
    global _WS_THREAD, _WS_LOOP
    if _port_open(VNC_WEBSOCKET_PORT):
        return
    if _WS_THREAD is not None and _WS_THREAD.is_alive():
        _WS_STARTED.wait(3)
        return
    _WS_STARTED.clear()

    def worker() -> None:
        global _WS_LOOP
        loop = asyncio.new_event_loop()
        _WS_LOOP = loop
        asyncio.set_event_loop(loop)

        async def main() -> None:
            try:
                import websockets
            except ImportError as exc:
                raise ComputerError("Agentie Computer requires the websockets package for its local noVNC bridge.") from exc

            async def handler(websocket: Any) -> None:
                reader, writer = await asyncio.open_connection("127.0.0.1", VNC_HOST_PORT)

                async def ws_to_tcp() -> None:
                    try:
                        async for message in websocket:
                            data = message.encode("latin1") if isinstance(message, str) else bytes(message)
                            writer.write(data)
                            await writer.drain()
                    finally:
                        writer.close()
                        try:
                            await writer.wait_closed()
                        except Exception:
                            pass

                async def tcp_to_ws() -> None:
                    try:
                        while True:
                            data = await reader.read(65536)
                            if not data:
                                break
                            await websocket.send(data)
                    finally:
                        try:
                            await websocket.close()
                        except Exception:
                            pass

                await asyncio.gather(ws_to_tcp(), tcp_to_ws(), return_exceptions=True)

            async with websockets.serve(handler, "127.0.0.1", VNC_WEBSOCKET_PORT, max_size=None, compression=None):
                _WS_STARTED.set()
                await asyncio.Future()

        try:
            loop.run_until_complete(main())
        except Exception as exc:
            _log(f"VNC WebSocket bridge failed: {exc}")
            _WS_STARTED.set()
        finally:
            loop.close()

    _WS_THREAD = threading.Thread(target=worker, name="agentie-vbox-vnc-websocket", daemon=True)
    _WS_THREAD.start()
    _WS_STARTED.wait(5)
    if not _port_open(VNC_WEBSOCKET_PORT):
        raise ComputerError("Agentie Computer could not start its local noVNC WebSocket bridge.")


def _wait_until_ready() -> None:
    _wait("GUEST_READY", lambda: _guest_ok(["/bin/true"]), 300,
          "Agentie Computer started, but VirtualBox Guest Additions did not become ready.")
    _wait("DESKTOP_READY", lambda: _guest_ok([
        "/bin/bash", "-lc",
        "systemctl is-active --quiet agentie-xorg.service && systemctl is-active --quiet agentie-desktop.service && DISPLAY=:0 xdotool getdisplaygeometry >/dev/null 2>&1",
    ]), 360, "Agentie Computer started, but its Linux desktop did not become ready.")
    _wait("DISPLAY_READY", lambda: _guest_ok([
        "/bin/bash", "-lc", f"systemctl is-active --quiet agentie-vnc.service && ss -ltn | grep -q ':{VNC_GUEST_PORT} '",
    ]) and _port_open(VNC_HOST_PORT), 120, "Agentie Computer desktop is running, but its display service did not become reachable.")
    _start_display_server()
    _start_vnc_websocket_bridge()
    if not _port_open(DISPLAY_HTTP_PORT) or not _port_open(VNC_WEBSOCKET_PORT):
        raise ComputerError("Agentie Computer display bridge did not become ready.")
    _wait("BROWSER_READY", _cdp_ready, 180,
          "Agentie Computer desktop is ready, but Chromium did not become available.")
    _update(state="READY", readiness_stage="ready", last_error=None, last_activity=_now())


def start() -> dict[str, Any]:
    with _STATE_LOCK:
        if _vm_running():
            _start_display_server()
            if _port_open(VNC_HOST_PORT):
                try:
                    _start_vnc_websocket_bridge()
                except Exception:
                    pass
            if _cdp_ready() and _port_open(VNC_WEBSOCKET_PORT):
                touch_activity()
                return status()
        prepare()
        state = _vm_state()
        _update(state="STARTING", readiness_stage="vm_start", last_error=None)
        if state == "saved":
            proc = _run(["startvm", VM_NAME, "--type", "headless"], timeout=60)
        elif state != "running":
            proc = _run(["startvm", VM_NAME, "--type", "headless"], timeout=60)
        else:
            proc = None
        if proc is not None and proc.returncode != 0:
            detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-1800:]
            needs_restart = any(token in detail.lower() for token in ("restart", "reboot", "verr_nem", "driver"))
            _update(state="ERROR", readiness_stage="vm_start", last_error=detail, needs_restart=needs_restart)
            raise ComputerError("Agentie Computer could not start in VirtualBox: " + (detail or "VirtualBox returned an error."))
        deadline = time.time() + 45
        while time.time() < deadline and not _vm_running():
            time.sleep(.5)
        if not _vm_running():
            _update(state="ERROR", readiness_stage="vm_start", last_error="VirtualBox did not report the VM as running.")
            raise ComputerError("Agentie Computer did not start in VirtualBox.")
        try:
            _wait_until_ready()
        except Exception as exc:
            _update(state="ERROR", last_error=str(exc))
            raise
        return status()


def acquire_agent(agent_id: str, job_id: str | None = None) -> dict[str, Any]:
    agent_id = str(agent_id or "").strip() or "agt_general"
    start()
    with _STATE_LOCK:
        row = _row()
        owner = row.get("controller_agent_id")
        if row["state"] == "USER_CONTROL":
            raise ComputerError("The user currently controls Agentie Computer.")
        if row["state"] == "USER_REQUIRED":
            raise ComputerError("Agentie Computer is waiting for user action.")
        if row["state"] == "AGENT_CONTROL" and owner and owner != agent_id:
            raise ComputerError(f"Agentie Computer is currently controlled by {owner}.")
        generation = int(row.get("control_generation") or 0) + (0 if row["state"] == "AGENT_CONTROL" and owner == agent_id else 1)
        return _update(state="AGENT_CONTROL", controller_type="agent", controller_agent_id=agent_id,
                       job_id=job_id, control_generation=generation, takeover_reason=None, last_activity=_now())


def acquire_for_session(session_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    return acquire_agent(_session_agent_id(session_id), job_id)


def request_user_takeover(agent_id: str, reason: str) -> dict[str, Any]:
    with _STATE_LOCK:
        row = _row()
        if row["state"] != "AGENT_CONTROL" or row.get("controller_agent_id") != agent_id:
            raise ComputerError("Only the controlling agent can request user takeover.")
        return _update(state="USER_REQUIRED", controller_type=None,
                       takeover_reason=str(reason or "User action required")[:1000], last_activity=_now())


def request_user_takeover_for_session(session_id: str | None, reason: str) -> dict[str, Any]:
    return request_user_takeover(_session_agent_id(session_id), reason)


def acquire_user() -> dict[str, Any]:
    start()
    with _STATE_LOCK:
        return _update(state="USER_CONTROL", controller_type="user", last_activity=_now())


def continue_agent() -> dict[str, Any]:
    with _STATE_LOCK:
        row = _row()
        agent_id = row.get("controller_agent_id")
        if not agent_id:
            raise ComputerError("There is no paused agent to continue.")
        if row["state"] not in {"USER_CONTROL", "USER_REQUIRED"}:
            raise ComputerError("Agentie Computer is not waiting for user takeover.")
        return _update(state="AGENT_CONTROL", controller_type="agent", takeover_reason=None, last_activity=_now())


def release_control(agent_id: str | None = None) -> dict[str, Any]:
    with _STATE_LOCK:
        row = _row()
        if agent_id and row.get("controller_agent_id") and row.get("controller_agent_id") != agent_id:
            raise ComputerError("Computer control belongs to another agent.")
        return _update(state="IDLE", controller_type=None, controller_agent_id=None, job_id=None,
                       takeover_reason=None, last_activity=_now())


def handoff_agent(from_agent_id: str, to_agent_id: str, job_id: str | None = None) -> dict[str, Any]:
    with _STATE_LOCK:
        row = _row()
        if row["state"] != "AGENT_CONTROL" or row.get("controller_agent_id") != from_agent_id:
            raise ComputerError("Computer handoff requires current agent ownership.")
        return _update(state="AGENT_CONTROL", controller_type="agent", controller_agent_id=to_agent_id,
                       job_id=job_id, control_generation=int(row.get("control_generation") or 0) + 1,
                       last_activity=_now())


def suspend() -> dict[str, Any]:
    with _STATE_LOCK:
        row = _row()
        if row["state"] in {"AGENT_CONTROL", "USER_CONTROL", "USER_REQUIRED"}:
            raise ComputerError("Agentie Computer cannot suspend while it is controlled or waiting for user action.")
        if not _vm_running():
            return _update(state="STOPPED", suspended_snapshot=0)
        _run_checked(["controlvm", VM_NAME, "savestate"], stage="suspend", timeout=120)
        return _update(state="SUSPENDED", suspended_snapshot=1, last_activity=_now())


def resume() -> dict[str, Any]:
    with _STATE_LOCK:
        if _row()["state"] != "SUSPENDED":
            return start()
    return start()


def stop() -> dict[str, Any]:
    with _STATE_LOCK:
        if _vm_running():
            _run(["controlvm", VM_NAME, "acpipowerbutton"], timeout=20)
            deadline = time.time() + 12
            while time.time() < deadline and _vm_running():
                time.sleep(.4)
            if _vm_running():
                _run(["controlvm", VM_NAME, "poweroff"], timeout=30)
        return _update(state="STOPPED", controller_type=None, controller_agent_id=None, job_id=None,
                       takeover_reason=None, suspended_snapshot=0, readiness_stage=None, last_activity=_now())


def display_url(*, view_only: bool = False) -> str:
    return (
        f"http://127.0.0.1:{DISPLAY_HTTP_PORT}/vnc.html?autoconnect=1&resize=scale"
        f"&view_only={1 if view_only else 0}&path=websockify?token=&port={VNC_WEBSOCKET_PORT}"
    )


def status() -> dict[str, Any]:
    row = _row()
    vm_state = _vm_state() if vbox_binary() else "missing"
    running = vm_state == "running"
    if row["state"] not in {"STOPPED", "ERROR", "SUSPENDED"} and not running:
        row = _update(state="STOPPED", controller_type=None, controller_agent_id=None,
                      job_id=None, takeover_reason=None, readiness_stage=None)
    display_ready = running and _port_open(VNC_HOST_PORT) and _port_open(VNC_WEBSOCKET_PORT) and _port_open(DISPLAY_HTTP_PORT)
    browser_ready = running and _cdp_ready()
    row.update({
        "computer_id": "company-default",
        "backend": "virtualbox",
        "persistent": True,
        "running": running,
        "vm_state": vm_state,
        "display_ready": display_ready,
        "browser_ready": browser_ready,
        "display_url": display_url(view_only=row.get("controller_type") == "agent"),
        "cdp_url": f"http://127.0.0.1:{CDP_PORT}",
        "disk_path": str(DISK),
        "disk_exists": DISK.exists(),
        "legacy_qcow2_exists": OLD_QCOW2.exists(),
        "legacy_qcow2_backup_exists": OLD_QCOW2_BACKUP.exists(),
        "profile": host_profile(),
        "vbox_available": vbox_binary() is not None,
        "acceleration": {
            "available": vbox_binary() is not None,
            "accelerator": "virtualbox",
            "reason": None if vbox_binary() else "VirtualBox is not installed yet.",
            "action": None if vbox_binary() else "Open Agentie Computer to let Agentie install VirtualBox.",
        },
    })
    return row
