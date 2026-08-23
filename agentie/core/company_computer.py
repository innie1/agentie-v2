from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
import zipfile
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import psutil

ROOT = Path.cwd() / "workspace" / "company_computer"
RUNTIME_DIR = ROOT / "runtime"
DOWNLOADS_DIR = RUNTIME_DIR / "downloads"
NOVNC_DIR = RUNTIME_DIR / "novnc"
BASE_IMAGE = RUNTIME_DIR / "debian-base.qcow2"
DISK = ROOT / "company-computer.qcow2"
SEED_ISO = ROOT / "cloud-init.iso"
STATE_DB = ROOT / "state.sqlite3"
PID_FILE = ROOT / "qemu.pid"
LOG_FILE = ROOT / "qemu.log"

VNC_DISPLAY = int(os.getenv("AGENTIE_QEMU_VNC_DISPLAY", "1"))
VNC_PORT = 5900 + VNC_DISPLAY
VNC_WEBSOCKET_PORT = int(os.getenv("AGENTIE_QEMU_VNC_WEBSOCKET_PORT", "5701"))
DISPLAY_HTTP_PORT = int(os.getenv("AGENTIE_QEMU_DISPLAY_HTTP_PORT", "6088"))
CDP_PORT = int(os.getenv("AGENTIE_QEMU_CDP_PORT", "9222"))
QMP_PORT = int(os.getenv("AGENTIE_QEMU_QMP_PORT", "4444"))
QGA_PORT = int(os.getenv("AGENTIE_QEMU_QGA_PORT", "4445"))
IDLE_SECONDS = max(60, int(os.getenv("AGENTIE_COMPUTER_IDLE_SECONDS", "600")))
ALLOW_TCG = os.getenv("AGENTIE_QEMU_ALLOW_TCG", "").strip().lower() in {"1", "true", "yes", "on"}
AUTO_INSTALL_QEMU = os.getenv("AGENTIE_QEMU_AUTO_INSTALL", "1").strip().lower() not in {"0", "false", "no", "off"}
NOVNC_VERSION = "1.7.0"
NOVNC_URL = f"https://github.com/novnc/noVNC/archive/refs/tags/v{NOVNC_VERSION}.zip"
DEBIAN_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

_STATE_LOCK = threading.RLock()
_PROCESS: subprocess.Popen[Any] | None = None
_IDLE_THREAD: threading.Thread | None = None
_IDLE_STOP = threading.Event()
_DISPLAY_SERVER: ThreadingHTTPServer | None = None
_DISPLAY_THREAD: threading.Thread | None = None

VALID_STATES = {"STOPPED","STARTING","READY","AGENT_CONTROL","USER_REQUIRED","USER_CONTROL","IDLE","SUSPENDED","ERROR"}


class ComputerError(RuntimeError):
    pass


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


def _now() -> float:
    return time.time()


def _ensure_db() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATE_DB) as db:
        db.execute("""
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
              suspended_snapshot INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("""
            INSERT OR IGNORE INTO computer_state
            (id,state,controller_type,controller_agent_id,job_id,control_generation,last_activity,
             takeover_reason,browser_state,vm_pid,last_error,suspended_snapshot)
            VALUES (1,'STOPPED',NULL,NULL,NULL,0,?,NULL,'{}',NULL,NULL,0)
        """, (_now(),))
        db.commit()


def _row() -> dict[str, Any]:
    _ensure_db()
    with sqlite3.connect(STATE_DB) as db:
        db.row_factory = sqlite3.Row
        item = db.execute("SELECT * FROM computer_state WHERE id=1").fetchone()
    assert item is not None
    result = dict(item)
    try:result["browser_state"] = json.loads(result.get("browser_state") or "{}")
    except Exception:result["browser_state"] = {}
    return result


def _update(**fields: Any) -> dict[str, Any]:
    if not fields:return _row()
    allowed={"state","controller_type","controller_agent_id","job_id","control_generation","last_activity","takeover_reason","browser_state","vm_pid","last_error","suspended_snapshot"};unknown=set(fields)-allowed
    if unknown:raise ValueError(f"Unknown computer state fields: {', '.join(sorted(unknown))}")
    if "state" in fields and fields["state"] not in VALID_STATES:raise ValueError("Invalid Company Computer state.")
    values=dict(fields)
    if isinstance(values.get("browser_state"),dict):values["browser_state"]=json.dumps(values["browser_state"],separators=(",",":"))
    assignments=", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(STATE_DB) as db:db.execute(f"UPDATE computer_state SET {assignments} WHERE id=1",list(values.values()));db.commit()
    return _row()


def touch_activity(browser_state: dict[str, Any] | None = None) -> dict[str, Any]:
    fields:dict[str,Any]={"last_activity":_now()}
    if browser_state is not None:fields["browser_state"]=browser_state
    return _update(**fields)


def _free_port(port:int)->bool:
    try:
        with closing(socket.socket(socket.AF_INET,socket.SOCK_STREAM)) as sock:sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(("127.0.0.1",port))
        return True
    except OSError:return False

def _port_open(port:int,timeout:float=.15)->bool:
    try:
        with socket.create_connection(("127.0.0.1",port),timeout=timeout):return True
    except OSError:return False


def host_profile()->dict[str,Any]:
    system=platform.system().lower();machine=platform.machine().lower();logical=max(1,int(psutil.cpu_count(logical=True) or 1));memory_mb=max(512,int(psutil.virtual_memory().total/(1024*1024)))
    if memory_mb<4096:ram_mb,vcpus=1024,1
    elif memory_mb<8192:ram_mb,vcpus=1536,min(2,logical)
    elif memory_mb<16384:ram_mb,vcpus=2048,min(2,logical)
    else:ram_mb,vcpus=3072,min(4,logical)
    ram_mb=min(ram_mb,max(768,memory_mb//3));return {"system":system,"machine":machine,"logical_cpus":logical,"memory_mb":memory_mb,"vm_ram_mb":ram_mb,"vm_vcpus":max(1,vcpus),"low_end":memory_mb<4096 or logical<=2}

def _qemu_names(profile:dict[str,Any])->list[str]:
    names=["qemu-system-aarch64"] if profile["machine"] in {"arm64","aarch64"} else ["qemu-system-x86_64"];return [name+".exe" for name in names]+names if os.name=="nt" else names
def qemu_binary(profile:dict[str,Any]|None=None)->str|None:
    info=profile or host_profile();bundled=Path.cwd()/"runtime"/"qemu";candidates:list[Path]=[]
    for name in _qemu_names(info):
        candidates.extend([bundled/name,bundled/"bin"/name]);found=shutil.which(name)
        if found:candidates.append(Path(found))
        if os.name=="nt":candidates.append(Path(os.environ.get("ProgramFiles",r"C:\Program Files"))/"qemu"/name)
    for candidate in candidates:
        if candidate.exists():return str(candidate)
    return None
def qemu_img_binary(qemu:str|None=None)->str|None:
    if qemu:
        path=Path(qemu);adjacent=path.with_name("qemu-img.exe" if path.suffix.lower()==".exe" else "qemu-img")
        if adjacent.exists():return str(adjacent)
    for name in (["qemu-img.exe","qemu-img"] if os.name=="nt" else ["qemu-img"]):
        found=shutil.which(name)
        if found:return found
    bundled=Path.cwd()/"runtime"/"qemu"
    for name in ("qemu-img.exe","qemu-img"):
        for candidate in (bundled/name,bundled/"bin"/name):
            if candidate.exists():return str(candidate)
    return None

def _run_installer(command:list[str],timeout:int=600)->tuple[bool,str]:
    try:
        proc=subprocess.run(command,capture_output=True,text=True,timeout=timeout,shell=False);detail=((proc.stdout or "")+"\n"+(proc.stderr or "")).strip();return proc.returncode==0,detail[-3000:]
    except Exception as exc:return False,str(exc)
def install_qemu()->str:
    profile=host_profile();found=qemu_binary(profile)
    if found:return found
    if not AUTO_INSTALL_QEMU:raise ComputerError("QEMU is missing and automatic Computer runtime installation is disabled.")
    system=profile["system"];attempts:list[tuple[list[str],str]]=[]
    if system=="windows":
        winget=shutil.which("winget")
        if winget:attempts.append(([winget,"install","--id","SoftwareFreedomConservancy.QEMU","-e","--silent","--accept-package-agreements","--accept-source-agreements"],"Windows Package Manager"))
    elif system=="darwin":
        brew=shutil.which("brew")
        if brew:attempts.append(([brew,"install","qemu"],"Homebrew"))
    elif system=="linux":
        pkexec=shutil.which("pkexec")
        if pkexec and shutil.which("apt-get"):attempts.append(([pkexec,"apt-get","install","-y","qemu-system","qemu-utils"],"apt"))
        elif pkexec and shutil.which("dnf"):attempts.append(([pkexec,"dnf","install","-y","qemu-system-x86","qemu-img"],"dnf"))
        elif pkexec and shutil.which("pacman"):attempts.append(([pkexec,"pacman","-S","--noconfirm","qemu-desktop"],"pacman"))
    errors=[]
    for command,name in attempts:
        ok,detail=_run_installer(command)
        if ok:
            found=qemu_binary(profile)
            if found:return found
        errors.append(f"{name}: {detail or 'installation did not expose QEMU'}")
    hint={"windows":"Install QEMU with Windows Package Manager or include it in Agentie's runtime/qemu bundle.","darwin":"Install QEMU with Homebrew or include it in Agentie's runtime/qemu bundle.","linux":"Install qemu-system and qemu-utils with your distribution package manager."}.get(system,"Install a supported QEMU build.")
    raise ComputerError("Agentie could not prepare QEMU automatically. "+hint+(" Details: "+" | ".join(errors) if errors else ""))
def _accel_help(qemu:str)->set[str]:
    try:proc=subprocess.run([qemu,"-accel","help"],capture_output=True,text=True,timeout=8,shell=False);text=((proc.stdout or "")+"\n"+(proc.stderr or "")).lower()
    except Exception:return set()
    return {name for name in ("whpx","hvf","kvm","tcg") if name in text}
def _whpx_feature_enabled()->bool:
    if platform.system().lower()!="windows":return False
    try:proc=subprocess.run(["dism.exe","/Online","/Get-FeatureInfo","/FeatureName:HypervisorPlatform","/English"],capture_output=True,text=True,timeout=12,shell=False);text=((proc.stdout or "")+"\n"+(proc.stderr or "")).lower();return proc.returncode==0 and "state : enabled" in text
    except Exception:return False
def acceleration(qemu:str|None=None,profile:dict[str,Any]|None=None)->dict[str,Any]:
    info=profile or host_profile();binary=qemu or qemu_binary(info)
    if not binary:return {"available":False,"accelerator":None,"reason":"QEMU is not installed yet.","action":"Open Agentie Computer to let Agentie install or locate QEMU."}
    supported=_accel_help(binary);system=info["system"]
    if system=="windows":wanted="whpx";enabled=wanted in supported and _whpx_feature_enabled();action="Enable Windows Hypervisor Platform and CPU virtualization in firmware, then restart Windows."
    elif system=="darwin":wanted="hvf";enabled=wanted in supported;action="Use a QEMU build with HVF support and a Mac that supports hardware virtualization."
    elif system=="linux":wanted="kvm";enabled=wanted in supported and os.path.exists("/dev/kvm") and os.access("/dev/kvm",os.R_OK|os.W_OK);action="Enable KVM/CPU virtualization and give your user read/write access to /dev/kvm."
    else:wanted=None;enabled=False;action=f"Agentie Computer does not support {platform.system()} yet."
    if enabled:return {"available":True,"accelerator":wanted,"reason":None,"action":None}
    if ALLOW_TCG and "tcg" in supported:return {"available":True,"accelerator":"tcg","compatibility_mode":True,"reason":f"{wanted or 'hardware acceleration'} is unavailable; explicit slow compatibility mode is enabled.","action":None}
    return {"available":False,"accelerator":wanted,"reason":f"{(wanted or 'Hardware acceleration').upper()} is unavailable.","action":action}


def _debian_filename(profile:dict[str,Any])->str:
    arch=DEBIAN_ARCH.get(profile["machine"])
    if not arch:raise ComputerError(f"Unsupported host architecture: {profile['machine']}.")
    return f"debian-13-genericcloud-{arch}.qcow2"
def _debian_url(profile:dict[str,Any])->str:return "https://cloud.debian.org/images/cloud/trixie/latest/"+_debian_filename(profile)
def _download(url:str,destination:Path,*,timeout:int=300)->None:
    destination.parent.mkdir(parents=True,exist_ok=True);partial=destination.with_suffix(destination.suffix+".part");request=urllib.request.Request(url,headers={"User-Agent":"Agentie/1.0"})
    with urllib.request.urlopen(request,timeout=timeout) as response,partial.open("wb") as output:shutil.copyfileobj(response,output,length=1024*1024)
    partial.replace(destination)
def _verify_debian_image(profile:dict[str,Any])->None:
    request=urllib.request.Request("https://cloud.debian.org/images/cloud/trixie/latest/SHA512SUMS",headers={"User-Agent":"Agentie/1.0"})
    with urllib.request.urlopen(request,timeout=60) as response:text=response.read().decode("utf-8","replace")
    filename=_debian_filename(profile);expected=None
    for line in text.splitlines():
        parts=line.split()
        if len(parts)>=2 and parts[-1].lstrip("*")==filename:expected=parts[0].lower();break
    if not expected:raise ComputerError("Could not verify the Debian Company Computer image checksum.")
    digest=hashlib.sha512()
    with BASE_IMAGE.open("rb") as source:
        for chunk in iter(lambda:source.read(1024*1024),b""):digest.update(chunk)
    if digest.hexdigest().lower()!=expected:BASE_IMAGE.unlink(missing_ok=True);raise ComputerError("Downloaded Company Computer base image failed SHA-512 verification.")
def ensure_novnc()->Path:
    entry=NOVNC_DIR/"vnc.html"
    if entry.exists():return entry
    DOWNLOADS_DIR.mkdir(parents=True,exist_ok=True);archive=DOWNLOADS_DIR/f"novnc-{NOVNC_VERSION}.zip"
    if not archive.exists():_download(NOVNC_URL,archive)
    extract_root=DOWNLOADS_DIR/f"novnc-extract-{NOVNC_VERSION}";shutil.rmtree(extract_root,ignore_errors=True);extract_root.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:bundle.extractall(extract_root)
    roots=[p for p in extract_root.iterdir() if p.is_dir()];source=roots[0] if len(roots)==1 else extract_root;shutil.rmtree(NOVNC_DIR,ignore_errors=True);shutil.copytree(source,NOVNC_DIR)
    if not entry.exists():raise ComputerError("noVNC runtime did not contain vnc.html.")
    return entry
def _start_display_server()->None:
    global _DISPLAY_SERVER,_DISPLAY_THREAD
    ensure_novnc()
    if _DISPLAY_SERVER is not None and _DISPLAY_THREAD is not None and _DISPLAY_THREAD.is_alive():return
    if not _free_port(DISPLAY_HTTP_PORT):
        if _port_open(DISPLAY_HTTP_PORT):return
        raise ComputerError(f"Agentie Computer display port {DISPLAY_HTTP_PORT} is unavailable.")
    handler=partial(_QuietHandler,directory=str(NOVNC_DIR));_DISPLAY_SERVER=ThreadingHTTPServer(("127.0.0.1",DISPLAY_HTTP_PORT),handler);_DISPLAY_THREAD=threading.Thread(target=_DISPLAY_SERVER.serve_forever,name="agentie-computer-display",daemon=True);_DISPLAY_THREAD.start()


def _cloud_init_user_data()->str:
    return """#cloud-config
hostname: agentie-computer
manage_etc_hosts: true
users:
  - name: agentie
    gecos: Agentie
    groups: [sudo, audio, video, plugdev]
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
disable_root: true
ssh_pwauth: false
package_update: true
packages:
  - xserver-xorg
  - xinit
  - openbox
  - dbus-x11
  - pcmanfm
  - xterm
  - chromium
  - qemu-guest-agent
  - curl
  - ca-certificates
  - unzip
  - fonts-dejavu-core
write_files:
  - path: /home/agentie/.xinitrc
    permissions: '0755'
    owner: agentie:agentie
    content: |
      #!/bin/sh
      export DISPLAY=:0
      export XDG_RUNTIME_DIR=/tmp/runtime-agentie
      mkdir -p "$XDG_RUNTIME_DIR"
      chmod 700 "$XDG_RUNTIME_DIR"
      dbus-launch --exit-with-session sh -c '
        pcmanfm --desktop --profile LXDE >/tmp/pcmanfm.log 2>&1 &
        chromium --user-data-dir=/home/agentie/.config/chromium-agentie --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --no-first-run --no-default-browser-check --restore-last-session about:blank >/tmp/chromium.log 2>&1 &
        exec openbox-session
      '
  - path: /etc/systemd/system/agentie-desktop.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Agentie lightweight desktop
      After=network-online.target cloud-final.service
      Wants=network-online.target
      [Service]
      User=agentie
      Environment=HOME=/home/agentie
      WorkingDirectory=/home/agentie
      ExecStart=/usr/bin/startx /home/agentie/.xinitrc -- :0 -nolisten tcp vt1
      Restart=always
      RestartSec=2
      [Install]
      WantedBy=graphical.target
runcmd:
  - [mkdir, -p, /home/agentie/Downloads]
  - [mkdir, -p, /home/agentie/Desktop]
  - [chown, -R, "agentie:agentie", /home/agentie]
  - [systemctl, enable, --now, qemu-guest-agent]
  - [systemctl, enable, agentie-desktop.service]
  - [systemctl, set-default, graphical.target]
  - [systemctl, start, agentie-desktop.service]
final_message: "Agentie Computer guest is ready."
"""
def ensure_seed_iso()->Path:
    if SEED_ISO.exists():return SEED_ISO
    try:import pycdlib
    except ImportError as exc:raise ComputerError("Agentie Computer requires pycdlib; reinstall Agentie dependencies.") from exc
    ROOT.mkdir(parents=True,exist_ok=True);temp=ROOT/"seed";shutil.rmtree(temp,ignore_errors=True);temp.mkdir(parents=True);(temp/"user-data").write_text(_cloud_init_user_data(),encoding="utf-8");(temp/"meta-data").write_text("instance-id: agentie-company-computer\nlocal-hostname: agentie-computer\n",encoding="utf-8");iso=pycdlib.PyCdlib();iso.new(interchange_level=3,joliet=3,vol_ident="cidata");iso.add_file(str(temp/"user-data"),iso_path="/USER_DAT.;1",joliet_path="/user-data");iso.add_file(str(temp/"meta-data"),iso_path="/META_DAT.;1",joliet_path="/meta-data");iso.write(str(SEED_ISO));iso.close();shutil.rmtree(temp,ignore_errors=True);return SEED_ISO
def ensure_disk(qemu_img:str,profile:dict[str,Any]|None=None)->Path:
    if DISK.exists():return DISK
    info=profile or host_profile();RUNTIME_DIR.mkdir(parents=True,exist_ok=True)
    if not BASE_IMAGE.exists():_download(_debian_url(info),BASE_IMAGE);_verify_debian_image(info)
    proc=subprocess.run([qemu_img,"convert","-p","-O","qcow2",str(BASE_IMAGE),str(DISK)],capture_output=True,text=True,timeout=300,shell=False)
    if proc.returncode!=0:DISK.unlink(missing_ok=True);raise ComputerError("Could not create persistent QCOW2 disk: "+((proc.stderr or proc.stdout or "").strip()[-1200:]))
    proc=subprocess.run([qemu_img,"resize",str(DISK),"12G"],capture_output=True,text=True,timeout=30,shell=False)
    if proc.returncode!=0:raise ComputerError("Could not resize persistent QCOW2 disk: "+((proc.stderr or proc.stdout or "").strip()[-800:]))
    return DISK
def prepare()->dict[str,Any]:
    profile=host_profile();qemu=qemu_binary(profile) or install_qemu();qemu_img=qemu_img_binary(qemu)
    if not qemu_img:raise ComputerError("qemu-img is missing from the QEMU installation.")
    accel=acceleration(qemu,profile)
    if not accel.get("available"):raise ComputerError(f"{accel['reason']} {accel['action']}")
    ensure_novnc();ensure_seed_iso();ensure_disk(qemu_img,profile);_start_display_server();return {"profile":profile,"qemu":qemu,"qemu_img":qemu_img,"acceleration":accel}
def _is_pid_alive(pid:int|None)->bool:
    if not pid:return False
    try:proc=psutil.Process(int(pid));return proc.is_running() and proc.status()!=psutil.STATUS_ZOMBIE
    except Exception:return False
def _qmp_command(command:str,arguments:dict[str,Any]|None=None,timeout:float=3.0)->dict[str,Any]:
    with socket.create_connection(("127.0.0.1",QMP_PORT),timeout=timeout) as sock:
        file=sock.makefile("rwb",buffering=0);file.readline();file.write(json.dumps({"execute":"qmp_capabilities"}).encode()+b"\r\n");file.readline();payload:dict[str,Any]={"execute":command}
        if arguments:payload["arguments"]=arguments
        file.write(json.dumps(payload).encode()+b"\r\n");deadline=time.time()+timeout
        while time.time()<deadline:
            line=file.readline()
            if not line:break
            item=json.loads(line.decode("utf-8","replace"))
            if "return" in item or "error" in item:return item
    raise ComputerError(f"QMP command timed out: {command}")
def _hmp(command:str)->str:
    result=_qmp_command("human-monitor-command",{"command-line":command},timeout=12)
    if result.get("error"):raise ComputerError(str(result["error"]))
    return str(result.get("return") or "")
def _aarch64_firmware(qemu:str)->str:
    qpath=Path(qemu).resolve();candidates=[qpath.parent.parent/"share"/"qemu"/"edk2-aarch64-code.fd",qpath.parent/"../share/qemu/edk2-aarch64-code.fd",Path("/opt/homebrew/share/qemu/edk2-aarch64-code.fd"),Path("/usr/local/share/qemu/edk2-aarch64-code.fd"),Path("/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"),Path("/usr/share/AAVMF/AAVMF_CODE.fd")]
    for item in candidates:
        try:item=item.resolve()
        except Exception:pass
        if item.exists():return str(item)
    raise ComputerError("QEMU ARM64 firmware was not found. Install QEMU's EDK2/AAVMF firmware package.")
def _qemu_args(config:dict[str,Any],*,resume_snapshot:bool=False)->list[str]:
    profile=config["profile"];accel=config["acceleration"]["accelerator"];qemu=config["qemu"];machine=profile["machine"];args=[qemu,"-name","Agentie Company Computer","-m",str(profile["vm_ram_mb"]),"-smp",str(profile["vm_vcpus"]),"-accel",accel]
    if machine in {"arm64","aarch64"}:args += ["-machine","virt","-cpu","host","-bios",_aarch64_firmware(qemu),"-device","virtio-gpu-pci"]
    else:args += ["-machine","q35","-cpu","host","-device","virtio-vga"]
    args += ["-drive",f"file={DISK},if=virtio,format=qcow2,cache=writeback,discard=unmap","-drive",f"file={SEED_ISO},media=cdrom,readonly=on","-netdev",f"user,id=net0,hostfwd=tcp:127.0.0.1:{CDP_PORT}-:{CDP_PORT}","-device","virtio-net-pci,netdev=net0","-vnc",f"127.0.0.1:{VNC_DISPLAY},websocket={VNC_WEBSOCKET_PORT}","-qmp",f"tcp:127.0.0.1:{QMP_PORT},server=on,wait=off","-chardev",f"socket,id=qga0,host=127.0.0.1,port={QGA_PORT},server=on,wait=off","-device","virtio-serial-pci","-device","virtserialport,chardev=qga0,name=org.qemu.guest_agent.0","-pidfile",str(PID_FILE),"-display","none"]
    if resume_snapshot:args += ["-loadvm","agentie-idle"]
    return args
def start()->dict[str,Any]:
    global _PROCESS
    with _STATE_LOCK:
        current=_row()
        if _is_pid_alive(current.get("vm_pid")) and _port_open(VNC_PORT):_start_display_server();touch_activity();return status()
        config=prepare()
        for port in (VNC_PORT,VNC_WEBSOCKET_PORT,CDP_PORT,QMP_PORT,QGA_PORT):
            if not _free_port(port):raise ComputerError(f"Agentie Computer cannot start because local port {port} is already in use.")
        resume_snapshot=bool(current.get("suspended_snapshot"));_update(state="STARTING",last_error=None,last_activity=_now(),vm_pid=None);LOG_FILE.parent.mkdir(parents=True,exist_ok=True);log=LOG_FILE.open("ab");kwargs:dict[str,Any]={"stdin":subprocess.DEVNULL,"stdout":log,"stderr":subprocess.STDOUT,"cwd":str(Path.cwd())}
        if os.name=="nt":kwargs["creationflags"]=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP
        else:kwargs["start_new_session"]=True
        try:_PROCESS=subprocess.Popen(_qemu_args(config,resume_snapshot=resume_snapshot),**kwargs)
        except Exception as exc:log.close();_update(state="ERROR",last_error=str(exc),vm_pid=None);raise ComputerError(f"Could not launch QEMU: {exc}") from exc
        _update(vm_pid=_PROCESS.pid);deadline=time.time()+30
        while time.time()<deadline:
            if _PROCESS.poll() is not None:_update(state="ERROR",last_error="QEMU exited during startup.",vm_pid=None);raise ComputerError("QEMU exited while Agentie Computer was starting. Check workspace/company_computer/qemu.log.")
            if _port_open(VNC_PORT) and _port_open(QMP_PORT):
                _update(state="READY",suspended_snapshot=0,last_activity=_now())
                if resume_snapshot:
                    try:_hmp("delvm agentie-idle")
                    except Exception:pass
                return status()
            time.sleep(.2)
        _update(state="ERROR",last_error="QEMU display did not become ready.");raise ComputerError("Agentie Computer started QEMU, but its display did not become ready.")
def _clear_control(next_state:str="READY")->dict[str,Any]:
    row=_row();return _update(state=next_state,controller_type=None,controller_agent_id=None,job_id=None,takeover_reason=None,control_generation=int(row.get("control_generation") or 0)+1,last_activity=_now())
def stop()->dict[str,Any]:
    global _PROCESS
    with _STATE_LOCK:
        current=_row();pid=current.get("vm_pid")
        if not _is_pid_alive(pid):_PROCESS=None;_update(state="STOPPED",vm_pid=None,controller_type=None,controller_agent_id=None,job_id=None,takeover_reason=None,suspended_snapshot=0,last_activity=_now());return status()
        try:_qmp_command("system_powerdown")
        except Exception:pass
        deadline=time.time()+15
        while time.time()<deadline and _is_pid_alive(pid):time.sleep(.25)
        if _is_pid_alive(pid):
            try:_qmp_command("quit")
            except Exception:
                try:psutil.Process(int(pid)).terminate()
                except Exception:pass
        _PROCESS=None;_update(state="STOPPED",vm_pid=None,controller_type=None,controller_agent_id=None,job_id=None,takeover_reason=None,suspended_snapshot=0,last_activity=_now());return status()
def suspend()->dict[str,Any]:
    global _PROCESS
    with _STATE_LOCK:
        current=_row()
        if not _is_pid_alive(current.get("vm_pid")):_update(state="SUSPENDED",vm_pid=None,suspended_snapshot=int(bool(current.get("suspended_snapshot"))));return status()
        if current.get("controller_type"):raise ComputerError("Cannot suspend Agentie Computer while a user or agent owns control.")
        try:
            try:_hmp("delvm agentie-idle")
            except Exception:pass
            _hmp("savevm agentie-idle");_qmp_command("quit")
        except Exception as exc:raise ComputerError(f"Could not suspend Agentie Computer: {exc}") from exc
        deadline=time.time()+8
        while time.time()<deadline and _is_pid_alive(current.get("vm_pid")):time.sleep(.2)
        _PROCESS=None;_update(state="SUSPENDED",vm_pid=None,suspended_snapshot=1,last_activity=_now());return status()
def resume()->dict[str,Any]:return start()
def acquire_agent(agent_id:str,job_id:str|None=None)->dict[str,Any]:
    if not str(agent_id or "").strip():raise ComputerError("Agent identity is required to control Agentie Computer.")
    start()
    with _STATE_LOCK:
        current=_row();owner=current.get("controller_type");owner_agent=current.get("controller_agent_id")
        if owner=="user":raise ComputerError("User currently controls Agentie Computer.")
        if owner=="agent" and owner_agent not in {None,agent_id}:raise ComputerError(f"Agentie Computer is currently controlled by agent {owner_agent}.")
        return _update(state="AGENT_CONTROL",controller_type="agent",controller_agent_id=agent_id,job_id=job_id,takeover_reason=None,last_activity=_now())
def handoff_agent(from_agent_id:str,to_agent_id:str,job_id:str|None=None)->dict[str,Any]:
    with _STATE_LOCK:
        current=_row()
        if current.get("controller_type")!="agent" or current.get("controller_agent_id")!=from_agent_id:raise ComputerError("Only the agent currently controlling Agentie Computer can hand it off.")
        return _update(state="AGENT_CONTROL",controller_agent_id=to_agent_id,job_id=job_id,control_generation=int(current.get("control_generation") or 0)+1,last_activity=_now())
def request_user_takeover(agent_id:str,reason:str)->dict[str,Any]:
    with _STATE_LOCK:
        current=_row()
        if current.get("controller_type")!="agent" or current.get("controller_agent_id")!=agent_id:raise ComputerError("Only the controlling agent can request user takeover.")
        return _update(state="USER_REQUIRED",takeover_reason=str(reason or "User action required")[:1000],last_activity=_now())
def acquire_user()->dict[str,Any]:
    start()
    with _STATE_LOCK:
        current=_row()
        if current.get("controller_type")=="agent" and current.get("state")!="USER_REQUIRED":raise ComputerError("An agent is currently working. It must pause before user takeover.")
        return _update(state="USER_CONTROL",controller_type="user",control_generation=int(current.get("control_generation") or 0)+1,last_activity=_now())
def continue_agent()->dict[str,Any]:
    with _STATE_LOCK:
        current=_row();agent_id=current.get("controller_agent_id")
        if current.get("controller_type")!="user" or not agent_id:raise ComputerError("There is no paused agent to continue.")
        return _update(state="AGENT_CONTROL",controller_type="agent",takeover_reason=None,control_generation=int(current.get("control_generation") or 0)+1,last_activity=_now())
def release_control(agent_id:str|None=None)->dict[str,Any]:
    with _STATE_LOCK:
        current=_row()
        if agent_id and current.get("controller_type")=="agent" and current.get("controller_agent_id")!=agent_id:raise ComputerError("This agent does not own Agentie Computer.")
        return _clear_control("IDLE")
def _session_agent_id(session_key:str|None)->str:
    text=str(session_key or "")
    if text.startswith("agent:"):
        parts=text.split(":")
        if len(parts)>=2 and parts[1]:return parts[1]
    return "base"
def acquire_for_session(session_key:str|None,job_id:str|None=None)->dict[str,Any]:return acquire_agent(_session_agent_id(session_key),job_id)
def request_user_takeover_for_session(session_key:str|None,reason:str)->dict[str,Any]:return request_user_takeover(_session_agent_id(session_key),reason)
def display_url(*,view_only:bool|None=None)->str:
    current=_row()
    if view_only is None:view_only=current.get("controller_type")!="user"
    flag="1" if view_only else "0";return f"http://127.0.0.1:{DISPLAY_HTTP_PORT}/vnc.html?autoconnect=1&resize=remote&view_only={flag}&host=127.0.0.1&port={VNC_WEBSOCKET_PORT}"
def status()->dict[str,Any]:
    current=_row();pid=current.get("vm_pid");alive=_is_pid_alive(pid)
    if current.get("state") in {"STARTING","READY","AGENT_CONTROL","USER_REQUIRED","USER_CONTROL","IDLE"} and not alive:current=_update(state="STOPPED",vm_pid=None,controller_type=None,controller_agent_id=None,job_id=None,takeover_reason=None);alive=False
    profile=host_profile();qemu=qemu_binary(profile);accel=acceleration(qemu,profile) if qemu else {"available":False,"accelerator":None,"reason":"QEMU is not installed yet.","action":"Open Agentie Computer to let Agentie prepare QEMU."}
    return {**current,"computer_id":"company-default","running":alive and current.get("state") not in {"STOPPED","SUSPENDED","ERROR"},"display_ready":alive and _port_open(VNC_PORT) and _port_open(DISPLAY_HTTP_PORT),"browser_ready":alive and _port_open(CDP_PORT),"display_url":display_url(view_only=current.get("controller_type")!="user") if alive else None,"cdp_url":f"http://127.0.0.1:{CDP_PORT}" if alive else None,"disk_path":str(DISK),"disk_exists":DISK.exists(),"profile":profile,"acceleration":accel,"persistent":True}
def _qga_request(payload:dict[str,Any],timeout:float=10.0)->dict[str,Any]:
    if not _port_open(QGA_PORT):raise ComputerError("Guest automation channel is not ready yet.")
    with socket.create_connection(("127.0.0.1",QGA_PORT),timeout=timeout) as sock:
        sock.settimeout(timeout);file=sock.makefile("rwb",buffering=0);file.write(json.dumps(payload).encode()+b"\n");deadline=time.time()+timeout
        while time.time()<deadline:
            line=file.readline()
            if not line:break
            try:item=json.loads(line.decode("utf-8","replace"))
            except json.JSONDecodeError:continue
            if "return" in item or "error" in item:return item
    raise ComputerError("Guest automation command timed out.")
def guest_exec(command:list[str],timeout:int=60)->dict[str,Any]:
    if not command:raise ValueError("Guest command is required.")
    response=_qga_request({"execute":"guest-exec","arguments":{"path":command[0],"arg":command[1:],"capture-output":True}})
    if response.get("error"):raise ComputerError(str(response["error"]))
    pid=int((response.get("return") or {}).get("pid") or 0)
    if not pid:raise ComputerError("Guest command did not start.")
    deadline=time.time()+timeout
    while time.time()<deadline:
        item=_qga_request({"execute":"guest-exec-status","arguments":{"pid":pid}});result=item.get("return") or {}
        if result.get("exited"):touch_activity();return result
        time.sleep(.2)
    raise ComputerError("Guest command timed out.")
def qmp_input(events:list[dict[str,Any]])->None:
    result=_qmp_command("input-send-event",{"events":events})
    if result.get("error"):raise ComputerError(str(result["error"]))
    touch_activity()
def start_idle_monitor()->None:
    global _IDLE_THREAD
    if _IDLE_THREAD and _IDLE_THREAD.is_alive():return
    _IDLE_STOP.clear()
    def worker()->None:
        while not _IDLE_STOP.wait(15):
            try:
                current=_row()
                if current.get("state") not in {"READY","IDLE"} or current.get("controller_type"):continue
                if _now()-float(current.get("last_activity") or _now())>=IDLE_SECONDS:suspend()
            except Exception:continue
    _IDLE_THREAD=threading.Thread(target=worker,name="agentie-company-computer-idle",daemon=True);_IDLE_THREAD.start()
def stop_idle_monitor()->None:_IDLE_STOP.set()
