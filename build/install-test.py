#!/usr/bin/env python3
"""Install a Samurai Linux ISO into a blank QEMU disk and boot the result.

The live image has no Calamares batch mode, so this driver:
  1. boots the ISO with a blank disk and a serial console,
  2. logs in on ttyS0, becomes root, and starts Calamares on the live desktop,
  3. drives Calamares through VNC with a small amount of OCR-based state
     detection, and
  4. boots from the installed disk and verifies it over the serial console.

It is intentionally boring: every UI action is logged, every screenshot is
kept as a CI artifact, and a failure leaves enough evidence to debug it.

Run ``python3 build/install-test.py --self-test`` to exercise the serial
console logic without QEMU.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import posixpath
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
LOG_BEGIN = "__SAMURAI_LOG_BEGIN__"
LOG_END = "__SAMURAI_LOG_END__"

# OCR of Calamares' own words, lowercased and with the whitespace collapsed.
FINISHED_WORDS = (
    "all done",
    "installation complete",
    "installation finished",
    "install complete",
    "install finished",
    "your new system",
    "restart now",
    "reboot now",
)
CRASH_WORDS = (
    "closed unexpectedly",
    "crash handler",
    "segmentation fault",
    "calamares closed",
)

# Where the installer is started from, inside the guest.
CALAMARES_LAUNCHER_PATH = "/tmp/samurai-calamares-session.sh"

# Calamares' first partitioning job asks KDE's kded for the automount setting,
# and every run so far segfaulted inside that call: with no session bus at all
# (runs 41802792291, 41830599254, after "Not connected to D-Bus server"), and
# with a private bus whose D-Bus daemon had to cold-start kded6 while Calamares
# sat blocked on it (runs 41833873221, 41892892060, 41984807632 - "Activating
# service name='org.kde.kded6'", then "Signal: Segmentation fault (11)" one
# second later). Leaving Debian's own partition.conf in place changed nothing,
# so this is the call, not the config. Nobody can reproduce it from a real
# desktop: a user starts the installer from Plasma, where kded has owned its bus
# name since login and the call is answered by a running daemon instead of being
# activated mid-flight from a worker thread. So give the installer the session it
# would have in use - join the live session's own bus when root may use it, and
# otherwise start kded first and wait for it to register before Calamares asks it
# anything. Each SAMURAI_* line says what the launcher found, because "it
# crashed again" and "it crashed for the same reason" are different failures.
CALAMARES_LAUNCHER = r"""#!/bin/sh
# Written by build/install-test.py; run under dbus-run-session.
echo "SAMURAI_SESSION_PROCS=$(ps -u samurai -o comm= 2>/dev/null | sort -u | tr '\n' ' ')"
[ -S /run/user/1000/bus ] && echo "SAMURAI_USERBUS_FILE=$(DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus busctl --no-pager --user list 2>&1 | head -n 1)"

# The address a session really answers on comes from the session's own
# processes: run 41984807632 named a Plasma desktop (kwin_wayland, ksplashqml
# and a dbus-daemon, all owned by samurai) while /run/user/1000/bus said
# "Transport endpoint is not connected", so that socket was not the live bus.
busaddr=
for pid in $(pgrep -u samurai -x dbus-daemon 2>/dev/null) $(pgrep -u samurai -x plasmashell 2>/dev/null) \
        $(pgrep -u samurai -x kwin_x11 2>/dev/null) $(pgrep -u samurai -x kwin_wayland 2>/dev/null); do
    candidate=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' | head -n 1)
    [ -z "$candidate" ] && continue
    if DBUS_SESSION_BUS_ADDRESS="$candidate" busctl --no-pager --user list >/dev/null 2>&1; then
        busaddr=$candidate
        echo "SAMURAI_SESSION_BUS=pid=$pid reachable"
        break
    fi
    echo "SAMURAI_SESSION_BUS=pid=$pid refused: $(DBUS_SESSION_BUS_ADDRESS="$candidate" busctl --no-pager --user list 2>&1 | head -n 1)"
done
if [ -n "$busaddr" ]; then
    DBUS_SESSION_BUS_ADDRESS="$busaddr"
    export DBUS_SESSION_BUS_ADDRESS
    echo "SAMURAI_DBUS=session"
else
    echo SAMURAI_DBUS=private
fi

kded=
for candidate in /usr/bin/kded6 /usr/bin/kded5; do
    [ -x "$candidate" ] && kded=$candidate && break
done
case "${kded##*/}" in
    kded5) kdedname=org.kde.kded5 ;;
    *) kdedname=org.kde.kded6 ;;
esac
echo "SAMURAI_KDED=${kded:-absent} name=$kdedname owners=$(busctl --no-pager list 2>/dev/null | grep -c 'org\.kde\.kded')"

# kded is only ever started on a bus of our own: on the desktop's bus its
# absence is that desktop's business, not something to fix with a root daemon.
if [ -z "$busaddr" ] && [ -n "$kded" ] \
        && ! busctl --no-pager list 2>/dev/null | grep -q "$kdedname"; then
    [ -d /run/user/0 ] || install -d -m 0700 /run/user/0
    # kded is a Qt application and aborts (exit 134, "Available platform plugins
    # are: ...") when it is started as root with no display to open, which is what
    # run 41991858787 recorded as "alive=no" after one second. It needs no window
    # to answer a D-Bus call, so give it the offscreen platform.
    HOME=/root XDG_RUNTIME_DIR=/run/user/0 QT_QPA_PLATFORM=offscreen \
        "$kded" >/tmp/kded.out 2>&1 &
    kdedpid=$!
    polls=0
    while [ "$polls" -lt 60 ]; do
        busctl --no-pager list 2>/dev/null | grep -q "$kdedname" && break
        kill -0 "$kdedpid" 2>/dev/null || break
        sleep 0.5
        polls=$((polls + 1))
    done
    echo "SAMURAI_KDED_STARTED=pid=$kdedpid after_halves=$polls owners=$(busctl --no-pager list 2>/dev/null | grep -c 'org\.kde\.kded') alive=$(kill -0 "$kdedpid" 2>/dev/null && echo yes || echo no)"
    echo "SAMURAI_KDED_TAIL=$(tail -n 2 /tmp/kded.out 2>/dev/null | tr '\n' '|')"
fi

echo "SAMURAI_AUTOMOUNT_PROBE=$(busctl --no-pager call "$kdedname" /kded "$kdedname" isModuleAutoloaded s device_automounter 2>&1 | head -n 1)"
echo SAMURAI_LAUNCH=calamares
exec calamares -d
"""


class Failure(RuntimeError):
    pass


def _is_hex(token: str) -> bool:
    try:
        int(token, 16)
    except ValueError:
        return False
    return True


def renderer_problem(session_type: str, glx: str, egl: str) -> str | None:
    """Say what keeps this session from compositing, or None when it can.

    glxinfo reaches OpenGL through an X server. The installed image logs into
    Plasma's Wayland session even when the test-only autologin names plasmax11,
    so asking glxinfo there fails with "unable to open display :0" while Mesa is
    present and working - which is how run 42129297987 reported a missing DRI
    driver on an image whose eglinfo named kms_swrast. On Wayland the same
    question is answered over EGL, the path KWin itself uses.
    """
    if session_type.lower() == "wayland":
        if "Mesa" not in egl:
            return "the Wayland session reports no Mesa EGL vendor, so KWin cannot composite"
        if "EGL driver name:" not in egl:
            return "the Wayland session created no EGL driver, so the image has no usable Mesa DRI driver"
        return None
    # `glxinfo -B` prints Mesa's extended block - "Extended renderer info
    # (GLX_MESA_query_renderer)" with a "Device:" line - and not the classic
    # "OpenGL renderer string" line that the full listing prints. Run
    # 42381460039 failed here on an image whose brief output named
    # "Device: llvmpipe (LLVM 19.1.7, 256 bits)": the probe looked only for
    # the full-listing label and called a working Mesa stack missing.
    if "OpenGL renderer string" in glx or "Device:" in glx:
        return None
    return "the X11 session has no OpenGL renderer, so the image has no Mesa DRI driver"


class Log:
    def __init__(self, path: Path):
        self.path = path
        self._fh = path.open("w", encoding="utf-8", errors="replace")

    def __call__(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def run(cmd: list[str], *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise Failure(f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stdout}")
    return result


class SerialConsole:
    """A bidirectional connection to QEMU's unix serial chardev."""

    def __init__(
        self,
        transcript: Path,
        log: Log,
        *,
        path: Path | None = None,
        sock: socket.socket | None = None,
    ):
        self.path = path
        self.log = log
        self.buffer = ""
        self.raw = ""
        self.counter = 0
        self.eof = False
        self._fh = transcript.open("w", encoding="utf-8", errors="replace")
        if sock is None:
            if path is None:
                raise ValueError("SerialConsole needs a path or a connected socket")
            sock = self._connect(path)
        self.sock = sock
        self.sock.setblocking(False)

    @staticmethod
    def _connect(path: Path) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.time() + 30
        while True:
            try:
                sock.connect(str(path))
                return sock
            except OSError:
                if time.time() > deadline:
                    sock.close()
                    raise
                time.sleep(0.5)

    def close(self) -> None:
        try:
            self.sock.close()
        finally:
            self._fh.close()

    def _read(self) -> None:
        while True:
            try:
                chunk = self.sock.recv(65536)
            except BlockingIOError:
                return
            except OSError:
                self.eof = True
                return
            if not chunk:
                self.eof = True
                return
            text = chunk.decode("utf-8", errors="replace")
            self.buffer += text
            self.raw += text
            self._fh.write(text)
            self._fh.flush()
            if len(self.raw) > 200_000:
                self.raw = self.raw[-100_000:]
            if len(self.buffer) > 1_000_000:
                # Boot logs can be long; keep enough tail for diagnosis.
                self.buffer = self.buffer[-500_000:]

    def send(self, text: str) -> None:
        try:
            self.sock.sendall(text.encode("utf-8"))
        except OSError as exc:
            raise Failure(f"could not write to the serial console: {exc}") from exc

    def sendline(self, line: str = "") -> None:
        self.send(line + "\r")

    def raw_tail(self, size: int = 300) -> str:
        """End of the serial stream, control characters and all.

        ``expect()`` strips ANSI and consumes what it matched, so by the time a
        prompt fails the whitespace that caused it is gone from ``buffer``. This
        is the unedited record of what the guest wrote.
        """
        return self.raw[-size:]

    def expect(self, pattern: str, timeout: float, label: str) -> tuple[str, re.Match[str]]:
        """Wait for a pattern and return (output-before-match, match).

        The returned output is what the guest printed before the match; it is
        deliberately not discarded so callers (``command``) can use it.
        """
        rx = re.compile(pattern, re.S | re.M)
        deadline = time.time() + timeout
        while True:
            self._read()
            match = rx.search(self.buffer)
            if match:
                output = ANSI_RE.sub("", self.buffer[: match.start()])
                self.buffer = self.buffer[match.end() :]
                return output, match
            if self.eof:
                tail = ANSI_RE.sub("", self.buffer)[-2000:]
                raise Failure(f"serial connection closed while waiting for {label}; tail:\n{tail}")
            if time.time() > deadline:
                tail = ANSI_RE.sub("", self.buffer)[-2000:]
                raise Failure(f"timed out waiting for {label}; serial tail:\n{tail}")
            time.sleep(0.2)

    def wait_for_text(self, pattern: str, timeout: float, label: str) -> str:
        return self.expect(pattern, timeout, label)[0]

    def _login_prompt(self, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            # agetty's prompt may have been printed before this socket connected,
            # so a newline makes it print a fresh one.
            self.sendline()
            try:
                self.expect(r"login: ", 8, "serial login prompt")
                return
            except Failure:
                if time.time() > deadline:
                    break
                continue
        tail = ANSI_RE.sub("", self.buffer)[-2000:]
        raise Failure(f"the serial console never showed a login prompt; tail:\n{tail}")

    def login(self, username: str, password: str, timeout: float = 420) -> None:
        self.log("waiting for the serial login prompt")
        self._login_prompt(timeout)
        self.sendline(username)
        self.expect(r"Password:", 30, "serial password prompt")
        self.sendline(password)
        self.expect(r"[$#] ", 60, "serial user shell")
        self.log("logged in on the serial console")

    def root_shell(self, password: str = "live", timeout: float = 120) -> None:
        """Start ``sudo -i`` without blocking command() on an interactive shell.

        sudo calls tcsetattr(TCSAFLUSH) when it starts, so anything typed in
        the instant between its prompt appearing and it reading the terminal is
        discarded - with no error, it just waits.  Pause before typing, and
        retry in case an attempt is still swallowed.
        """
        self.log("opening a root shell with sudo -i")
        self.sendline("sudo -i")
        # sudo prints "[sudo] password for user: ", not a bare "password:", and
        # the trailing space is not guaranteed to arrive with the prompt, so any
        # whitespace after the colon counts.
        prompt = r"[Pp]assword[^\r\n:]*:\s|root@[^\s:]+:[^\r\n]*# "
        try:
            _, match = self.expect(prompt, timeout, "root shell")
            for attempt in range(1, 4):
                if "root@" in match.group(0):
                    break
                time.sleep(2 * attempt)
                self.log(f"typing the password for sudo (attempt {attempt})")
                self.sendline(password)
                _, match = self.expect(prompt, 60, "root shell")
            if "root@" not in match.group(0):
                raise Failure(f"sudo -i never gave a root shell (last output {match.group(0)!r})")
        except Failure as exc:
            # expect() prints a trimmed tail; the whitespace sudo actually wrote is
            # what tells you why a prompt failed to match.
            raise Failure(f"{exc}\nraw serial bytes: {self.raw_tail()!r}") from exc
        uid = self.command("id -u", timeout=30)
        if uid.strip() != "0":
            raise Failure(f"sudo -i did not give a root shell (id -u = {uid!r})")
        self.command("cd /", timeout=30)
        self.log("root shell is ready")

    def background(self, command: str, timeout: float = 30) -> int:
        """Start a command in the background and return its shell PID.

        ``command()`` cannot be used for this: appending ``; echo ...`` after a
        trailing ``&`` is a shell syntax error.
        """
        marker = f"__SAMURAI_DONE_{self.counter}_{os.getpid()}__"
        self.counter += 1
        self.sendline(f"( {command} ) & echo {marker}:$!")
        _, match = self.expect(
            re.escape(marker) + r":([0-9]+)", timeout, f"background: {command}"
        )
        pid = int(match.group(1))
        self.log(f"started in the background (pid {pid}): {command}")
        return pid

    def command(self, command: str, timeout: float = 60, check: bool = True) -> str:
        if command.rstrip().endswith("&"):
            raise Failure("use background() for a command that ends with '&'")
        marker = f"__SAMURAI_DONE_{self.counter}_{os.getpid()}__"
        self.counter += 1
        begin = f"{marker}.BEGIN"
        self.sendline(f"echo {begin}; {command}; echo {marker}.END:$?")
        output, match = self.expect(
            re.escape(marker) + r"\.END:([0-9]+)", timeout, f"command: {command}"
        )
        status = int(match.group(1))
        # expect() removes ANSI, but a command line that fills the 80-column
        # console makes readline redraw it and the redraw leaves real characters
        # behind - a stray '?' cost run 16 a false "no /home/samurai" failure on
        # a system that was fine. So the value is read from after the BEGIN the
        # shell printed, never from the whole exchange.
        anchor = output.rfind(begin)
        if anchor < 0:
            output = "\n".join(line for line in output.splitlines() if marker not in line)
        else:
            output = output[anchor + len(begin) :]
        clean = output.strip()
        self.log(f"serial: {command} -> {status}")
        if clean:
            self.log("serial output:\n" + clean[-4000:])
        if check and status != 0:
            raise Failure(f"serial command failed ({status}): {command}\n{clean}")
        return clean

    def write_file(self, path: str, content: str, chunk_size: int = 3000) -> None:
        """Write a guest file without fighting the serial line's quoting rules.

        The tty line discipline ends a canonical line at 4096 bytes, so a long
        payload cannot be typed as one line: it is staged in a base64 side file
        and decoded only once every piece has landed.
        """
        payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
        target = shlex.quote(path)
        if len(payload) <= chunk_size:
            self.command(f"printf %s {shlex.quote(payload)} | base64 -d > {target}", timeout=60)
            return
        staged = target + ".b64"
        self.command(f": > {staged}", timeout=30)
        for start in range(0, len(payload), chunk_size):
            piece = shlex.quote(payload[start : start + chunk_size])
            self.command(f"printf %s {piece} >> {staged}", timeout=60)
        self.command(f"base64 -d {staged} > {target} && rm -f {staged}", timeout=60)

    def pull_file(self, path: str, label: str, timeout: float = 240) -> bytes:
        """Copy a guest file back over the serial line, byte for byte.

        Reading the file plainly would wrap it at 80 columns and lose the
        spacing that makes a report readable, so it travels base64-encoded.
        """
        self.sendline(
            f"echo {LOG_BEGIN}; base64 -w0 {shlex.quote(path)} 2>/dev/null; echo; echo {LOG_END}"
        )
        output, _ = self.expect(r"\r?\n" + LOG_END + r"\r?\n", timeout, label)
        if LOG_BEGIN not in output:
            return b""
        payload = re.sub(r"[^A-Za-z0-9+/=]", "", output.rsplit(LOG_BEGIN, 1)[1])
        if not payload:
            return b""
        try:
            return base64.b64decode(payload)
        except (ValueError, binascii.Error):
            self.log(f"{label}: the base64 payload was corrupted in transit")
            return b""


class VNC:
    """Drive the QEMU VNC display with vncdo."""

    def __init__(self, server: str, artifact_dir: Path, log: Log):
        self.server = server
        self.artifact_dir = artifact_dir
        self.log = log
        self._captures = 0

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        last: subprocess.CompletedProcess | None = None
        for attempt in range(3):
            try:
                last = run(["vncdo", "-s", self.server, *map(str, args)], timeout=timeout)
                return last
            except (Failure, subprocess.TimeoutExpired) as exc:
                self.log(f"vncdo attempt {attempt + 1} failed: {exc}")
                time.sleep(2)
        raise Failure(
            f"vncdo failed: {' '.join(map(str, args))}\n{getattr(last, 'stdout', '')}"
        )

    def key(self, key: str) -> None:
        self.log(f"vnc: key {key}")
        self._run("key", key)

    def type(self, text: str) -> None:
        self.log(f"vnc: type {text!r}")
        self._run("type", text)

    def click(self, x: int, y: int) -> None:
        self.log(f"vnc: click {x},{y}")
        # QEMU's PS/2 pointer is relative; with usb-tablet the move is
        # absolute. The pause also lets X update the pointer before the
        # button event, which otherwise lands at the previous position.
        self._run("move", str(x), str(y), "pause", "0.3", "click", "1")

    def capture(self, name: str) -> Path:
        self._captures += 1
        path = self.artifact_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run("capture", str(path))
        return path

    def wake(self) -> None:
        """Nudge the pointer so an idle-blanked live desktop comes back.

        The Plasma session screens out after a few minutes with no input, and
        QEMU keeps serving the black frame, which would make every later
        capture useless.
        """
        try:
            self._run("move", "200", "200", "pause", "0.2", "move", "220", "210")
        except Failure as exc:
            self.log(f"could not wake the display: {exc}")

    def stable_capture(self, name: str, quiet: float = 0.8, attempts: int = 6) -> Path:
        """Capture until two consecutive frames are byte-identical.

        vncdotool has no 'stable' command; polling in the driver keeps the
        dependency on its documented commands only.
        """
        path = self.artifact_dir / name
        previous: bytes | None = None
        for _ in range(attempts):
            self.capture(name)
            data = path.read_bytes()
            if data == previous:
                return path
            previous = data
            time.sleep(quiet)
        return path


class OCR:
    """Tesseract with a small amount of preprocessing for 1024x768 screens."""

    SCALE = 2

    def __init__(self, artifact_dir: Path, log: Log):
        self.artifact_dir = artifact_dir
        self.log = log
        self._prepared_dir = artifact_dir / "ocr"
        self._prepared_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[tuple[str, int, int, int], str] = {}
        self._warned = False

    def _prepare(self, image: Path) -> tuple[Path, int]:
        try:
            from PIL import Image, ImageOps
        except ImportError:
            if not self._warned:
                self.log("Pillow is not installed; OCR runs on the raw screenshot")
                self._warned = True
            return image, 1

        prepared = self._prepared_dir / f"{image.stem}-ocr.png"
        with Image.open(image) as im:
            im = im.convert("L")
            im = ImageOps.autocontrast(im)
            resample = getattr(Image, "Resampling", Image).LANCZOS
            im = im.resize((im.width * self.SCALE, im.height * self.SCALE), resample)
            im.save(prepared)
        return prepared, self.SCALE

    def text(self, image: Path, psm: int = 11) -> str:
        stat = image.stat()
        key = (str(image), psm, stat.st_mtime_ns, stat.st_size)
        if key in self._cache:
            return self._cache[key]
        prepared, _ = self._prepare(image)
        result = run(
            ["tesseract", str(prepared), "stdout", "--psm", str(psm)],
            check=False,
            timeout=120,
        )
        text = result.stdout or ""
        self._cache[key] = text
        return text

    def words(self, image: Path, psm: int = 11) -> list[dict]:
        prepared, scale = self._prepare(image)
        result = run(
            ["tesseract", str(prepared), "stdout", "--psm", str(psm), "tsv"],
            check=False,
            timeout=120,
        )
        words = []
        for line in (result.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 12 or parts[0] != "5":
                continue
            try:
                conf = float(parts[10])
                left, top, width, height = (int(parts[i]) for i in range(6, 10))
            except ValueError:
                continue
            value = parts[11].strip()
            if value and conf >= 35:
                words.append(
                    {
                        "text": value,
                        "left": left // scale,
                        "top": top // scale,
                        "width": width // scale,
                        "height": height // scale,
                        "conf": conf,
                    }
                )
        return words


class InstallerTest:
    def __init__(self, args: argparse.Namespace):
        self.iso = Path(args.iso).resolve()
        self.work = Path(args.work_dir).resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.log = Log(self.work / "driver.log")
        self.ocr = OCR(self.work, self.log)
        self.vnc_server = f"127.0.0.1::{args.vnc_port}"
        self.vnc = VNC(self.vnc_server, self.work, self.log)
        self.disk = self.work / "disk.qcow2"
        self.install_serial = self.work / "install-serial.log"
        self.qemu: subprocess.Popen | None = None
        self.qemu_log: Path | None = None
        self.serial: SerialConsole | None = None
        self.timeout = args.timeout
        self.disk_size = args.disk_size
        self.vnc_display = args.vnc_port - 5900
        self.reboot_timeout = args.reboot_timeout
        self.password = args.password
        self.branded = args.branded
        self.desktop = args.desktop
        self.desktop_session = args.desktop_session
        self.session_env: dict[str, str] = {}
        self.x_display = ":0"
        self.root_ready = False
        self.log_copied = False
        if not 1 <= self.vnc_display <= 99:
            raise Failure(f"VNC port must be between 5901 and 5999, got {args.vnc_port}")

    # -- QEMU ---------------------------------------------------------

    def _qemu_base(self) -> list[str]:
        args = [
            "qemu-system-x86_64",
            "-name",
            "Samurai Linux install test",
            "-m",
            "4096",
            "-smp",
            "4",
            "-display",
            f"vnc=127.0.0.1:{self.vnc_display}",
            # KWin under -vga std has no real DRM device and dies when Calamares
            # paints its QML partition preview, taking XWayland and the installer
            # with it (runs 41545976827 and 41596964514, both at the same step).
            # virtio-gpu gives the guest a KMS driver, which is what Plasma
            # expects; the VNC server mirrors it the same way.
            "-vga",
            "virtio",
            "-usb",
            "-device",
            "usb-tablet",
            "-monitor",
            "none",
            "-no-reboot",
            "-rtc",
            "base=utc",
        ]
        if os.access("/dev/kvm", os.W_OK):
            args += ["-enable-kvm", "-cpu", "host"]
        else:
            args += ["-accel", "tcg,thread=multi", "-cpu", "max"]
        return args

    def _start_vm(self, extra: list[str], serial_sock: Path, qemu_log: Path) -> None:
        cmd = self._qemu_base() + extra
        serial_sock.unlink(missing_ok=True)
        self.qemu_log = qemu_log
        with qemu_log.open("w", encoding="utf-8") as fh:
            self.log("starting VM: " + " ".join(cmd))
            self.qemu = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
        for _ in range(120):
            if serial_sock.exists():
                break
            if self.qemu.poll() is not None:
                raise Failure(f"QEMU exited before the serial socket appeared; see {qemu_log}")
            time.sleep(0.5)
        else:
            raise Failure("QEMU did not create the serial socket")

    def start_install_vm(self) -> None:
        self.disk.unlink(missing_ok=True)
        run(["qemu-img", "create", "-f", "qcow2", str(self.disk), self.disk_size])
        serial_sock = self.work / "serial-install.sock"
        self._start_vm(
            [
                "-drive",
                f"file={self.disk},format=qcow2,if=ide,cache=writeback",
                "-cdrom",
                str(self.iso),
                "-boot",
                "d",
                "-serial",
                f"unix:{serial_sock},server=on,wait=off",
                "-net",
                "none",
            ],
            serial_sock,
            self.work / "qemu-install.log",
        )
        self.serial = SerialConsole(self.install_serial, self.log, path=serial_sock)

    def start_reboot_vm(self, name: str = "installed") -> None:
        serial_sock = self.work / f"serial-{name}.sock"
        self._start_vm(
            [
                "-drive",
                f"file={self.disk},format=qcow2,if=ide,cache=writeback",
                "-boot",
                "c",
                "-serial",
                f"unix:{serial_sock},server=on,wait=off",
                "-net",
                "none",
            ],
            serial_sock,
            self.work / f"qemu-{name}.log",
        )
        self.serial = SerialConsole(self.work / f"{name}-serial.log", self.log, path=serial_sock)

    def stop_vm(self) -> None:
        if self.serial:
            self.serial.close()
            self.serial = None
        if self.qemu and self.qemu.poll() is None:
            self.qemu.terminate()
            try:
                self.qemu.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.qemu.kill()
                self.qemu.wait()
        self.qemu = None

    def wait_for_guest_exit(self, timeout: int = 180) -> None:
        if not self.qemu:
            return
        try:
            self.qemu.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.log("guest did not power off; terminating QEMU")

    # -- OCR helpers ---------------------------------------------------

    def ocr_text(self, image: Path) -> str:
        return self.ocr.text(image)

    def dismiss_welcome(self) -> None:
        """Close Plasma's first-run Welcome Center if it is running.

        It opens on top of Calamares and takes the keyboard focus, so leaving
        it up makes both OCR and clicks unreliable.
        """
        if not self.serial:
            return
        self.serial.command(
            "pkill -x plasma-welcome >/dev/null 2>&1 || true; "
            "pkill -f '/usr/bin/plasma-welcome' >/dev/null 2>&1 || true; "
            "pkill -x kde-welcome >/dev/null 2>&1 || true; "
            "true",
            timeout=30,
            check=False,
        )

    def wait_for(
        self,
        needles: str | tuple[str, ...],
        label: str,
        timeout: float,
        screenshot: str,
        *,
        dismiss_welcome: bool = False,
        watch: tuple[str, str] | None = None,
    ) -> Path:
        if isinstance(needles, str):
            needles = (needles,)
        needles = tuple(needle.lower() for needle in needles)
        deadline = time.time() + timeout
        last_text = ""
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            if dismiss_welcome:
                self.dismiss_welcome()
            image = self.vnc.stable_capture(f"{screenshot}-{attempt:02d}.png")
            text = self.ocr_text(image)
            last_text = text
            normalized = re.sub(r"\s+", " ", text.lower())
            self.log(f"OCR {label} attempt {attempt}: {normalized[:200]!r}")
            if any(needle in normalized for needle in needles):
                self.log(f"detected {label!r}")
                return self.vnc.stable_capture(f"{screenshot}.png")
            if "installation failed" in normalized or "installer failed" in normalized:
                raise Failure(f"Calamares reported a failure while waiting for {label}; see {image}")
            # A process that died is not going to paint the page being waited
            # for, and OCR of the desktop says nothing about why.  Its own log
            # does, so a crash fails here with that output instead of burning
            # the whole timeout and reporting pixels.
            if watch is not None and self.serial is not None and attempt % 3 == 0:
                process, logfile = watch
                state = self.serial.command(
                    f"pgrep -x {process} >/dev/null && echo yes || echo no", timeout=30
                )
                if state.strip() != "yes":
                    output = self.serial.command(
                        f"tail -n 200 {logfile} 2>/dev/null || true", timeout=60
                    )
                    # The display server dying takes Calamares and KWin with it.
                    # Depending on the session there may be no Xorg log at all, so
                    # read the compositor's own session log, the journal and any
                    # coredump: those record the crash either way.
                    display = self.serial.command(
                        'dmesg | tail -n 30; free -m | head -n 3; '
                        'for f in /var/log/Xorg.0.log /run/sddm/xorg.log '
                        '/root/.local/share/sddm/*session.log '
                        '/home/*/.local/share/sddm/*session.log; do '
                        'if [ -r "$f" ]; then echo "--- $f"; tail -n 40 "$f"; fi; done; true',
                        timeout=90,
                    )
                    session = self.serial.command(
                        'journalctl -b --no-pager 2>&1 | grep -iE "kwin|sddm|coredump|oom|'
                        'out of memory|drm" | tail -n 60; '
                        'command -v coredumpctl >/dev/null && '
                        'coredumpctl list --no-pager 2>&1 | tail -n 8; '
                        # The list says which binary died; only the backtrace says
                        # whether it was the compositor or the installer. Run
                        # 41989352435 had frames from libkwin.so.6 and a Calamares
                        # process that was alive until its X connection broke.
                        'command -v coredumpctl >/dev/null && '
                        'coredumpctl info --no-pager 2>&1 | '
                        'grep -E "^(Executable|Signal|Command|#[0-9]+)" | tail -n 25; true',
                        timeout=120,
                    )
                    self.vnc.capture(f"{screenshot}-process-gone.png")
                    raise Failure(
                        f"{process} exited while waiting for {label}; tail of {logfile}:\n"
                        f"{output[-4000:]}\n"
                        f"display server evidence:\n{display[-3000:]}\n"
                        f"session evidence:\n{session[-3000:]}"
                    )
            time.sleep(4)
        self.vnc.capture(f"{screenshot}-timeout.png")
        raise Failure(
            f"timed out waiting for {label} {needles!r}; last OCR text:\n{last_text[-3000:]}"
        )

    @staticmethod
    def png_size(path: Path) -> tuple[int, int]:
        head = path.read_bytes()[:33]
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            raise Failure(f"{path} is not a screenshot")
        return struct.unpack(">II", head[16:24])

    def click_word(self, word: str, min_top_ratio: float = 0.65) -> bool:
        """Click a matching word in the lower part of the screen.

        The button row is the lowest text on a Calamares page, so the lowest
        match is the button. A band of the last 12% was too tight: on the
        1280x800 framebuffer this test uses, the word "Next" starts at y=699
        and the band began at y=704, so the search failed and the fallback
        switched Calamares' UI language instead (run 42296526484).
        """
        image = self.vnc.stable_capture("lookup.png")
        _, height = self.png_size(image)
        band = height * min_top_ratio
        matches = [
            item
            for item in self.ocr.words(image)
            if word.lower() in item["text"].lower() and item["top"] >= band
        ]
        if not matches:
            return False
        target = max(matches, key=lambda item: item["top"])
        x = target["left"] + target["width"] // 2
        y = target["top"] + target["height"] // 2
        self.vnc.click(x, y)
        return True

    def click_primary_button(self) -> None:
        """Click Calamares' bottom-right primary button by geometry.

        Used only when the word search has no effect. Calamares opens a
        1024x648 window centred on the screen, and the primary button sits
        143 px left of and 14 px above its bottom-right corner. The old
        fixed ``height - 80`` landed one pixel below the button on the
        1280x800 framebuffer (y=720 against a button ending at 719), so the
        click was swallowed. The window geometry keeps this correct on the
        1024x768 screens the OCR class also mentions.
        """
        image = self.vnc.capture("primary-button.png")
        width, height = self.png_size(image)
        x = (width + 1024) // 2 - 143
        y = (height + 648) // 2 - 14
        self.log(f"clicking the primary button at {x},{y} (screen {width}x{height})")
        self.vnc.click(x, y)

    def page_signature(self, text: str) -> frozenset[str]:
        """The words OCR can see, for telling one Calamares page from another."""
        return frozenset(word for word in re.findall(r"[a-z]{3,}", text.lower()))

    def advance(
        self,
        needle: str | tuple[str, ...],
        label: str,
        timeout: float,
        screenshot: str,
    ) -> None:
        # A click can be swallowed: Calamares spends the first seconds after the
        # welcome page loading the partition module and running os-prober, and a
        # click that lands in that window does nothing at all (run 41604632927
        # sat on Welcome for its whole 90-second locale timeout). Retrying blind
        # is the other failure: a second click that lands after the page has
        # already changed skips a step. So a retry happens only when the screen
        # still shows the page the click was aimed at.
        if isinstance(needle, str):
            needles = (needle,)
        else:
            needles = tuple(needle)
        before = self.page_signature(self.ocr_text(self.vnc.capture(f"{screenshot}-before.png")))
        clicked = time.time()
        clicks = 0
        deadline = time.time() + timeout
        while time.time() < deadline:
            image = self.vnc.stable_capture(f"{screenshot}-attempt.png")
            text = self.ocr_text(image)
            normalized = re.sub(r"\s+", " ", text.lower())
            if any(needle.lower() in normalized for needle in needles):
                self.log(f"detected {label!r}")
                self.vnc.stable_capture(f"{screenshot}.png")
                return
            if "installation failed" in normalized or "installer failed" in normalized:
                raise Failure(f"Calamares reported a failure while waiting for {label}; see {image}")
            if time.time() - clicked < 25:
                time.sleep(3)
                continue
            if clicks >= 3:
                break
            now = self.page_signature(text)
            overlap = len(before & now) / max(1, len(before | now))
            if overlap < 0.75:
                self.log(f"{label}: the screen changed without matching {needles!r}, not re-clicking")
                before, clicked = now, time.time()
                continue
            clicks += 1
            self.log(f"{label}: still on the same page after 25 s, clicking Next again ({clicks})")
            if not self.click_word("next"):
                # Alt+N is not a safe fallback: on the welcome page the
                # language combo owns focus, and Alt+N became type-ahead "n"
                # and selected "norsk bokmål" in run 42296526484. The button's
                # geometry depends on neither OCR nor focus.
                self.click_primary_button()
            clicked = time.time()
        self.vnc.capture(f"{screenshot}-gave-up.png")
        raise Failure(f"never reached {label} after {clicks + 1} click(s); last OCR: {normalized[-1500:]}")

    def calamares_log_size(self) -> int:
        assert self.serial
        output = self.serial.command(
            "stat -c %s /root/.cache/calamares/session.log 2>/dev/null || echo 0",
            timeout=30,
            check=False,
        )
        for line in output.splitlines():
            if line.strip().isdigit():
                return int(line.strip())
        return 0

    def crash_evidence(self) -> str:
        """Gather whatever the guest knows about the installer dying.

        The crash dialog gives the signal and a PID but no stack, and a
        segfaulting Calamares leaves its session log frozen mid-job, so the
        backtrace has to come from the core dump or the kernel's own report.
        """
        assert self.serial
        probes = (
            ("tail of /tmp/calamares.out", "tail -n 120 /tmp/calamares.out 2>/dev/null || true"),
            (
                "kernel report",
                "dmesg | grep -iE 'segfault|general protection|traps|killed process|"
                "out of memory' | tail -n 20 || true",
            ),
            (
                "core dump",
                "command -v coredumpctl >/dev/null && coredumpctl info calamares 2>&1 "
                "| tail -n 80 || echo 'no coredumpctl in the live image'",
            ),
            # An empty filtered dmesg only means something next to the raw tail:
            # run 41830599254 segfaulted with no matching kernel line at all.
            ("tail of dmesg", "dmesg | tail -n 12 || true"),
            ("recorded crashes", "ls -l /var/crash /var/lib/systemd/coredump 2>/dev/null || true"),
            (
                "session log tail",
                "tail -n 40 /root/.cache/calamares/session.log 2>/dev/null || true",
            ),
        )
        chunks = []
        for label, probe in probes:
            try:
                output = self.serial.command(probe, timeout=180, check=False)
            except Failure as exc:
                output = f"(could not read: {exc})"
            chunks.append(f"--- {label}\n{output.strip()}")
        return "\n".join(chunks)

    def start_install(self) -> None:
        """Start the install without guessing the Install button by OCR.

        The summary body contains the words "Install Samurai on ...", so an
        OCR click landed on that sentence and the installer sat on the summary
        page for the whole timeout. The button carries the standard Alt+I
        accelerator; a geometry click is the fallback. Either way, the install
        only counts as started once Calamares actually runs its jobs.
        """
        baseline = self.calamares_log_size()
        self.log(f"Calamares session log is {baseline} bytes before starting")
        attempts: list[tuple[str, object]] = [
            ("the Alt+I accelerator", lambda: self.vnc.key("alt-i")),
            ("the Alt+I accelerator again", lambda: self.vnc.key("alt-i")),
            ("a click on the primary button", self.click_primary_button),
            ("the Alt+I accelerator", lambda: self.vnc.key("alt-i")),
        ]
        for label, action in attempts:
            self.log(f"starting the install with {label}")
            assert callable(action)
            action()
            deadline = time.time() + 45
            while time.time() < deadline:
                time.sleep(5)
                size = self.calamares_log_size()
                if size > baseline + 512:
                    self.log(
                        "Calamares is installing: the session log grew from "
                        f"{baseline} to {size} bytes"
                    )
                    return
        self.vnc.capture("06-install-not-started.png")
        raise Failure(
            "Calamares stayed on the summary page after the Alt+I accelerator "
            "and a click on the primary button (see 06-install-not-started.png)"
        )

    # -- install flow --------------------------------------------------

    def apply_calamares_overlay(self, path: str, keys: tuple[str, ...], entries: str) -> None:
        """Add the test's choices to a shipped Calamares config, keeping the rest.

        Calamares reads one YAML file per module, and the harness used to replace
        those files wholesale - so the install ran with a configuration no user
        ever has, silently dropping whatever the distribution sets around the
        partition and bootloader jobs. Log the shipped file, delete only the keys
        the test cares about, then append them.
        """
        assert self.serial
        shipped = self.serial.command(
            f"sed -n '1,80p' {shlex.quote(path)} 2>/dev/null || true", timeout=60, check=False
        )
        self.log(f"shipped {path}:\n{shipped[-1800:]}")
        quoted = shlex.quote(path)
        strip = "; ".join(
            f"sed -i '/^{key}[[:space:]]*:/d' {quoted}" for key in keys
        )
        # posixpath, not Path: this is a path inside the guest, and a host
        # pathlib on Windows turns /etc/calamares into \etc\calamares, which the
        # guest would happily create as a directory named with backslashes.
        self.serial.command(
            f"mkdir -p {shlex.quote(posixpath.dirname(path))}; "
            f"[ -f {quoted} ] || : > {quoted}; {strip}; "
            f"printf '%s\\n' {shlex.quote(entries)} >> {quoted}",
            timeout=90,
        )

    def configure_calamares_for_test(self) -> None:
        """Preseed only the choices that would otherwise need a lot of clicking.

        The installer still goes through the real partition, mount, unpackfs,
        bootloader, packages and initramfs jobs.
        """
        self.apply_calamares_overlay(
            "/etc/calamares/modules/partition.conf",
            ("initialPartitioningChoice", "initialSwapChoice", "defaultFileSystemType"),
            "initialPartitioningChoice: erase\n"
            "initialSwapChoice: none\n"
            "defaultFileSystemType: ext4\n",
        )
        self.apply_calamares_overlay(
            "/etc/calamares/modules/grubcfg.conf",
            ("overwrite", "keep_distributor", "prefer_grub_d", "kernel_params"),
            # Quote the console argument: YAML flow sequences split on commas,
            # which turned it into two kernel arguments (ttyS0 + 115200n8).
            "overwrite: false\n"
            "keep_distributor: false\n"
            "prefer_grub_d: false\n"
            'kernel_params: [ quiet, "console=ttyS0,115200n8" ]\n',
        )
        self.apply_calamares_overlay(
            "/etc/calamares/modules/locale.conf",
            ("useSystemTimezone",),
            "useSystemTimezone: true\n",
        )
        self.log("applied Calamares test overlays")

    def report_firewall(self) -> None:
        """Put the firewall's actual state in the log rather than infer it.

        Run 41596964514 booted the live session with nftables.service failed
        ("Main process exited, code=exited, status=3/NOTIMPLEMENTED"), and a
        packet filter that does not load is not a security control, so the
        reason has to be visible instead of an exit code three lines deep in
        dmesg.
        """
        assert self.serial
        report = self.serial.command(
            "systemctl status nftables --no-pager -l 2>&1 | tail -n 12; "
            "nft --check --file /etc/nftables.conf 2>&1 | tail -n 6; "
            "uname -r; ls /lib/modules 2>&1 | head -n 4; "
            "modprobe nf_tables 2>&1; echo modprobe-status=$?; "
            "nft --check --file /etc/nftables.conf 2>&1 | tail -n 4; "
            "nft list ruleset 2>&1 | head -n 5",
            timeout=120,
            check=False,
        )
        self.log(f"live firewall state:\n{report[-2500:]}")

    def report_input_devices(self) -> None:
        """Say whether the guest can see the VNC pointer at all.

        The installer is driven by clicks delivered through QEMU's usb-tablet,
        and run 41608570457 clicked on Next four times without the page changing
        on a kernel that could load no module - including usbhid. Whether that is
        why is answerable from the guest, so ask it instead of guessing.
        """
        assert self.serial
        report = self.serial.command(
            "dmesg | grep -iE 'usbhid|hid|input:' | tail -n 12; "
            "echo before:; ls /dev/input 2>&1; "
            "modprobe usbhid 2>&1; echo usbhid-status=$?; "
            "echo after:; ls /dev/input 2>&1",
            timeout=120,
            check=False,
        )
        self.log(f"live input devices:\n{report[-2000:]}")

    def report_installer_entry_point(self) -> None:
        """Record how a person on the live desktop would actually start this.

        installation.md promises a desktop icon or menu entry, and the test then
        launches Calamares as root on a serial shell - which is not how anyone
        installs a system. Whether that gap matters is answerable from the live
        session: what launcher the image ships, what it execs (a plain
        `calamares`, or a polkit elevation a real user has to authenticate to),
        and what session the live user is sitting in.
        """
        assert self.serial
        report = self.serial.command(
            "echo 'live sessions:'; loginctl --no-pager list-sessions 2>&1 | head -n 6; "
            "echo 'display manager:'; systemctl is-enabled sddm 2>&1; "
            "echo 'desktop files that exec calamares:'; "
            "grep -l -i 'calamares' /usr/share/applications/*.desktop "
            "/etc/skel/Desktop/*.desktop 2>/dev/null | "
            "while read -r f; do echo \"$f: $(sed -n 's/^Exec=//p' \"$f\" | head -n1)\"; done; "
            "echo 'skel desktop:'; ls /etc/skel/Desktop 2>&1; "
            "echo 'polkit actions:'; ls /usr/share/polkit-1/actions/ 2>/dev/null "
            "| grep -i calamares || echo none",
            timeout=120,
            check=False,
        )
        self.log(f"live installer entry point:\n{report[-2500:]}")

    def live_compositor(self) -> str:
        """Return "x11" or "wayland" once the live session has a compositor.

        Run 41991858787 asked at 08:11:23 and got nothing, because SDDM was still
        bringing the session up, then decided there was no Wayland session to
        switch away from; by 08:11:59 that same session had kwin_wayland,
        plasmashell and Xwayland running and the installer had been launched into
        a half-started desktop. A compositor that has not forked yet is not a
        compositor that is absent, so wait for one to appear.
        """
        assert self.serial
        out = self.serial.command(
            "i=0; c=; while [ $i -lt 90 ]; do "
            "if pgrep -x kwin_x11 >/dev/null 2>&1; then c=x11; break; fi; "
            "if pgrep -x kwin_wayland >/dev/null 2>&1; then c=wayland; break; fi; "
            "sleep 2; i=$((i+1)); done; "
            'echo "compositor=${c:-none} waited_halves=$i"',
            timeout=240,
            check=False,
        )
        self.log("live compositor: " + " ".join(out.split()))
        for line in out.splitlines():
            if line.startswith("compositor="):
                value = line.split("=", 1)[1].split()[0]
                return "" if value == "none" else value
        return ""

    def live_x_display(self) -> str:
        """Which X display the guest's X server actually answers on.

        ":0" stops being safe the moment SDDM is restarted: run 42105485811 kept
        logind session 5 (the Wayland one, with its Xwayland on :0) listed as
        "online" while the new Xorg took tty3, so a hardcoded :0 can name a
        server that no longer holds the screen. Ask the running Xorg.
        """
        assert self.serial
        out = self.serial.command(
            "for p in $(pgrep -x Xorg 2>/dev/null); do "
            "tr '\\0' '\\n' < \"/proc/$p/cmdline\" 2>/dev/null; done "
            "| grep -E -m1 '^:[0-9]+$'; "
            "ls -t /tmp/.X11-unix/X* 2>/dev/null | head -n1 | sed -n 's|.*X|:|p'",
            timeout=60,
            check=False,
        )
        for line in out.splitlines():
            if re.fullmatch(r":\d+", line.strip()):
                return line.strip()
        return ":0"

    def start_x11_session(self, session: str) -> bool:
        """Start the X11 Plasma session by hand when SDDM's autologin did not.

        Run 42112234958 shows what "the X11 session came up with no compositor"
        really was: the autologin drop-in was ignored, SDDM started the Wayland
        session anyway, that session exited ten seconds later, and SDDM then
        removed the display and added a new one on VT3 for its **greeter** - an
        X server with a login screen and nobody logged in, which is what the
        earlier cycle read as "Type=x11, active, no kwin_x11". If the patched
        configuration still does not autologin, the test's remaining option is
        to log in itself: run exactly what the session file says to run, as the
        user the image logs in automatically, on the display that X server
        serves, and keep everything it prints.

        A success here says the installer was tested on an X11 desktop the
        harness started rather than one the image started by itself; a failure
        says startplasma-x11 cannot come up in the live image at all. Either is
        more informative than the "x11=no" this method replaced.
        """
        assert self.serial
        if not re.fullmatch(r"[A-Za-z0-9._-]+", session):
            self.log(f"refusing to start session with the unusable name {session!r}")
            return False
        session_file = shlex.quote(f"/usr/share/xsessions/{session}.desktop")
        # The display cannot be read out of the X server's environment: run
        # 42112234958 showed SDDM starting it as "/usr/bin/X ... -displayfd 17",
        # which hands the number back over a file descriptor and stores it
        # nowhere. The socket in /tmp/.X11-unix is what is left, so that is what
        # names the display.
        display = self.live_x_display()
        info = self.serial.command(
            "xp=$(pgrep -x Xorg 2>/dev/null | head -n1); xa=; exec_line=; "
            'if [ -n "$xp" ]; then '
            "xa=$(tr '\\0' '\\n' < \"/proc/$xp/environ\" 2>/dev/null "
            "| sed -n 's/^XAUTHORITY=//p' | head -n1); fi; "
            'if [ -z "$xa" ] || [ ! -r "$xa" ]; then '
            "xa=$(ls -t /run/sddm/xauth_* /home/samurai/.Xauthority /run/user/1000/xauth_* "
            "2>/dev/null | head -n1); fi; "
            "exec_line=$(sed -n 's/^Exec=//p' " + session_file + " | head -n1); "
            'printf "xorg=%s\\ndisplay=%s\\ncookie=%s\\nexec=%s\\n" '
            '"${xp:-none}" ' + shlex.quote(display) + ' "${xa:-none}" "${exec_line:-none}"',
            timeout=60,
            check=False,
        )
        fields = {}
        for line in info.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                fields[key.strip()] = value.strip()
        display, cookie = fields.get("display", ":0"), fields.get("cookie", "none")
        program = fields.get("exec", "none")
        self.log(f"X11 session by hand: {' '.join(info.split())}")
        if program == "none":
            self.log("the X11 session file has no Exec to run")
            return False
        env = f"HOME=/home/samurai DISPLAY={shlex.quote(display)} XDG_SESSION_TYPE=x11"
        if cookie != "none":
            env += f" XAUTHORITY={shlex.quote(cookie)}"
        # The session bus SDDM would have given the session does not exist here,
        # and startplasma-x11 needs one to register kded6 on - which is the name
        # Calamares' first partitioning job calls. Give the session a bus the
        # same way the shipped session does, and let the launcher find it in
        # samurai's own process environment the way it finds any other.
        wrapper = "/tmp/samurai-start-x11-session.sh"
        self.serial.write_file(
            wrapper,
            "#!/bin/sh\n"
            "if command -v dbus-run-session >/dev/null 2>&1; then\n"
            f"    exec dbus-run-session -- bash -lc {shlex.quote(program)}\n"
            "fi\n"
            f"exec bash -lc {shlex.quote(program)}\n",
        )
        self.serial.command(f"chmod 0755 {shlex.quote(wrapper)}", timeout=30, check=False)
        self.serial.command(
            "rm -f /tmp/samurai-startplasma.out; "
            # The display this lands on is usually SDDM's greeter X, and a
            # greeter drawing a login screen over the installer would make
            # every screenshot below meaningless. SDDM started that server with
            # -noreset, so the client can go and the server stay.
            "pkill -x sddm-greeter >/dev/null 2>&1 || true; "
            f"setsid sudo -u samurai env {env} XDG_RUNTIME_DIR=/run/user/1000 "
            f"sh {shlex.quote(wrapper)} >/tmp/samurai-startplasma.out 2>&1 "
            "< /dev/null & echo started=$!",
            timeout=60,
            check=False,
        )
        back = self.serial.command(
            "i=0; while [ $i -lt 45 ] && ! pgrep -x kwin_x11 >/dev/null 2>&1; do "
            "sleep 2; i=$((i+1)); done; "
            "echo waited_halves=$i; pgrep -x kwin_x11 >/dev/null 2>&1 "
            "&& echo x11=yes || echo x11=no; "
            "echo 'what it printed:'; tail -n 25 /tmp/samurai-startplasma.out 2>&1",
            timeout=150,
            check=False,
        )
        self.log("X11 session started by hand: " + " | ".join(line for line in back.splitlines() if line.strip()))
        return "x11=yes" in back

    def x11_autologin(self, session: str) -> None:
        """Aim whatever SDDM calls autologin at the X11 session.

        The drop-in alone is not the answer. Run 42112234958 restarted SDDM with
        /etc/sddm.conf.d/99-install-test-x11.conf holding Session=plasmax11 and
        the journal still said "Starting Wayland user session: ...
        /usr/bin/startplasma-wayland"; ten seconds later that session exited
        cleanly, SDDM removed the display and added a new one on VT3 running
        "/usr/bin/X ... -displayfd 17" for its **greeter**. That is the whole of
        what the previous cycle read as "an X11 session with no compositor in
        it": Xorg was SDDM's greeter X, nobody had logged in, and the autologin
        request had been ignored.

        So disable every Session= key the image already carries - SDDM's schema
        only uses that name under [Autologin] - and state the request once more
        in a file named to sort after any the image ships. Which of those two is
        the one SDDM obeys is not established from upstream documentation, so
        the configuration is printed before it is touched: nothing in this
        project has ever read the live image's autologin settings back, and they
        are the reason two cycles in a row ended where they did.
        """
        assert self.serial
        dump = self.serial.command(
            "echo 'sddm configuration files:'; ls -l /etc/sddm.conf /etc/sddm.conf.d/ 2>&1; "
            "for f in /etc/sddm.conf /etc/sddm.conf.d/*.conf; do "
            '[ -f "$f" ] || continue; echo "== $f"; cat "$f"; done 2>&1; '
            "echo 'live autologin mechanism:'; grep -R -n -i 'autologin' /etc/sddm.conf "
            "/etc/sddm.conf.d /etc/live 2>/dev/null | head -n 12; "
            "cat /proc/cmdline 2>&1",
            timeout=60,
            check=False,
        )
        self.log("SDDM configuration before the test changed it:\n" + dump[-3500:])
        script = "/tmp/samurai-x11-autologin.sh"
        self.serial.write_file(
            script,
            "#!/bin/sh\n"
            "# Written by build/install-test.py; points SDDM's autologin at X11.\n"
            "#\n"
            "# SDDM resolves an autologin request from /etc/sddm.conf together\n"
            "# with the drop-in directory, and whatever the live image configures\n"
            "# there outvoted a test file named 99-...: run 42112234958 left that\n"
            "# file holding Session=plasmax11 and the journal still logged the\n"
            "# Wayland session. Rather than guess which file wins, disable every\n"
            "# other Session= key - SDDM's schema only uses that name under\n"
            "# [Autologin] - and state the request once more, at the end of the\n"
            "# alphabet.\n"
            "set -eu\n"
            "for f in /etc/sddm.conf /etc/sddm.conf.d/*.conf; do\n"
            '    [ -f "$f" ] || continue\n'
            '    grep -qE "^[[:space:]]*[Ss]ession[[:space:]]*=" "$f" || continue\n'
            '    cp -a "$f" "$f.orig.install-test" 2>/dev/null || true\n'
            "    sed -E -i 's/^([[:space:]]*)([Ss]ession[[:space:]]*=.*)$/\\1# \\2/' \"$f\"\n"
            "    printf 'disabled the Session= keys in %s\\n' \"$f\"\n"
            "done\n",
        )
        answer = self.serial.command(f"sh {shlex.quote(script)}", timeout=60, check=False)
        self.log("SDDM autologin patch: " + " | ".join(line for line in answer.splitlines() if line.strip()))
        self.serial.command("mkdir -p /etc/sddm.conf.d", timeout=30)
        self.serial.write_file(
            "/etc/sddm.conf.d/zz-install-test-x11.conf",
            f"[Autologin]\nUser=samurai\nSession={session}\n",
        )

    def ensure_x11_live_session(self) -> None:
        """Move the live session from KWin on Wayland to KWin on X11.

        Three runs end the same way: Calamares logs "Updating partitioning
        preview widgets" and one or two seconds later the coredump table records a
        SIGSEGV in /usr/bin/kwin_wayland (run 41989352435: PID 1252, UID 1000,
        frames from libkwin.so.6), the Wayland session's Xwayland dies with it,
        and Calamares exits quoting "The X11 connection broke (error 1). Did the
        X11 server die?" - which is why that run's OCR saw a blank screen from
        07:51:45 onward and why the installer looked dead when it was not.
        Giving the guest a real KMS device did not prevent it: virtio-gpu has
        been the QEMU VGA since run 41596964514 and the crash came back at the
        same step. The compositor is what dies, so ask for the other one. Plasma
        ships both, the installed system is already tested on X11 because
        MangoHUD is documented to be unreliable on Wayland, and X11 gives the
        test an Xorg to switch VTs to, which is what the VNC screenshot shows.

        This overrides the live image's session choice at runtime; it is logged
        as a test-environment change, not as a shipped default.
        """
        assert self.serial
        compositor = self.live_compositor()
        if compositor == "x11":
            return
        if compositor != "wayland":
            self.log("no Plasma compositor came up at all; leaving the session alone")
            return
        listing = self.serial.command(
            'for f in /usr/share/xsessions/*.desktop; do [ -e "$f" ] && echo "$f"; '
            "done 2>/dev/null || true",
            timeout=30,
            check=False,
        )
        files = [line.strip() for line in listing.splitlines() if line.strip().endswith(".desktop")]
        if not files:
            self.log("the live image ships no X11 session file; staying on Wayland")
            return
        # SDDM matches [Autologin] Session against the session name, not the
        # file name, so the ".desktop" suffix has to go.
        session = Path(files[0]).name.removesuffix(".desktop")
        self.x11_autologin(session)
        self.log(f"restarting SDDM into the X11 session {session!r} for this test")
        self.serial.command("systemctl restart sddm", timeout=180, check=False)
        back = self.serial.command(
            "i=0; while [ $i -lt 60 ] && ! pgrep -x kwin_x11 >/dev/null 2>&1; do "
            "sleep 2; i=$((i+1)); done; "
            "echo waited_halves=$i; pgrep -x kwin_x11 >/dev/null 2>&1 "
            "&& echo x11=yes || echo x11=no; "
            "echo 'what sddm started:'; journalctl -b -u sddm --no-pager 2>&1 "
            "| grep -E 'Starting (X11|Wayland) user session|Greeter starting|Session started' "
            "| tail -n 4; "
            "loginctl --no-pager list-sessions 2>&1 | head -n 4",
            timeout=240,
            check=False,
        )
        self.log("live session after restart: " + " | ".join(line for line in back.splitlines() if line.strip()))
        if "x11=yes" not in back:
            # "no kwin_x11" has at least three causes and they are not
            # distinguishable from the wait loop's answer: the compositor binary
            # may not be installed (run 41993508779: Debian puts kwin_x11 in its
            # own package and the image had not installed it), the session may
            # have come back on Wayland, or X itself may have failed. Ask which
            # of those it is before giving up.
            detail = self.serial.command(
                "ps -e -o pid=,uid=,comm= | grep -E 'kwin|Xorg|Xwayland|startplasma|plasma' | head -n 12; "
                "echo 'compositor binaries:'; ls -l /usr/bin/kwin_x11 /usr/bin/kwin_wayland "
                "/usr/bin/startplasma-x11 2>&1; "
                "echo 'session file:'; grep -HE '^(Exec|TryExec|DesktopNames)=' "
                "/usr/share/xsessions/*.desktop 2>&1; "
                "echo 'session types:'; "
                "for s in $(loginctl --no-pager list-sessions 2>/dev/null | awk 'NR>1{print $1}'); do "
                'echo "$s $(loginctl --no-pager show-session "$s" -p Type -p State -p TTY '
                '2>/dev/null | tr \'\\n\' \' \')"; done; '
                "echo 'core dumps:'; coredumpctl --no-pager list 2>&1 | tail -n 8; "
                "echo 'xorg log:'; "
                "lf=$(ls -t /var/log/Xorg.*.log 2>/dev/null | head -n1); "
                'echo "$lf"; [ -n "$lf" ] && tail -n 25 "$lf"; '
                "echo 'sddm journal:'; journalctl -b -u sddm --no-pager 2>&1 | tail -n 30; "
                "echo 'sddm session logs:'; ls -l /home/samurai/.local/share/sddm/ 2>&1; "
                "for f in /home/samurai/.local/share/sddm/*.log; do "
                '[ -e "$f" ] && echo "--- $f" && tail -n 20 "$f"; done 2>&1',
                timeout=120,
                check=False,
            )
            self.log("why the X11 session did not come up:\n" + detail[-4000:])
            if self.start_x11_session(session):
                self.log(
                    "the X11 session came up only when the harness started it; SDDM "
                    "autologin into that session is a real defect, logged as one"
                )
                return
            raise Failure(
                f"the live session did not come back on X11 as {session!r}, and the "
                f"harness could not start that session by hand either; "
                f"sessions after restart: {back.strip()!r}\n"
                f"what the guest says is running:\n{detail[-3000:]}"
            )

    def prepare_root_display(self) -> None:
        """Give root a working X display and prove it before putting anything on it.

        Run 41991858787 copied the X cookie at 08:11:26 while the session was
        still starting and SDDM replaced that cookie as it came up; the xhost
        grant that followed threw its output away, so Calamares was launched at
        08:11:58 onto a display root could not use, died within four seconds, and
        the tail the harness reported was xdg-desktop-portal noise about "cannot
        open display" rather than the reason. Ask the live session's own processes
        where their cookie is, then check the answer with a real X request and
        retry until it succeeds.
        """
        assert self.serial
        self.x_display = self.live_x_display()
        self.log(f"live X display: {self.x_display}")
        state = ""
        for attempt in range(1, 8):
            state = self.serial.command(
                "xa=; for p in $(pgrep -x kwin_x11 2>/dev/null) $(pgrep -x kwin_wayland 2>/dev/null) "
                "$(pgrep -x Xwayland 2>/dev/null) $(pgrep -x Xorg 2>/dev/null); do "
                'c=$(tr \'\\0\' \'\\n\' < "/proc/$p/environ" 2>/dev/null '
                "| sed -n 's/^XAUTHORITY=//p' | head -n1); "
                '[ -n "$c" ] && [ -r "$c" ] && xa=$c && break; done; '
                '[ -n "$xa" ] || xa=$(ls /home/samurai/.Xauthority /run/user/1000/xauth_* '
                '/run/sddm/xauth_* 2>/dev/null | head -n1); '
                'if [ -n "$xa" ]; then install -m 0600 "$xa" /root/.Xauthority; fi; '
                "if DISPLAY=" + self.x_display + " XAUTHORITY=/root/.Xauthority "
                "xhost +SI:localuser:root "
                ">/dev/null 2>&1; then xh=ok; else xh=refused; fi; "
                "if DISPLAY=" + self.x_display + " XAUTHORITY=/root/.Xauthority "
                "xset q >/dev/null 2>&1; "
                "then xs=ok; else xs=refused; fi; "
                'printf "cookie=%s xhost=%s xset=%s\\n" "${xa:-none}" "$xh" "$xs"',
                timeout=90,
                check=False,
            )
            self.log(f"display attempt {attempt}: " + " ".join(state.split()))
            if "xset=ok" in state:
                return
            time.sleep(5)
        raise Failure(
            "root could not use the live X display, so nothing could be launched "
            f"on it; last answer from the guest: {state.strip()!r}"
        )

    def launch_calamares(self) -> None:
        # The Debian wrapper moves the live fstab aside because it confuses
        # Calamares' partition module.
        assert self.serial
        self.report_firewall()
        self.report_input_devices()
        self.report_installer_entry_point()
        self.ensure_x11_live_session()
        self.serial.command(
            "if [ -e /etc/fstab ]; then mv /etc/fstab /etc/fstab.orig.calamares; fi",
            timeout=30,
            check=False,
        )
        self.prepare_root_display()
        # QEMU's VNC output follows the active VT, so make Xorg's VT visible.
        self.serial.command(
            "vt=$(ps -o tty= -C Xorg 2>/dev/null | tr -d ' ' | head -n1); "
            "case \"$vt\" in tty[0-9]*) chvt \"${vt#tty}\" ;; esac",
            timeout=30,
            check=False,
        )
        self.dismiss_welcome()
        # A blanked desktop hides the installer from VNC (and from every
        # screenshot kept as CI evidence), so switch X's blanking off and stop
        # Plasma's power daemon from blanking it again.
        self.serial.command(
            "pkill -x powerdevil >/dev/null 2>&1 || true; "
            "DISPLAY=" + self.x_display + " XAUTHORITY=/root/.Xauthority "
            "xset s off s noblank -dpms >/dev/null 2>&1 || true",
            timeout=30,
            check=False,
        )
        # Which desktop is actually running decides which half of the launcher
        # matters. Run 41892892060 fell back to a private bus and the journal
        # called it "dbus-daemon[1365]: [session uid=0 ...]" - a bus started for
        # the installer, not the one a session logged into - while run
        # 41984807632 showed samurai running kwin_wayland, ksplashqml and a
        # dbus-daemon behind a /run/user/1000/bus that refused to connect. So
        # name the session's processes and let the user bus say in its own words
        # whether root may use it.
        desktop = self.serial.command(
            "ls /run/user/ 2>/dev/null | tr '\\n' ' '; "
            "echo session-procs:; ps -e -o user=,comm= "
            "| awk '$1==\"samurai\" || $1==\"live\"' | sort -u | head -n 14; "
            "[ -S /run/user/1000/bus ] && echo 'user bus socket=present' "
            "|| echo 'user bus socket=absent'; "
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus "
            "busctl --no-pager --user list 2>&1 | head -n 2",
            timeout=90,
            check=False,
        )
        self.log("live desktop: " + " | ".join(line for line in desktop.splitlines() if line.strip()))
        self.serial.write_file(CALAMARES_LAUNCHER_PATH, CALAMARES_LAUNCHER)
        launcher = shlex.quote(CALAMARES_LAUNCHER_PATH)
        self.serial.command(f"chmod 0755 {launcher}", timeout=30)
        if (
            self.serial.command(
                "command -v dbus-run-session >/dev/null && echo yes || echo no", timeout=30
            ).strip()
            == "yes"
        ):
            # The launcher moves to the Plasma bus itself when it can use it; the
            # private bus is only there so kded has somewhere to register when
            # there is no Plasma session to join.
            start = f"dbus-run-session -- {launcher}"
        else:
            start = launcher
        self.serial.background(
            "DISPLAY=" + self.x_display + " XAUTHORITY=/root/.Xauthority "
            "QT_AUTO_SCREEN_SCALE_FACTOR=1 "
            f"QT_QUICK_BACKEND=software {start} >/tmp/calamares.out 2>&1"
        )
        # Cold-starting kded can take half a minute, so wait for the installer
        # instead of assuming a fixed delay: a 10-second sleep would have called
        # run 41892892060 "not running" while its launcher was still working.
        up = self.serial.command(
            "i=0; while [ $i -lt 70 ] && ! pgrep -x calamares >/dev/null 2>&1; do "
            "sleep 2; i=$((i+1)); done; "
            "echo waited_halves=$i; pgrep -x calamares >/dev/null 2>&1 "
            "&& echo calamares=yes || echo calamares=no",
            timeout=180,
            check=False,
        )
        self.log("installer start: " + " ".join(up.split()))
        markers = self.serial.command(
            "grep -h '^SAMURAI_' /tmp/calamares.out 2>/dev/null || true", timeout=30, check=False
        )
        for line in markers.splitlines():
            name, _, value = line.partition("=")
            self.log(f"launcher {name}: {value.strip()}")
        self.dismiss_welcome()
        tail = self.serial.command("tail -n 30 /tmp/calamares.out 2>/dev/null || true", timeout=30)
        running = self.serial.command("pgrep -x calamares >/dev/null && echo yes || echo no", timeout=30)
        if running.strip() != "yes":
            raise Failure(f"Calamares is not running; output:\n{tail}")
        if "cannot connect" in tail.lower() or "could not connect" in tail.lower():
            raise Failure(f"Calamares could not connect to the live display:\n{tail}")

    def drive_installer(self) -> None:
        self.wait_for(
            "calamares installer",
            "Calamares welcome page",
            240,
            "01-welcome",
            dismiss_welcome=True,
            watch=("calamares", "/tmp/calamares.out"),
        )
        self.advance(
            ("system language", "zone:", "region"),
            "Calamares locale page",
            90,
            "02-locale",
        )
        self.advance(
            ("keyboard model", "test your keyboard"),
            "Calamares keyboard page",
            90,
            "03-keyboard",
        )
        self.advance(
            ("erase disk", "manual partitioning"),
            "Calamares partition page",
            120,
            "04-partition",
        )
        self.advance(
            ("what is your name", "login name", "computer name"),
            "Calamares users page",
            120,
            "05-users",
        )

        # UsersViewStep focuses the full-name field on activation. The tab
        # order is full name -> login name -> computer name -> password ->
        # repeat password.
        self.vnc.type("Samurai Tester")
        self.vnc.key("tab")
        self.vnc.key("ctrl-a")
        self.vnc.type("samurai")
        self.vnc.key("tab")
        self.vnc.key("ctrl-a")
        self.vnc.type("samurai-test")
        self.vnc.key("tab")
        self.vnc.type(self.password)
        self.vnc.key("tab")
        self.vnc.type(self.password)
        time.sleep(1)
        self.vnc.capture("05-users-filled.png")
        self.advance("overview", "Calamares summary page", 120, "06-summary")

        self.start_install()

        # The exec page has no stable text other than the progress bar. Wait
        # for the finished page; poll the serial log so a stuck job is visible.
        self.log("installation started; waiting for the finished page")
        deadline = time.time() + self.timeout
        attempt = 0
        # A silent session log is not evidence of a dead installer: under TCG the
        # packages and unpackfs jobs run for many minutes without printing
        # anything. What makes an idle log fatal is nobody left alive to fill it,
        # so the poll also asks whether calamares is still a process. Run
        # 41802792291 segfaulted two seconds into job 2 of 39 and this loop
        # watched the corpse for 91 minutes before reporting pixels.
        last_size = self.calamares_log_size()
        stalled = 0
        while time.time() < deadline:
            attempt += 1
            time.sleep(15)
            # The session log is the authoritative completion signal: the
            # Finished module logs "completion: succeeded" exactly once, after
            # the last job and the final umount have completed. OCR is only a
            # hint here because the live desktop can blank its display.
            state = ""
            try:
                assert self.serial
                state = self.serial.command(
                    "log=/root/.cache/calamares/session.log; "
                    "if grep -q 'completion: succeeded' \"$log\" 2>/dev/null; then s=DONE; "
                    "elif grep -qE 'Installation failed|External command finished with errors' "
                    "\"$log\" 2>/dev/null; then s=FAILED; else s=RUNNING; fi; "
                    "pgrep -x calamares >/dev/null && a=yes || a=no; "
                    "printf 'SAMURAI_STATE=%s ALIVE=%s SIZE=%s\\n' "
                    "\"$s\" \"$a\" \"$(wc -c <\"$log\" 2>/dev/null || echo 0)\"",
                    timeout=90,
                    check=False,
                )
            except Failure as exc:
                self.log(f"could not read the Calamares state: {exc}")
            state = state.strip()
            if state:
                self.log(f"calamares state: {state} (poll {attempt})")
            if "SAMURAI_STATE=DONE" in state:
                self.vnc.wake()
                self.vnc.capture("08-finished.png")
                self.log("Calamares reported completion: succeeded")
                return
            if "SAMURAI_STATE=FAILED" in state:
                self.vnc.wake()
                self.vnc.capture("08-failure.png")
                tail = self.serial.command(
                    "tail -n 40 /root/.cache/calamares/session.log 2>/dev/null || true",
                    timeout=60,
                    check=False,
                )
                raise Failure(
                    "Calamares reported an installation failure; session log tail:\n"
                    + "\n".join(tail.splitlines()[-40:])
                )
            alive = re.search(r"ALIVE=(\w+)", state)
            size_match = re.search(r"SIZE=(\d+)", state)
            if size_match:
                size = int(size_match.group(1))
                stalled = stalled + 1 if size == last_size else 0
                last_size = size
            if alive and alive.group(1) == "no":
                # The installer is gone. Either it finished without the log
                # saying so, or it died; only the second is a failure.
                self.vnc.wake()
                image = self.vnc.capture(f"07-installer-gone-{attempt:02d}.png")
                text = re.sub(r"\s+", " ", self.ocr_text(image).lower())
                if not any(x in text for x in FINISHED_WORDS):
                    raise Failure(
                        "the calamares process exited before the install finished "
                        f"(poll {attempt}, session log {last_size} bytes, screen reads "
                        f"{text[-120:]!r})\n" + self.crash_evidence()
                    )
                self.vnc.capture("08-finished.png")
                self.log(f"Calamares exited on the finished page: {text[-100:]}")
                return
            if attempt % 8 == 0 or stalled >= 20:
                # Keep one screenshot every couple of minutes as evidence, and
                # look sooner once the log has been silent for five minutes.
                self.vnc.wake()
                image = self.vnc.capture(f"07-progress-{attempt:02d}.png")
                text = re.sub(r"\s+", " ", self.ocr_text(image).lower())
                if any(x in text for x in CRASH_WORDS):
                    raise Failure(
                        "Calamares crashed during the install; the screen reads "
                        f"{text[-200:]!r} (see {image})\n" + self.crash_evidence()
                    )
                if any(x in text for x in FINISHED_WORDS):
                    self.vnc.capture("08-finished.png")
                    self.log(f"Calamares reached the finished page: {text[-100:]}")
                    return
                if stalled >= 20:
                    self.log(
                        f"session log has not grown for {stalled} polls; the screen "
                        "shows no crash dialog, so this is treated as a slow job"
                    )
        self.vnc.wake()
        self.vnc.capture("08-timeout.png")
        raise Failure("timed out waiting for Calamares to finish")

    def report_qemu_exit(self) -> None:
        """Say whether the guest process survived at all.

        Run 41987490634 lost its serial 32 seconds into boot with "Broken pipe"
        and VNC answered "Connection refused" to all three screenshots. Both
        mean the same thing - QEMU is gone - but nothing in the log said so, and
        the one place that records why, QEMU's own output, sat unread.
        """
        if self.qemu is None:
            return
        status = self.qemu.poll()
        try:
            assert self.qemu_log
            tail = self.qemu_log.read_text(errors="replace")[-1500:]
        except OSError as exc:
            tail = f"unreadable: {exc}"
        self.log(
            "QEMU "
            + ("is still running" if status is None else f"exited with {status}")
            + f"; its output ({self.qemu_log}):\n{tail}"
        )

    def copy_calamares_log(self) -> None:
        """Copy the Calamares session log out over the serial line."""
        if self.log_copied or not self.root_ready or not self.serial:
            return
        self.log("copying the Calamares session log out of the live system")
        try:
            payload = self.serial.pull_file("/root/.cache/calamares/session.log", "Calamares session log")
        except Exception as exc:  # noqa: BLE001 - diagnostics are best effort
            self.log(f"could not copy the Calamares log: {exc}")
            return
        if not payload:
            self.log("the Calamares log was empty or unavailable")
            return
        (self.work / "calamares-session.log").write_bytes(payload)
        self.log("saved calamares-session.log")
        self.log_copied = True

    def verify_boot_loader(self) -> None:
        """Check that the installer made the target disk bootable.

        When BIOS cannot start the disk it prints "Booting from Hard Disk..."
        and hangs, which is indistinguishable from a slow boot until the
        reboot VM times out. Read the boot sector here instead, so a missing
        bootloader fails straight away with something actionable.
        """
        assert self.serial
        # -v keeps od from collapsing runs of zero bytes into "*", which
        # would otherwise hide the 512-byte layout we need to inspect.
        raw = self.serial.command(
            "od -An -v -tx1 -N512 /dev/sda", timeout=120, check=False
        )
        (self.work / "boot-sector.txt").write_text(raw + "\n", encoding="utf-8")
        tokens = [
            token for token in raw.split() if len(token) == 2 and _is_hex(token)
        ]
        sector = bytes(int(token, 16) for token in tokens[:512])
        if len(sector) != 512:
            raise Failure("could not read the installed disk's boot sector:\n" + raw)
        if sector[510:512] != b"\x55\xaa":
            raise Failure(
                "the installed disk has no boot signature in its MBR, so BIOS "
                "cannot start it; boot sector:\n" + raw
            )
        if not any(sector[:440]):
            raise Failure(
                "the installed disk's MBR boot code is empty, so BIOS cannot "
                "start it; boot sector:\n" + raw
            )
        if not any(sector[446:510]):
            raise Failure(
                "the installed disk's MBR has no partition table entries; "
                "boot sector:\n" + raw
            )
        self.log("the installed disk has a bootable MBR")
        files = self.serial.command(
            "mkdir -p /mnt/samurai-verify && "
            "mount -o ro /dev/sda1 /mnt/samurai-verify && "
            "for f in boot/grub/grub.cfg boot/grub/i386-pc/core.img; do "
            'if [ -s "/mnt/samurai-verify/$f" ]; then echo "present $f"; '
            'else echo "missing $f"; fi; done; '
            "umount /mnt/samurai-verify",
            timeout=180,
            check=False,
        )
        self.log("installed boot files:\n" + files)
        if "present boot/grub/grub.cfg" not in files:
            raise Failure(
                "the installed system has no /boot/grub/grub.cfg, so GRUB "
                "cannot boot it; boot files:\n" + files
            )

    def finish_install(self) -> None:
        # Power off from the serial shell rather than clicking the restart
        # checkbox. All install jobs have completed by the finished page.
        self.shutdown_guest()

    # -- post-install verification ------------------------------------

    def verify_installed_system(self) -> None:
        self.start_reboot_vm()
        assert self.serial
        self.serial.login("samurai", self.password, timeout=self.reboot_timeout)
        # /boot/grub/grub.cfg is root-only and the first sudo call would block on
        # a password prompt, so take a root shell up front for the whole check.
        self.serial.root_shell(self.password, timeout=120)

        commands = [
            ("cat /etc/os-release", "os-release"),
            ("hostname", "hostname"),
            ("findmnt -n -o SOURCE /", "root source"),
            ("findmnt -n -o FSTYPE /", "root filesystem"),
            ("stat -c '%U' /home/samurai", "home owner"),
            ("cat /proc/cmdline", "kernel command line"),
            (
                "grep -E 'Samurai Linux|console=ttyS0' /boot/grub/grub.cfg "
                "| head -n 10",
                "installed GRUB",
            ),
            ("cat /etc/default/grub", "grub defaults"),
            ("test -s /usr/share/samurai/boot/grub-splash.png && echo present || echo missing", "GRUB splash"),
            ("cat /etc/motd", "motd"),
            ("dpkg-query -W -f='${Status}\\n' live-boot 2>/dev/null || true", "live-boot status"),
            ("systemctl is-system-running 2>/dev/null || true", "system state"),
            ("systemctl --failed --no-legend 2>/dev/null | head -n 10 || true", "failed units"),
            # Security controls are read as configured state, not as installed
            # packages: the project requirements forbid claiming a control is on
            # because its package was pulled in.
            (
                "systemctl is-enabled nftables.service apparmor.service "
                "apt-daily.timer apt-daily-upgrade.timer 2>&1",
                "security units",
            ),
            ("nft list table inet samurai 2>&1 | head -n 40", "packet filter"),
            ("cat /sys/module/apparmor/parameters/enabled 2>&1", "apparmor parameter"),
            (
                "printf 'profiles=%s complain=%s\\n' \"$(wc -l < /sys/kernel/security/apparmor/profiles 2>/dev/null || echo 0)\" "
                "\"$(grep -c '(complain)' /sys/kernel/security/apparmor/profiles 2>/dev/null || echo 0)\"",
                "apparmor profiles",
            ),
            ("apt-config dump APT::Periodic::Unattended-Upgrade 2>&1", "unattended upgrades"),
            ("apt-config dump Unattended-Upgrade::Allowed-Origins 2>&1", "upgrade origins"),
            # The archive is configured in files the installed system boots with.
            # apt-cache policy is not the test here: it only lists archives apt
            # has already downloaded an index for, and this VM runs with no
            # network at all, so an empty list would say nothing about the policy.
            (
                "cat /etc/apt/sources.list /etc/apt/sources.list.d/*.list "
                "/etc/apt/sources.list.d/*.sources 2>/dev/null | grep -v '^[[:space:]]*#'",
                "apt sources",
            ),
            (
                "dpkg-query -W -f='${Package} ${db:Status-Abbrev} ${Version}\\n' "
                "unattended-upgrades 2>&1",
                "updater package",
            ),
            (
                "timeout 45 unattended-upgrades --dry-run --debug 2>&1 | head -n 60",
                "updater dry run",
            ),
            ("ls /var/lib/apt/lists 2>/dev/null | wc -l", "package indexes"),
            ("ls /etc/apt/apt.conf.d/ 2>&1 | head -n 30", "apt configuration files"),
            ("ls /var/log/journal 2>&1 | head -n 3", "journal storage"),
            ("stat -c '%a %U' /etc/sudoers.d/90samurai /etc/nftables.conf 2>&1", "policy file modes"),
            (
                "grep -rEl '^[^#]*NOPASSWD' /etc/sudoers /etc/sudoers.d/ 2>&1 || echo none",
                "passwordless sudoers",
            ),
            ("lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT", "block devices"),
        ]
        report = []
        values: dict[str, str] = {}
        for command, label in commands:
            output = self.serial.command(command, timeout=60, check=False)
            values[label] = output
            report.append(f"### {label}\n$ {command}\n{output}\n")
        (self.work / "installed-system.txt").write_text("\n".join(report), encoding="utf-8")

        hostname = values.get("hostname", "").strip()
        if hostname != "samurai-test":
            raise Failure(f"installed hostname is {hostname!r}, expected 'samurai-test'")
        root_source = values.get("root source", "").strip()
        if not root_source.startswith("/dev/"):
            raise Failure(f"installed root is {root_source!r}, not a disk device")
        if values.get("home owner", "").strip() != "samurai":
            raise Failure("the installed system has no /home/samurai owned by samurai")
        if "console=ttyS0,115200n8" not in values.get("kernel command line", ""):
            raise Failure("the installed kernel did not receive the serial console argument")
        if "console=ttyS0,115200n8" not in values.get("installed GRUB", ""):
            raise Failure("the installed GRUB configuration lost the serial console argument")
        os_release = values.get("os-release", "")
        if "NAME=" not in os_release:
            raise Failure("the installed system has no /etc/os-release")
        # sudo ignores a group- or world-writable drop-in and nft refuses to read
        # one, so a mode that drifted in installation leaves the policy present
        # and dead. Checked against the modes the security hook sets.
        modes = [line.split() for line in
                 values.get("policy file modes", "").splitlines() if line.split()]
        if len(modes) != 2 or any(len(fields) != 2 for fields in modes):
            raise Failure(
                "could not read both policy file modes from the installed system: "
                f"{values.get('policy file modes')!r}"
            )
        for path, (mode, owner) in zip(
            ("/etc/sudoers.d/90samurai", "/etc/nftables.conf"), modes
        ):
            expected = "440" if "sudoers" in path else "644"
            if mode != expected or owner != "root":
                raise Failure(
                    f"{path} on the installed system is {mode} owned by {owner}, "
                    f"expected {expected} owned by root"
                )
        if self.branded:
            if 'NAME="Samurai Linux"' not in os_release:
                raise Failure(f"installed os-release is not Samurai-branded:\n{os_release}")
            grub_default = values.get("grub defaults", "")
            # Calamares rewrites GRUB_DISTRIBUTOR with single quotes; the live
            # hook writes double quotes. Accept either.
            distributor_ok = any(
                line.startswith("GRUB_DISTRIBUTOR=")
                and "Samurai Linux" in line
                for line in grub_default.splitlines()
            )
            if not distributor_ok:
                raise Failure("installed /etc/default/grub is not Samurai-branded")
            if 'GRUB_BACKGROUND="/usr/share/samurai/boot/grub-splash.png"' not in grub_default:
                raise Failure("installed GRUB does not use the Samurai background")
            if values.get("GRUB splash", "").strip() != "present":
                raise Failure("the installed system is missing the Samurai GRUB splash")
            if "Samurai Linux" not in values.get("motd", ""):
                raise Failure("the installed /etc/motd is not Samurai-branded")
            if "Samurai Linux" not in values.get("installed GRUB", ""):
                raise Failure("the installed GRUB menu does not mention Samurai Linux")
            self.log("Samurai branding verification passed")

        self.verify_security_defaults(values)
        self.verify_package_management()

        self.log("installed system verification passed")

    def verify_security_defaults(self, values: dict[str, str]) -> None:
        """Check the security controls as configured state on the installed system.

        0120-security.hook.chroot writes these files into the image, and a file
        that a service never loads would look identical in the repository, so
        every control is read back from systemd, nft, the kernel and apt.
        """
        unit_names = ["nftables.service", "apparmor.service", "apt-daily.timer", "apt-daily-upgrade.timer"]
        states = [line.strip() for line in values.get("security units", "").splitlines() if line.strip()]
        if len(states) != len(unit_names):
            raise Failure(f"expected {len(unit_names)} unit states, read {states!r}")
        inactive = [f"{name}={state}" for name, state in zip(unit_names, states) if state != "enabled"]
        if inactive:
            raise Failure(f"security units are not enabled on the installed system: {', '.join(inactive)}")
        self.log("nftables, apparmor and the apt periodic timers are all enabled")

        ruleset = values.get("packet filter", "")
        if "chain ingress" not in ruleset or "policy drop" not in ruleset:
            raise Failure(f"the default-deny input policy is not in the running ruleset:\n{ruleset}")
        self.log("the running ruleset denies unsolicited inbound traffic")

        if values.get("apparmor parameter", "").strip() != "Y":
            raise Failure(f"the kernel has AppArmor disabled: {values.get('apparmor parameter')!r}")
        profiles = values.get("apparmor profiles", "")
        if not profiles.startswith("profiles=") or profiles.split()[0].split("=")[1] == "0":
            raise Failure(f"AppArmor is enabled but loaded no profiles: {profiles!r}")
        # Reported, not asserted: Debian ships some profiles in complain mode and
        # claiming enforcing coverage we do not have is the mistake to avoid.
        self.log(f"apparmor profiles: {profiles}")

        if '"1"' not in values.get("unattended upgrades", ""):
            raise Failure(
                "automatic security upgrades are switched off in the installed system: "
                f"{values.get('unattended upgrades')!r}"
            )
        # The switch above is worthless if no archive is allowed to upgrade from.
        # Two independent halves: the archive has to be configured, and the
        # origin the updater is told to accept has to name it. Debian's default
        # origin list is built from "${distro_id}", which this project's own
        # branding rewrites to Samurai, so an origin list copied from Debian
        # would match nothing here and would still look perfectly configured.
        sources = values.get("apt sources", "")
        if "trixie-security" not in sources:
            raise Failure(f"the installed system configures no Debian security archive:\n{sources}")
        if "unattended-upgrades ii" not in values.get("updater package", ""):
            raise Failure(
                "the installed system does not have the unattended-upgrades package: "
                f"{values.get('updater package')!r}"
            )
        origins = values.get("upgrade origins", "")
        if "security" not in origins:
            raise Failure(f"unattended upgrades are enabled for no security origin: {origins!r}")
        if "Debian:trixie-security" not in origins:
            raise Failure(f"the effective Allowed-Origins does not name the security archive: {origins!r}")
        # Reported, not asserted: the updater cannot build its cache without any
        # downloaded index, and this VM has no network by design, so a dry run
        # here measures how far the mechanism gets, not whether it can patch.
        self.log(f"package indexes in the installed system: {values.get('package indexes', '').strip()}")
        self.log("unattended security upgrades name Debian:trixie-security as an allowed origin")

        # journald only keeps a journal on disk once it has created its
        # machine-id directory, so the directory is the proof Storage=persistent
        # was read rather than shipped and ignored.
        journal = values.get("journal storage", "")
        if "No such file or directory" in journal or not journal.strip():
            raise Failure(f"the installed system keeps no persistent journal: {journal!r}")
        self.log("journald is writing a persistent journal")

        modes = [line.strip() for line in values.get("policy file modes", "").splitlines() if line.strip()]
        if modes != ["440 root", "644 root"]:
            raise Failure(f"security policy files have the wrong ownership or mode: {modes!r}")
        if values.get("passwordless sudoers", "").strip() != "none":
            raise Failure(
                "the installed system grants sudo without a password: "
                f"{values.get('passwordless sudoers')!r}"
            )
        self.log("sudo and nftables policy files are root-owned and not group-writable")

    def verify_package_management(self) -> None:
        """Run the package tools on the installed system, not just on a dev box.

        smoke.sh proves these scripts parse and refuse bad input. Only a real
        dpkg, apt and /etc can prove samurai-profile resolves and
        samurai-recovery captures and puts back. The test VM has no network on
        purpose, so anything that would have to download a .deb is reported as
        unverified instead of being dressed up as a pass.
        """
        report: list[str] = []

        def run(command: str, label: str, timeout: float = 180) -> str:
            output = self.serial.command(command, timeout=timeout, check=False)
            report.append(f"### {label}\n$ {command}\n{output}\n")
            return output

        profiles = run("samurai-profile list", "profile list")
        for expected in ("debug", "containers", "virtualization"):
            if expected not in profiles:
                raise Failure(f"the installed samurai-profile does not offer {expected}:\n{profiles}")
        refused = run("samurai-profile packages no-such-profile 2>&1", "unknown profile")
        if "Unknown profile" not in refused:
            raise Failure(f"samurai-profile accepted a profile it does not know: {refused!r}")
        # apt can only answer about a profile if the image kept package lists;
        # the installer is allowed to clean them, so a bare archive is reported
        # rather than asserted. The build hook resolves every profile anyway.
        plan = run("samurai-profile plan debug 2>&1 | tail -n 30", "profile plan")
        if "Unable to locate package" in plan:
            self.log("the installed system keeps no package lists, so profile resolution is build-time only")
        elif "gdb" not in plan:
            raise Failure(f"apt was asked to plan the debug profile and never mentioned it:\n{plan}")
        else:
            self.log("samurai-profile resolved the debug profile against the installed system's apt")

        snapshot = run("samurai-recovery snapshot installtest 2>&1 | tail -n 3", "recovery snapshot", timeout=600)
        lines = [line for line in snapshot.splitlines() if line.startswith("Snapshot: ")]
        if not lines:
            raise Failure(f"samurai-recovery recorded no snapshot:\n{snapshot}")
        store = lines[-1].split("Snapshot: ", 1)[1].strip()
        contents = run(
            f"cd {store} && for a in etc.tar.gz package-versions.tsv manual-selections.txt "
            'enabled-units.txt kernels.txt meta.txt SHA256SUMS; do '
            'if [ -s "$a" ]; then echo "$a=present"; else echo "$a=missing"; fi; done',
            "snapshot contents",
        )
        if "missing" in contents:
            raise Failure(f"the snapshot is incomplete:\n{contents}")
        # Same query, twice: the manifest and dpkg have to agree. The store is
        # 0700 root, so this is also the check that the privileged redirects
        # wrote a complete file rather than failing quietly into a directory the
        # calling user cannot open.
        recorded = run(
            f"printf 'manifest=%s dpkg=%s\\n' \"$(wc -l < {store}/package-versions.tsv)\" "
            '"$(dpkg-query -W -f=\'${Package}\\n\' 2>/dev/null | grep -c .)"',
            "snapshot manifest size",
        )
        counts = [int(word) for word in recorded.replace("=", " ").split() if word.isdigit()]
        if len(counts) != 2 or counts[0] != counts[1]:
            raise Failure(f"the snapshot manifest does not match dpkg: {recorded!r}")
        self.log(f"the snapshot recorded all {counts[1]} installed packages")

        verified = run(f"samurai-recovery verify {store} 2>&1 | tail -n 12", "snapshot integrity")
        if "OK" not in verified or "verified:" not in verified:
            raise Failure(f"the snapshot does not verify:\n{verified}")

        # Damage a policy file on purpose and put it back. A restore that is
        # never exercised is a restore that has never worked, and the firewall
        # configuration is the right victim: the marker is not valid nft syntax,
        # so nft --check afterwards proves the restored file really is the one
        # from the snapshot rather than something that merely looks populated.
        marker = "SAMURAI-INSTALLTEST-MARKER"
        run(
            f"printf '%s\\n' '{marker}' >> /etc/nftables.conf && grep -c '{marker}' /etc/nftables.conf",
            "marker appended",
        )
        restored = run(
            f"samurai-recovery restore-etc {store} /etc/nftables.conf 2>&1 | tail -n 5",
            "restore /etc",
            timeout=300,
        )
        if "Restored" not in restored:
            raise Failure(f"restore-etc reported no restore:\n{restored}")
        remaining = run(f"grep -c '{marker}' /etc/nftables.conf 2>&1 || true", "marker after restore")
        if remaining.strip() != "0":
            raise Failure(f"the damaged firewall policy is still in place: {remaining!r}")
        checked = run("nft -c -f /etc/nftables.conf 2>&1 && echo RESTORED_VALID", "restored policy syntax")
        if "RESTORED_VALID" not in checked:
            raise Failure(f"the restored nftables.conf does not parse:\n{checked}")
        self.log("restore-etc returned the damaged firewall policy intact")

        # Nothing was installed since the snapshot, so this is the honest limit
        # of what an offline guest can show: the diff mechanism runs and finds
        # the set unchanged. Reinstalling a package that appeared later needs a
        # networked run, and is recorded as such in known-limitations.
        rollback = run(f"samurai-recovery restore-packages {store} 2>&1 | tail -n 5", "package rollback")
        if "Nothing has been installed since" not in rollback:
            raise Failure(f"restore-packages saw a change with nothing installed:\n{rollback}")
        run("samurai-recovery prune 2>&1 | tail -n 3", "snapshot pruning")

        (self.work / "installed-package-management.txt").write_text("\n".join(report), encoding="utf-8")
        self.log("package management and recovery verified on the installed system")

    # -- desktop (Plasma session) verification --------------------------

    def shutdown_guest(self) -> None:
        assert self.serial
        self.serial.command("sync", timeout=120, check=False)
        # No marker: poweroff tears the shell down before it could be printed.
        self.serial.sendline("poweroff -f")
        self.wait_for_guest_exit()
        self.stop_vm()

    def enable_desktop_autologin(self) -> None:
        """Log samurai straight into Plasma, on the test disk only.

        The shipped image must keep asking for a password; this drop-in exists so
        the harness can inspect a running compositor without clicking through
        SDDM over VNC.
        """
        assert self.serial
        listing = self.serial.command(
            "for d in /usr/share/xsessions /usr/share/wayland-sessions; do "
            'for f in "$d"/*.desktop; do [ -e "$f" ] && echo "$f"; done; done 2>/dev/null || true',
            check=False,
        )
        self.log("available sessions:\n" + listing)
        session = self.desktop_session
        if not session:
            files = [line.strip() for line in listing.splitlines() if line.strip().endswith(".desktop")]
            if not files:
                raise Failure("the installed system has no display manager session files")
            # Prefer X11: MangoHUD is documented to be unreliable on Wayland.
            x11 = [f for f in files if "/xsessions/" in f]
            session = Path(x11[0] if x11 else files[0]).name
        # Calamares' displaymanager module writes [Autologin] Session=plasma to
        # /etc/sddm.conf, and SDDM loads /etc/sddm.conf *after* every drop-in
        # (ConfigBase::load), so that key outvoted the test's zz-... file in run
        # 42283033517: the installed desktop came up on Wayland even though the
        # test had asked for plasmax11. Disable every Session= key the image
        # carries first, exactly as x11_autologin() does on the live image.
        self.serial.command(
            'for f in /etc/sddm.conf /etc/sddm.conf.d/*.conf; do '
            '[ -f "$f" ] || continue; '
            'grep -qE "^[[:space:]]*[Ss]ession[[:space:]]*=" "$f" || continue; '
            'cp -a "$f" "$f.orig.install-test" 2>/dev/null || true; '
            'sed -E -i \'s/^([[:space:]]*)([Ss]ession[[:space:]]*=.*)$/\\1# \\2/\' "$f"; '
            'echo "disabled the Session= keys in $f"; done',
            timeout=60,
            check=False,
        )
        # SDDM matches [Autologin] Session against the session *name*, so the
        # ".desktop" suffix has to go: passing "plasmax11.desktop" made SDDM
        # ignore the request and fall back to its Wayland default.
        session = session.removesuffix(".desktop")
        self.serial.command("mkdir -p /etc/sddm.conf.d", timeout=30)
        self.serial.write_file(
            # Written last in name order on purpose: the live image's own
            # configuration outvoted a test drop-in named "99-..." in run
            # 42112234958, so a test-only drop-in takes the end of the alphabet.
            "/etc/sddm.conf.d/zz-install-test-autologin.conf",
            f"[Autologin]\nUser=samurai\nSession={session}\n",
        )
        self.log(f"enabled test-only SDDM autologin into {session!r}")
        configured = self.serial.command(
            "for f in /etc/sddm.conf /etc/sddm.conf.d/*.conf; do "
            '[ -f "$f" ] || continue; echo "== $f"; cat "$f"; done 2>&1 | head -n 40',
            timeout=60,
            check=False,
        )
        self.log("SDDM configuration for the desktop check:\n" + configured)
        # The image ships SDDM but nothing enables the unit, so an installed
        # system boots to a text console and plasmashell never exists.
        self.serial.command("systemctl enable sddm >/dev/null 2>&1 || true", timeout=60, check=False)
        enabled = self.serial.command(
            "printf 'SDDM_ENABLED=%s\\n' \"$(systemctl is-enabled sddm 2>&1)\"", timeout=60, check=False
        )
        if "SDDM_ENABLED=enabled" not in enabled:
            raise Failure(f"SDDM would not start the desktop session: {enabled!r}")

    def session_command(self, command: str, timeout: float = 180) -> str:
        """Run a command as samurai inside the desktop session.

        The serial shell has no session bus, and Plasma's own tools cannot reach
        KWin without it, so the environment is copied from plasmashell itself.
        """
        assert self.serial
        env = " ".join(f"{k}={shlex.quote(v)}" for k, v in self.session_env.items())
        return self.serial.command(
            f"sudo -u samurai env HOME=/home/samurai {env} bash -lc {shlex.quote(command)}",
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _distinct_colors(path: Path, size: tuple[int, int] = (80, 50)) -> int:
        from PIL import Image

        with Image.open(path) as image:
            sample = image.convert("RGB").resize(size)
            return len({tuple(px) for px in sample.getdata()})

    # Metrics the published performance claims are allowed to rest on. A core
    # metric that came back "unavailable" means the harness measured nothing, so
    # the run must not be reported as a pass.
    CORE_METRICS = (
        "memory_used",
        "cpu_idle",
        "units_enabled",
        "services_running",
        "sha256_mib_per_s",
        "rootfs_used",
    )

    def measure_performance(self) -> dict[str, str]:
        """Read the running cost of the installed desktop off the guest itself.

        docs/performance.md may only publish what this returns. The script runs
        inside the live Plasma session, so the numbers describe a desktop a user
        would actually see, and every value travels with the command and host
        that produced it.
        """
        assert self.serial
        script_path = Path(__file__).resolve().parent / "measure-performance.sh"
        script = script_path.read_text(encoding="utf-8")
        self.serial.write_file("/usr/local/bin/samurai-measure-performance.sh", script)
        self.serial.command("chmod 0755 /usr/local/bin/samurai-measure-performance.sh", timeout=30)
        out = "/tmp/samurai-performance"
        body = self.session_command(
            f"rm -rf {out} && bash /usr/local/bin/samurai-measure-performance.sh "
            f"--out-dir {out} --cpu-mib 64 --disk-mib 64 --sample-seconds 5",
            timeout=600,
        )
        report = self.serial.pull_file(f"{out}/performance.txt", "performance report")
        if not report:
            raise Failure(f"the installed system produced no performance report:\n{body}")
        (self.work / "performance.txt").write_bytes(report)

        metrics: dict[str, str] = {}
        for line in report.decode("utf-8", errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[0] != "label":
                metrics[parts[0]] = parts[1]
        missing = [name for name in self.CORE_METRICS if metrics.get(name, "").lower() in ("", "unavailable", "skipped")]
        if missing:
            raise Failure(
                "these core performance metrics were never measured, so the run cannot "
                f"be called a pass: {', '.join(missing)}\n{body}"
            )
        self.log("measured: " + ", ".join(f"{k}={v}" for k, v in sorted(metrics.items())))
        return metrics

    def verify_desktop(self) -> None:
        self.start_reboot_vm("desktop")
        assert self.serial

        pid = ""
        report: list[str] = []
        try:
            self.serial.login("samurai", self.password, timeout=self.reboot_timeout)
            self.serial.root_shell(self.password, timeout=180)

            found = self.serial.command(
                "pid=; for i in $(seq 1 150); do pid=$(pgrep -u samurai -f plasmashell | head -1); "
                '[ -n "$pid" ] && break; sleep 2; done; echo "pid=${pid:-none}"',
                timeout=340,
                check=False,
            )
            match = re.search(r"pid=(\d+)", found)
            if not match:
                journal = self.serial.command(
                    "journalctl -b -u sddm --no-pager 2>/dev/null | tail -n 60 || true",
                    check=False,
                )
                raise Failure(
                    "plasmashell never started, so the desktop cannot be verified; "
                    f"sddm journal tail:\n{journal}"
                )
            pid = match.group(1)

            env_text = self.serial.command(
                f"tr '\\0' '\\n' < /proc/{pid}/environ | grep -E "
                "'^(DBUS_SESSION_BUS_ADDRESS|XDG_RUNTIME_DIR|DISPLAY|WAYLAND_DISPLAY"
                "|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP|XAUTHORITY)=' || true",
                check=False,
            )
            for line in env_text.splitlines():
                key, sep, value = line.partition("=")
                if sep and key:
                    self.session_env[key] = value
            self.log(f"desktop session environment: {self.session_env}")
            if not (self.session_env.get("DISPLAY") or self.session_env.get("WAYLAND_DISPLAY")):
                raise Failure(f"the session exposes no display: {env_text!r}")

            def record(label: str, output: str) -> None:
                report.append(f"### {label}\n{output}\n")
                self.log(f"{label}: {output[:1500]}")

            record("sddm session history", self.serial.command(
                "journalctl -b -u sddm --no-pager 2>/dev/null | "
                "grep -E 'Session started|Starting (X11|Wayland) user session' | tail -n 6 || true",
                check=False,
            ))

            # Any scheduled blanking would hide the desktop from the capture
            # below, and the screenshots are the only proof that a person would
            # see something.
            self.vnc.wake()

            schemes = self.session_command("plasma-apply-colorscheme --list-schemes 2>&1 || true")
            record("color schemes known to Plasma", schemes)
            # Gated, not just logged: a scheme file that Plasma's own tool cannot
            # see would make every check below pass on a theme the user could
            # never pick. Matched on the theme word because --list-schemes prints
            # the scheme's Name= ("Samurai Kuro") while kdeglobals records the
            # file basename ("samurai-kuro").
            for scheme in ("kuro", "shiro"):
                if scheme not in schemes.lower():
                    raise Failure(
                        f"Plasma does not know the {scheme} color scheme, so the shipped "
                        f"scheme files are not usable:\n{schemes}"
                    )
            record("gamemode daemon", self.session_command(
                "systemctl --user status gamemoded --no-pager 2>&1 | head -n 8 || true"))

            # A desktop with no GL/EGL provider cannot composite, and that is what
            # really broke run 17: the image shipped Qt but no Mesa driver, so KWin
            # logged "egl: failed to create dri2 screen". Gated because every theme
            # check below depends on a working renderer. The probe follows the
            # session: glxinfo needs an X server and this image logs into Wayland.
            session_type = self.session_env.get("XDG_SESSION_TYPE", "").lower()
            record("session type", session_type or "unknown")
            glx = self.session_command("glxinfo -B 2>&1 | head -n 20 || true")
            record("glxinfo -B", glx)
            egl = self.session_command(
                "eglinfo 2>&1 | grep -E 'EGL vendor string|EGL driver name|"
                "OpenGL (core|ES) profile renderer' | head -n 6 || true"
            )
            record("eglinfo renderer", egl)
            problem = renderer_problem(session_type, glx, egl)
            if problem:
                raise Failure(
                    f"{problem} (session {session_type or 'unknown'}):\n"
                    f"glxinfo said:\n{glx}\neglinfo said:\n{egl}"
                )

            # samurai-theme waits up to 120 s for plasmashell's script engine
            # (dbus-send), then tries gdbus and the stock tool, so this call can
            # legitimately outlast the default command timeout on a slow guest.
            applied = self.session_command("samurai-theme set shiro 2>&1", timeout=360)
            record("samurai-theme set shiro", applied)
            if "Applied Samurai shiro color scheme" not in applied:
                raise Failure(
                    "samurai-theme could not apply a color scheme to a live Plasma session:\n"
                    + applied
                )
            if "Applied wallpaper shiro.jpg" not in applied:
                # samurai-theme hides each client's output, so ask Plasma
                # directly; without this the log only says a wallpaper was not
                # applied.
                reason = self.session_command(
                    "plasma-apply-wallpaperimage /usr/share/backgrounds/samurai/shiro.jpg 2>&1; "
                    "echo rc=$?",
                    timeout=180,
                )
                record("plasma-apply-wallpaperimage direct", reason)
                raise Failure(
                    "samurai-theme did not apply the Shiro wallpaper:\n" + applied
                    + f"\nplasma-apply-wallpaperimage said:\n{reason}"
                )

            config = self.session_command(
                "for g in KDE General; do printf '%s=' \"$g\"; kreadconfig6 --file kdeglobals "
                '--group "$g" --key ColorScheme 2>/dev/null; echo; done'
            )
            record("kdeglobals ColorScheme", config)
            if "samurai-shiro" not in config:
                raise Failure(f"Plasma did not record the shiro scheme in kdeglobals: {config!r}")

            gaming = self.session_command("samurai-gaming status 2>&1")
            record("samurai-gaming status", gaming)
            for tool in ("mangohud", "gamemoderun"):
                if f"{tool}: installed" not in gaming:
                    raise Failure(f"{tool} is not usable on the installed system:\n{gaming}")

            libraries = self.serial.command(
                "dpkg -L mangohud 2>/dev/null | grep -E '\\.so$' | head -n 5 || true",
                check=False,
            )
            record("mangohud interposer libraries", libraries)
            if ".so" not in libraries:
                raise Failure("the mangohud package ships no interposer library")

            # Recorded, not gated: an overlay needs a real GL/Vulkan app and a
            # GPU, neither of which QEMU's software renderer provides.
            record("mangohud preload smoke", self.session_command(
                "MANGOHUD=1 mangohud /bin/true 2>&1; echo rc=$?", timeout=120))

            metrics = self.measure_performance()
            record(
                "measured performance",
                "\n".join(f"{name} = {metrics[name]}" for name in sorted(metrics))
                + "\nfull report, each value with the command that produced it: performance.txt",
            )

            self.vnc.wake()
            shot = self.vnc.stable_capture("09-desktop.png")
            colors = self._distinct_colors(shot)
            record("desktop screenshot", f"{shot.name}: {colors} distinct colors sampled")
            if colors < 12:
                raise Failure(
                    f"the desktop capture is blank ({colors} distinct colors); "
                    "the compositor is not rendering"
                )
        finally:
            (self.work / f"installed-desktop-{pid or 'early'}.txt").write_text(
                "\n".join(report), encoding="utf-8"
            )

        self.log("desktop verification passed")
        self.shutdown_guest()

    # -- orchestration -------------------------------------------------

    def run(self) -> None:
        for tool in ("qemu-system-x86_64", "qemu-img", "vncdo", "tesseract"):
            if not shutil.which(tool):
                raise Failure(f"required tool is not installed: {tool}")
        if not self.iso.is_file():
            raise Failure(f"ISO not found: {self.iso}")

        self.log(f"ISO: {self.iso}")
        self.log(f"work directory: {self.work}")
        self.start_install_vm()
        try:
            assert self.serial
            self.serial.login("samurai", "live")
            self.serial.root_shell()
            self.root_ready = True
            self.configure_calamares_for_test()
            self.launch_calamares()
            self.drive_installer()
        except Exception:
            self.copy_calamares_log()
            raise
        self.copy_calamares_log()
        self.verify_boot_loader()
        self.finish_install()
        self.verify_installed_system()
        if self.desktop:
            # The root shell from the verification step is still open.
            self.enable_desktop_autologin()
            self.shutdown_guest()
            self.verify_desktop()
        else:
            self.shutdown_guest()
        self.log("install test passed")


def _fake_shell(
    sock: socket.socket,
    sudo_prompt: bytes = b"[sudo] password for samurai: ",
    sudo_password: str | None = None,
) -> None:
    """A tiny tty for the self-test: echoes input and answers markers."""
    pending = b""
    sudo = {"asking": False, "tries": 0}
    while True:
        try:
            chunk = sock.recv(4096)
        except OSError:
            return
        if not chunk:
            return
        pending += chunk
        while b"\r" in pending:
            line, pending = pending.split(b"\r", 1)
            text = line.decode("utf-8", errors="replace")
            sock.sendall((text + "\r\n").encode())
            if text.strip() == "sudo -i":
                # Mimic sudo: prompt, then drop the first password typed at it
                # (sudo flushes queued tty input with TCSAFLUSH).
                sudo["asking"] = True
                sudo["tries"] = 0
                sock.sendall(sudo_prompt)
                continue
            if sudo["asking"]:
                sudo["tries"] += 1
                if sudo["tries"] == 1 and sudo_password is None:
                    sock.sendall(b"\r\n" + sudo_prompt)
                elif sudo_password is not None and text != sudo_password:
                    sock.sendall(b"\r\nSorry, try again.\r\n" + sudo_prompt)
                else:
                    sudo["asking"] = False
                    sock.sendall(b"\r\nroot@samurai:~# ")
                continue
            if text.strip() == "echo password":
                sock.sendall(b"Password: ")
                continue
            if "& echo __SAMURAI_DONE_" in text:
                marker = text.rsplit("__SAMURAI_DONE_", 1)[1].split(":")[0]
                sock.sendall(f"__SAMURAI_DONE_{marker}:4242\r\n".encode())
                continue
            if "; echo __SAMURAI_DONE_" in text:
                head, _, tail = text.rpartition("; echo ")
                marker = tail.split(":")[0].split(".")[0]
                prefix = f"echo {marker}.BEGIN; "
                command = head[len(prefix) :] if head.startswith(prefix) else head
                answer = f"{marker}.BEGIN\r\n"
                if command.strip() == "echo hello":
                    answer += "hello\r\n"
                elif command.strip() == "id -u":
                    answer += "0\r\n"
                elif command.strip() == "stat -c '%U' /home/samurai":
                    # Replay the redraw bash wrote over the run-16 serial
                    # console: cursor motions and a stray "?" after the echo.
                    answer = "\r\x1b[A" + "\x1b[C" * 60 + "\x1b[K?\r\n" + answer + "samurai\r\n"
                sock.sendall((answer + f"{marker}.END:0\r\n").encode())
            else:
                sock.sendall(b"$ ")


def self_test() -> int:
    host, guest = socket.socketpair()
    thread = threading.Thread(target=_fake_shell, args=(guest,), daemon=True)
    thread.start()
    failures = 0

    with tempfile.TemporaryDirectory() as tmp:
        log = Log(Path(tmp) / "self-test.log")
        console = SerialConsole(Path(tmp) / "transcript.log", log, sock=host)
        try:
            console.sendline("echo password")
            output, match = console.expect("Password:", 5, "password prompt")
            if not output.startswith("echo password"):
                print(f"FAIL: expect() dropped pre-match output: {output!r}", file=sys.stderr)
                failures += 1
            if match.group(0) != "Password:":
                print("FAIL: expect() matched the wrong text", file=sys.stderr)
                failures += 1
            if console.command("echo hello") != "hello":
                print("FAIL: command() did not return its output", file=sys.stderr)
                failures += 1
            if console.command("stat -c '%U' /home/samurai") != "samurai":
                print(
                    "FAIL: command() let a readline redraw into the output of a single-line value",
                    file=sys.stderr,
                )
                failures += 1
            if console.background("echo background") != 4242:
                print("FAIL: background() did not return the shell PID", file=sys.stderr)
                failures += 1
            empty = console.command("true")
            if empty:
                print(f"FAIL: command() returned tty noise for empty output: {empty!r}", file=sys.stderr)
                failures += 1
            try:
                console.root_shell("", timeout=10)
            except Failure as exc:
                print(
                    f"FAIL: root_shell() did not recover from a dropped password: {exc}",
                    file=sys.stderr,
                )
                failures += 1
            if console.command("id -u") != "0":
                print("FAIL: root_shell() did not reach the fake root shell", file=sys.stderr)
                failures += 1
        finally:
            console.close()
            log.close()
    guest.close()

    # A rejected or unmatched sudo password must fail loudly with the bytes the
    # guest actually wrote, not hang and then report a trimmed tail.
    host, guest = socket.socketpair()
    thread = threading.Thread(
        target=_fake_shell,
        args=(guest,),
        kwargs={"sudo_password": "not-the-password"},
        daemon=True,
    )
    thread.start()
    with tempfile.TemporaryDirectory() as tmp:
        log = Log(Path(tmp) / "self-test.log")
        console = SerialConsole(Path(tmp) / "transcript.log", log, sock=host)
        try:
            console.root_shell("live", timeout=10)
        except Failure as exc:
            if "Sorry, try again" not in str(exc) or "raw serial bytes" not in str(exc):
                print(
                    f"FAIL: a rejected password did not report the serial bytes: {exc}",
                    file=sys.stderr,
                )
                failures += 1
        else:
            print("FAIL: root_shell() accepted a password sudo rejected", file=sys.stderr)
            failures += 1
        finally:
            console.close()
            log.close()
    guest.close()

    # The renderer gate has to read the session it is in. Run 42129297987
    # failed here: the installed image was on Wayland, glxinfo could not open a
    # display, and a working Mesa stack (eglinfo: kms_swrast) was reported as a
    # missing DRI driver.
    wayland_egl = "EGL vendor string: Mesa Project\nEGL driver name: kms_swrast\n"
    x11_glx = "OpenGL renderer string: llvmpipe (LLVM 19.1.7, 256 bits)\n"
    # What `glxinfo -B` actually prints on this image (run 42381460039): the
    # brief form has no "OpenGL renderer string" line at all.
    x11_glx_brief = (
        "Extended renderer info (GLX_MESA_query_renderer):\n"
        "    Vendor: Mesa (0xffffffff)\n"
        "    Device: llvmpipe (LLVM 19.1.7, 256 bits) (0xffffffff)\n"
    )
    for session_type, glx, egl, expected in (
        ("wayland", "Error: unable to open display :0\n", wayland_egl, None),
        ("wayland", "", "EGL vendor string: Mesa Project\n", "no EGL driver"),
        ("wayland", "", "EGL driver name: kms_swrast\n", "no Mesa EGL vendor"),
        ("x11", x11_glx, "", None),
        ("x11", x11_glx_brief, "", None),
        ("x11", "Error: unable to open display :0\n", wayland_egl, "no OpenGL renderer"),
    ):
        problem = renderer_problem(session_type, glx, egl)
        if (expected is None and problem is not None) or (expected and expected not in problem):
            print(
                f"FAIL: renderer gate for {session_type} returned {problem!r}, wanted {expected!r}",
                file=sys.stderr,
            )
            failures += 1

    if failures == 0:
        print("install-test self-test passed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("iso", nargs="?", help="Samurai Linux ISO to install")
    parser.add_argument(
        "--work-dir",
        default=str(Path(__file__).resolve().parent / "install-test"),
        help="directory for the disk, logs, and screenshots",
    )
    parser.add_argument("--disk-size", default="20G", help="size of the blank target disk")
    parser.add_argument("--timeout", type=int, default=3600, help="seconds allowed for the install")
    parser.add_argument(
        "--reboot-timeout", type=int, default=900, help="seconds allowed for the installed boot"
    )
    parser.add_argument("--vnc-port", type=int, default=5901, help="QEMU VNC port (5901+)")
    parser.add_argument(
        "--password",
        default="Kuro2026Qz",
        help="password for the installed samurai account",
    )
    parser.add_argument(
        "--branded",
        action="store_true",
        help="require Samurai branding on the installed system",
    )
    parser.add_argument(
        "--desktop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="boot the installed system into Plasma and verify the desktop "
        "(use --no-desktop to stop at the serial-console checks)",
    )
    parser.add_argument(
        "--desktop-session",
        default="",
        help="SDDM session file to auto-login for the desktop check; empty picks "
        "the first X11 session, else the first session found",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="test the serial console logic without QEMU and exit",
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.iso:
        parser.error("an ISO path is required unless --self-test is used")

    test = InstallerTest(args)
    try:
        test.run()
    except Exception as exc:  # noqa: BLE001 - report everything as a CI failure
        test.log(f"FAILED: {exc}")
        try:
            test.report_qemu_exit()
        except Exception:  # noqa: BLE001
            pass
        try:
            test.vnc.capture("failure-final.png")
        except Exception:  # noqa: BLE001
            pass
        try:
            test.copy_calamares_log()
        except Exception:  # noqa: BLE001
            pass
        test.stop_vm()
        test.log.close()
        print(f"\nInstall test failed: {exc}", file=sys.stderr)
        return 1
    test.log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
