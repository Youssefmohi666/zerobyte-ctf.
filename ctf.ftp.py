#!/usr/bin/env python3
"""
Metasploitable 2 - vsftpd 2.3.4 Vulnerable FTP Server Simulator
================================================================
For educational purposes, CTF labs, and penetration testing training only.
Simulates the following vulnerabilities:
  - CVE-2011-2523 : vsftpd 2.3.4 Backdoor (smiley face :) in USER triggers shell on port 6200)
  - Anonymous FTP login enabled (misconfiguration)
  - Weak credentials (common Metasploitable 2 accounts)
  - Directory traversal weakness (passive mode path disclosure)
  - Cleartext credentials (FTP has no encryption)

Usage:
  sudo python3 msf2_ftp_server.py [--host 0.0.0.0] [--port 21] [--root /tmp/ftp_root]

Exploit the backdoor:
  echo -e "USER backdoor:)\nPASS anything" | nc <host> 21
  nc <host> 6200       # → root shell!

  Or via Metasploit:
  use exploit/unix/ftp/vsftpd_234_backdoor
"""

import socket
import threading
import subprocess
import os
import sys
import argparse
import logging
import time
import random
from pathlib import Path
from datetime import datetime

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
BANNER       = "220 (vsFTPd 2.3.4)"
GOODBYE      = "221 Goodbye."
BACKDOOR_PORT = 6200

# Simulated user database (Metasploitable 2 defaults)
USERS = {
    "anonymous": "",           # anonymous login – accepts any password
    "ftp":        "",           # alias for anonymous
    "msfadmin":  "msfadmin",   # default Metasploitable admin
    "user":      "user",
    "service":   "service",
    "postgres":  "postgres",
    "root":      "toor",        # classic Metasploitable root
}

# Simulated directory tree (in-memory virtual FS)
VIRTUAL_FS = {
    "/":            {"type": "dir",  "perm": "drwxr-xr-x"},
    "/pub":         {"type": "dir",  "perm": "drwxr-xr-x"},
    "/pub/readme":  {"type": "file", "perm": "-rw-r--r--", "content": b"0BYTE{$FLAG$_-001.2_FTP_HACKED:)}\n"},
    "/incoming":    {"type": "dir",  "perm": "drwxrwxrwx"},
    "/etc":         {"type": "dir",  "perm": "drwxr-xr-x"},
    "/etc/passwd":  {"type": "file", "perm": "-rw-r--r--",
                     "content": (
                         b"root:x:0:0:root:/root:/bin/bash\n"
                         b"daemon:x:1:1:daemon:/usr/sbin:/bin/sh\n"
                         b"msfadmin:x:1000:1000:msfadmin,,,:/home/msfadmin:/bin/bash\n"
                         b"ftp:x:104:65534::/home/ftp:/bin/false\n"
                     )},
}

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vsftpd-2.3.4")


# ══════════════════════════════════════════════
# CVE-2011-2523 – Backdoor Shell Server
# ══════════════════════════════════════════════
class BackdoorServer:
    """
    Opens a raw TCP listener on port 6200 when the backdoor is triggered.
    Simulates the /bin/sh shell spawned by the patched vsftpd binary.
    """
    _instance = None
    _lock     = threading.Lock()

    @classmethod
    def trigger(cls, attacker_ip: str):
        with cls._lock:
            if cls._instance and cls._instance.is_alive():
                log.warning("[BACKDOOR] Already running – ignoring duplicate trigger")
                return
            t = threading.Thread(target=cls._serve, args=(attacker_ip,), daemon=True)
            t.start()
            cls._instance = t

    @staticmethod
    def _serve(attacker_ip: str):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", BACKDOOR_PORT))
            srv.listen(1)
            log.critical(
                f"\n{'='*60}\n"
                f"  CVE-2011-2523 TRIGGERED by {attacker_ip}\n"
                f"  Backdoor shell listening on port {BACKDOOR_PORT}\n"
                f"  Connect with: nc {attacker_ip} {BACKDOOR_PORT}\n"
                f"{'='*60}"
            )
            srv.settimeout(30)
            conn, addr = srv.accept()
            log.critical(f"[BACKDOOR] Shell connection from {addr[0]}:{addr[1]}")

            # Simulate an interactive root shell
            conn.sendall(b"\n")   # vsftpd sends nothing – prompt comes from sh
            _simulate_shell(conn)
        except socket.timeout:
            log.warning("[BACKDOOR] No connection within 30 s – closing backdoor port")
        except Exception as e:
            log.error(f"[BACKDOOR] Error: {e}")
        finally:
            try:
                srv.close()
            except Exception:
                pass


def _simulate_shell(conn: socket.socket):
    """Minimal interactive shell simulator running as 'root'."""
    FS_STATE = {
        "cwd": "/root",
        "hostname": "metasploitable",
        "user": "root",
    }

    FAKE_FILES = {
        "/root": [".", "..", ".bash_history", ".bashrc", "flag.txt"],
        "/":     ["bin", "boot", "dev", "etc", "home", "lib", "proc", "root", "tmp", "usr", "var"],
        "/etc":  ["passwd", "shadow", "hosts", "hostname"],
        "/tmp":  [".", ".."],
    }

    FILE_CONTENTS = {
        "/root/flag.txt":    b"FLAG{vsftpd_2_3_4_b4ckd00r_CVE-2011-2523}\n",
        "/etc/passwd":       VIRTUAL_FS["/etc/passwd"]["content"],
        "/etc/hostname":     b"metasploitable\n",
        "/root/.bash_history": b"ls\nid\ncat /etc/passwd\n",
        "/etc/shadow":       b"root:$1$toor$rLWFGGoLPTU8EGHlWqCcN.:14809:0:99999:7:::\n"
                             b"msfadmin:$1$XN10Zj2c$Rt/zzCW3mLtUWA.ihZjA5/:14809:0:99999:7:::\n",
    }

    def prompt():
        cwd = FS_STATE["cwd"]
        disp = "~" if cwd == "/root" else cwd
        return f"root@{FS_STATE['hostname']}:{disp}# ".encode()

    conn.sendall(prompt())

    buf = b""
    while True:
        try:
            conn.settimeout(120)
            chunk = conn.recv(1024)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.strip().decode(errors="ignore")
                response = _handle_shell_cmd(cmd, FS_STATE, FAKE_FILES, FILE_CONTENTS)
                conn.sendall(response + prompt())
        except socket.timeout:
            conn.sendall(b"\nSession timeout.\n")
            break
        except Exception:
            break
    conn.close()
    log.info("[BACKDOOR] Shell session ended")


def _handle_shell_cmd(cmd, state, fake_files, file_contents):
    """Process basic shell commands in the simulated root shell."""
    if not cmd:
        return b""
    parts = cmd.split()
    verb  = parts[0].lower()

    if verb == "id":
        return b"uid=0(root) gid=0(root) groups=0(root)\n"

    if verb == "whoami":
        return b"root\n"

    if verb == "hostname":
        return f"{state['hostname']}\n".encode()

    if verb == "uname":
        flags = " ".join(parts[1:])
        if "-a" in flags:
            return b"Linux metasploitable 2.6.24-16-server #1 SMP Thu Apr 10 13:58:00 UTC 2008 i686 GNU/Linux\n"
        return b"Linux\n"

    if verb == "pwd":
        return f"{state['cwd']}\n".encode()

    if verb == "ls":
        target = state["cwd"]
        if len(parts) > 1 and not parts[-1].startswith("-"):
            target = parts[-1]
        entries = fake_files.get(target, [])
        return ("\n".join(entries) + "\n").encode() if entries else b"ls: cannot access: No such file or directory\n"

    if verb == "cd":
        dest = parts[1] if len(parts) > 1 else "/root"
        if dest == "~":
            dest = "/root"
        elif not dest.startswith("/"):
            dest = state["cwd"].rstrip("/") + "/" + dest
        if dest in fake_files or dest == "/root":
            state["cwd"] = dest
            return b""
        return f"bash: cd: {dest}: No such file or directory\n".encode()

    if verb == "cat":
        if len(parts) < 2:
            return b""
        path = parts[1] if parts[1].startswith("/") else state["cwd"].rstrip("/") + "/" + parts[1]
        content = file_contents.get(path)
        if content:
            return content
        return f"cat: {parts[1]}: No such file or directory\n".encode()

    if verb in ("exit", "quit", "logout"):
        return b"logout\n"

    if verb == "ifconfig":
        return (
            b"eth0      Link encap:Ethernet  HWaddr 00:0c:29:xx:xx:xx\n"
            b"          inet addr:192.168.1.100  Bcast:192.168.1.255  Mask:255.255.255.0\n"
            b"          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1\n\n"
        )

    if verb == "ps":
        return (
            b"  PID TTY          TIME CMD\n"
            b"    1 ?        00:00:01 init\n"
            b" 1337 pts/0    00:00:00 vsftpd\n"
            b" 1338 pts/1    00:00:00 sh\n"
        )

    return f"bash: {verb}: command not found\n".encode()


# ══════════════════════════════════════════════
# FTP Session Handler
# ══════════════════════════════════════════════
class FTPSession(threading.Thread):
    def __init__(self, conn: socket.socket, addr: tuple, ftp_root: str):
        super().__init__(daemon=True)
        self.conn      = conn
        self.addr      = addr
        self.ftp_root  = Path(ftp_root)
        self.cwd       = Path("/")
        self.username  = None
        self.logged_in = False
        self.passive_sock = None
        self.data_conn    = None
        self.transfer_type = "A"   # ASCII by default
        self.rename_from   = None

    # ── I/O helpers ───────────────────────────
    def send(self, msg: str):
        log.debug(f"→ {self.addr[0]}  {msg.strip()}")
        try:
            self.conn.sendall((msg + "\r\n").encode())
        except (ConnectionResetError, BrokenPipeError, OSError):
            raise  # let run() handle it

    def recv_line(self) -> str:
        buf = b""
        while True:
            try:
                ch = self.conn.recv(1)
            except (ConnectionResetError, OSError):
                return ""
            if not ch or ch == b"\n":
                break
            if ch != b"\r":
                buf += ch
        line = buf.decode(errors="ignore").strip()
        if line:
            log_line = line if not line.upper().startswith("PASS") else "PASS ****"
            log.debug(f"← {self.addr[0]}  {log_line}")
        return line

    # ── Entry point ───────────────────────────
    def run(self):
        log.info(f"[+] Connection from {self.addr[0]}:{self.addr[1]}")

        # Tune socket: disable Nagle (important for nmap probes),
        # enable keepalive so stale connections get cleaned up.
        try:
            self.conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.conn.setsockopt(socket.SOL_SOCKET,  socket.SO_KEEPALIVE, 1)
            self.conn.settimeout(120)   # 2-min idle timeout per session
        except OSError:
            pass

        try:
            # nmap / scanners sometimes reset immediately after TCP handshake.
            # Catch that silently – it's just a port-open probe, not a real session.
            self.send(BANNER)
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            log.debug(f"[!] {self.addr[0]} dropped before banner (scanner probe): {e}")
            try:
                self.conn.close()
            except Exception:
                pass
            return  # not a real session – exit cleanly

        try:
            while True:
                line = self.recv_line()
                if not line:
                    break
                self._dispatch(line)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        except socket.timeout:
            log.debug(f"[!] {self.addr[0]} session timed out")
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            if self.passive_sock:
                try:
                    self.passive_sock.close()
                except Exception:
                    pass
            log.info(f"[-] Disconnected {self.addr[0]}:{self.addr[1]}")

    # ── Command dispatcher ────────────────────
    def _dispatch(self, line: str):
        parts = line.split(None, 1)
        cmd   = parts[0].upper() if parts else ""
        arg   = parts[1] if len(parts) > 1 else ""

        dispatch = {
            "USER": self._cmd_user,
            "PASS": self._cmd_pass,
            "SYST": self._cmd_syst,
            "FEAT": self._cmd_feat,
            "NOOP": self._cmd_noop,
            "QUIT": self._cmd_quit,
            "PWD":  self._cmd_pwd,
            "CWD":  self._cmd_cwd,
            "CDUP": self._cmd_cdup,
            "TYPE": self._cmd_type,
            "PASV": self._cmd_pasv,
            "LIST": self._cmd_list,
            "NLST": self._cmd_nlst,
            "RETR": self._cmd_retr,
            "STOR": self._cmd_stor,
            "DELE": self._cmd_dele,
            "MKD":  self._cmd_mkd,
            "RMD":  self._cmd_rmd,
            "RNFR": self._cmd_rnfr,
            "RNTO": self._cmd_rnto,
            "SIZE": self._cmd_size,
            "MDTM": self._cmd_mdtm,
            "PORT": self._cmd_port,
            "ABOR": self._cmd_abor,
            "STAT": self._cmd_stat,
        }

        handler = dispatch.get(cmd)
        if handler:
            handler(arg)
        else:
            self.send(f"502 Command not implemented: {cmd}")

    # ── Auth commands ─────────────────────────
    def _cmd_user(self, arg: str):
        self.username  = arg
        self.logged_in = False

        # ══ CVE-2011-2523 BACKDOOR TRIGGER ══
        if ":)" in arg:
            log.critical(
                f"\n{'!'*60}\n"
                f"  CVE-2011-2523 BACKDOOR TRIGGERED!\n"
                f"  Malicious username: {repr(arg)}\n"
                f"  Attacker IP: {self.addr[0]}\n"
                f"{'!'*60}"
            )
            self.send("331 Please specify the password.")
            # Trigger happens on PASS – store flag
            self._backdoor_pending = True
            return

        self._backdoor_pending = False

        if arg.lower() in ("anonymous", "ftp"):
            self.send("331 Please specify the password.")
        elif arg in USERS:
            self.send("331 Please specify the password.")
        else:
            self.send("331 Please specify the password.")

    def _cmd_pass(self, arg: str):
        # ══ CVE-2011-2523 – complete backdoor sequence ══
        if getattr(self, "_backdoor_pending", False):
            self._backdoor_pending = False
            self.send("230 Login successful.")   # some scanners expect 230 first
            # Spawn backdoor in background
            BackdoorServer.trigger(self.addr[0])
            self.logged_in = True
            return

        uname = (self.username or "").lower()

        # Anonymous login (vulnerability: misconfiguration)
        if uname in ("anonymous", "ftp"):
            log.warning(f"[ANON] Anonymous login from {self.addr[0]}")
            self.logged_in = True
            self.send("230 Login successful.")
            return

        # Credential check
        expected = USERS.get(self.username)
        if expected is not None and (expected == "" or expected == arg):
            log.warning(f"[AUTH] Login: user={self.username} pass={arg} from {self.addr[0]}")
            self.logged_in = True
            self.send("230 Login successful.")
        else:
            log.warning(f"[AUTH] Failed login: user={self.username} pass={arg} from {self.addr[0]}")
            self.send("530 Login incorrect.")

    def _require_auth(self) -> bool:
        if not self.logged_in:
            self.send("530 Please login with USER and PASS.")
            return False
        return True

    # ── Info commands ─────────────────────────
    def _cmd_syst(self, _):
        self.send("215 UNIX Type: L8")

    def _cmd_feat(self, _):
        self.send("211-Features:")
        self.send(" PASV")
        self.send(" SIZE")
        self.send(" MDTM")
        self.send("211 End")

    def _cmd_noop(self, _):
        self.send("200 NOOP ok.")

    def _cmd_quit(self, _):
        self.send(GOODBYE)

    def _cmd_stat(self, _):
        self.send(f"211-FTP server status (vsFTPd 2.3.4):")
        self.send(f"     Connected to {self.addr[0]}")
        self.send(f"     Logged in as {self.username or 'nobody'}")
        self.send("211 End of status")

    def _cmd_abor(self, _):
        self.send("226 Abort successful")

    # ── Navigation commands ───────────────────
    def _cmd_pwd(self, _):
        if not self._require_auth(): return
        self.send(f'257 "{self.cwd}" is the current directory')

    def _cmd_cwd(self, arg: str):
        if not self._require_auth(): return
        new_cwd = self._resolve(arg)
        real    = self._real_path(new_cwd)
        if real.is_dir():
            self.cwd = new_cwd
            self.send(f'250 Directory successfully changed.')
        else:
            self.send("550 Failed to change directory.")

    def _cmd_cdup(self, _):
        self._cmd_cwd("..")

    # ── Transfer setup ────────────────────────
    def _cmd_type(self, arg: str):
        if not self._require_auth(): return
        self.transfer_type = arg.upper()
        self.send(f"200 Switching to {'Binary' if 'I' in arg else 'ASCII'} mode.")

    def _cmd_pasv(self, _):
        if not self._require_auth(): return
        if self.passive_sock:
            self.passive_sock.close()
        self.passive_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.passive_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.passive_sock.bind(("0.0.0.0", 0))
        self.passive_sock.listen(1)
        self.passive_sock.settimeout(15)
        _, port = self.passive_sock.getsockname()
        p1, p2  = port >> 8, port & 0xFF
        # Use server IP (127.0.0.1 for local testing)
        ip_parts = "127,0,0,1"
        self.send(f"227 Entering Passive Mode ({ip_parts},{p1},{p2}).")

    def _cmd_port(self, arg: str):
        """Active mode – accept but we won't truly connect back (simplified)."""
        if not self._require_auth(): return
        self.send("200 PORT command successful.")

    def _get_data_conn(self):
        if self.passive_sock:
            try:
                conn, _ = self.passive_sock.accept()
                return conn
            except socket.timeout:
                self.send("425 Failed to establish connection.")
                return None
        return None

    # ── Directory listing ─────────────────────
    def _cmd_list(self, arg: str):
        if not self._require_auth(): return
        self.send("150 Here comes the directory listing.")
        conn = self._get_data_conn()
        if not conn:
            return
        listing = self._build_listing(self.cwd)
        conn.sendall(listing.encode())
        conn.close()
        self.send("226 Directory send OK.")

    def _cmd_nlst(self, arg: str):
        if not self._require_auth(): return
        self.send("150 Here comes the file names.")
        conn = self._get_data_conn()
        if not conn:
            return
        real = self._real_path(self.cwd)
        entries = "\r\n".join(e.name for e in real.iterdir()) if real.is_dir() else ""
        conn.sendall((entries + "\r\n").encode())
        conn.close()
        self.send("226 Directory send OK.")

    def _build_listing(self, vpath: Path) -> str:
        real = self._real_path(vpath)
        lines = []
        now   = datetime.now().strftime("%b %d %H:%M")
        if real.is_dir():
            for entry in sorted(real.iterdir()):
                stat = entry.stat()
                size = stat.st_size
                perm = "drwxr-xr-x" if entry.is_dir() else "-rw-r--r--"
                lines.append(f"{perm}  1 ftp ftp {size:12d} {now} {entry.name}")
        return "\r\n".join(lines) + "\r\n"

    # ── File transfer commands ────────────────
    def _cmd_retr(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        if not path.is_file():
            self.send("550 Failed to open file.")
            return
        self.send(f"150 Opening {self.transfer_type} mode data connection for {arg}.")
        conn = self._get_data_conn()
        if not conn:
            return
        try:
            conn.sendfile(open(path, "rb"))
        finally:
            conn.close()
        self.send("226 Transfer complete.")

    def _cmd_stor(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        self.send(f"150 Ok to send data.")
        conn = self._get_data_conn()
        if not conn:
            return
        try:
            with open(path, "wb") as f:
                while True:
                    chunk = conn.recv(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        finally:
            conn.close()
        log.warning(f"[UPLOAD] {self.username} uploaded {arg}")
        self.send("226 Transfer complete.")

    def _cmd_dele(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        if path.is_file():
            path.unlink()
            self.send(f"250 Delete operation successful.")
        else:
            self.send("550 Delete operation failed.")

    def _cmd_mkd(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        try:
            path.mkdir(parents=True, exist_ok=True)
            self.send(f'257 "{self._resolve(arg)}" created')
        except Exception:
            self.send("550 Create directory operation failed.")

    def _cmd_rmd(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        try:
            import shutil
            shutil.rmtree(str(path))
            self.send("250 Remove directory operation successful.")
        except Exception:
            self.send("550 Remove directory operation failed.")

    def _cmd_rnfr(self, arg: str):
        if not self._require_auth(): return
        self.rename_from = arg
        self.send("350 Ready for RNTO.")

    def _cmd_rnto(self, arg: str):
        if not self._require_auth(): return
        if not self.rename_from:
            self.send("503 RNFR required first.")
            return
        src = self._real_path(self._resolve(self.rename_from))
        dst = self._real_path(self._resolve(arg))
        if src.exists():
            src.rename(dst)
            self.send("250 Rename successful.")
        else:
            self.send("550 Rename failed.")
        self.rename_from = None

    def _cmd_size(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        if path.is_file():
            self.send(f"213 {path.stat().st_size}")
        else:
            self.send("550 Could not get file size.")

    def _cmd_mdtm(self, arg: str):
        if not self._require_auth(): return
        path = self._real_path(self._resolve(arg))
        if path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            self.send(f"213 {mtime.strftime('%Y%m%d%H%M%S')}")
        else:
            self.send("550 Could not get file modification time.")

    # ── Path helpers ──────────────────────────
    def _resolve(self, arg: str) -> Path:
        arg = arg.strip()
        if not arg or arg == ".":
            return self.cwd
        if arg.startswith("/"):
            new = Path(arg)
        else:
            new = self.cwd / arg
        try:
            # Normalise without resolving symlinks (virtual FS)
            parts = []
            for p in new.parts:
                if p == "..":
                    if parts and parts[-1] != "/":
                        parts.pop()
                elif p != ".":
                    parts.append(p)
            return Path(*parts) if parts else Path("/")
        except Exception:
            return self.cwd

    def _real_path(self, vpath: Path) -> Path:
        rel = str(vpath).lstrip("/")
        return self.ftp_root / rel if rel else self.ftp_root


# ══════════════════════════════════════════════
# Main FTP Server
# ══════════════════════════════════════════════
class VulnerableFTPServer:
    def __init__(self, host="0.0.0.0", port=21, ftp_root="/tmp/ftp_root"):
        self.host     = host
        self.port     = port
        self.ftp_root = ftp_root
        self._setup_root()

    def _setup_root(self):
        root = Path(self.ftp_root)
        (root / "pub").mkdir(parents=True, exist_ok=True)
        (root / "incoming").mkdir(parents=True, exist_ok=True)
        readme = root / "pub" / "readme"
        if not readme.exists():
            readme.write_text("Welcome to Metasploitable 2 FTP\n")
        log.info(f"[*] FTP root: {root.resolve()}")

    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(20)

        print(self._banner())
        log.info(f"[*] vsftpd 2.3.4 (vulnerable) listening on {self.host}:{self.port}")
        log.info(f"[*] Backdoor port: {BACKDOOR_PORT}")

        while True:
            try:
                conn, addr = srv.accept()
                FTPSession(conn, addr, self.ftp_root).start()
            except KeyboardInterrupt:
                log.info("\n[!] Shutting down...")
                break
            except Exception as e:
                log.error(f"Accept error: {e}")

    @staticmethod
    def _banner():
        return f"""
╔══════════════════════════════════════════════════════════════════╗
║          vsftpd 2.3.4 — Vulnerable FTP Server (Lab)              ║
║                  Metasploitable 2 Simulator                      ║
╠══════════════════════════════════════════════════════════════════╣
║  ⚠  FOR EDUCATIONAL / CTF / PENTEST LAB USE ONLY                 ║
╠══════════════════════════════════════════════════════════════════╣
║  Vulnerabilities simulated:                                      ║
║  • CVE-2011-2523  vsftpd 2.3.4 Backdoor (USER with :)            ║
║    → Opens root shell on port {BACKDOOR_PORT}                    ║
║  • Anonymous FTP login enabled (misconfiguration)                ║
║  • Weak / default credentials (msfadmin:msfadmin, etc.)          ║
║  • Cleartext authentication (no TLS)                             ║
╠══════════════════════════════════════════════════════════════════╣
║  THIS CTF CREATED VIA "https://zerobyte.dev-core.site"           ║
╚══════════════════════════════════════════════════════════════════╝"""


# ══════════════════════════════════════════════
# CLI Entry point
# ══════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Metasploitable 2 vsftpd 2.3.4 vulnerable FTP server (educational)"
    )
    parser.add_argument("--host",  default="0.0.0.0",       help="Bind address")
    parser.add_argument("--port",  default=21,   type=int,   help="FTP port (default 21)")
    parser.add_argument("--root",  default="/tmp/ftp_root",  help="FTP root directory")
    parser.add_argument("--debug", action="store_true",      help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.port < 1024 and os.geteuid() != 0:
        print("[!] Port < 1024 requires root. Run with sudo or use --port 2121")
        sys.exit(1)

    VulnerableFTPServer(args.host, args.port, args.root).serve_forever()


if __name__ == "__main__":
    main()
