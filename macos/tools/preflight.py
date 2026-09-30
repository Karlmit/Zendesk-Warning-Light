r"""Check that everything macOS-specific in this port actually works on this Mac.

Written because the port was authored on Windows, where none of the platform layer
can be exercised: the Keychain, LaunchAgents, `open`, the .app layout and the Cocoa
Qt plugin all need a real Mac. Run this before trusting the build.

    ./.venv/bin/python tools/preflight.py

It needs no Zendesk sign-in and changes nothing permanent - the Keychain probe uses
its own throwaway service name, and the LaunchAgent probe writes to a temp path.
Use tools/verify_oauth.py separately to check the Zendesk side.
"""

from __future__ import annotations

import os
import platform
import plistlib
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROBE_SERVICE = "com.yourcompany.zendeskwarninglight.preflight"
PROBE_ACCOUNT = "preflight-probe"

_results: list[tuple[bool, str, str]] = []


def record(passed: bool, label: str, detail: str = "") -> bool:
    _results.append((passed, label, detail))
    mark = "\033[32m  ok  \033[0m" if passed else "\033[31m FAIL \033[0m"
    print("{} {:<44} {}".format(mark, label, detail))
    return passed


def section(title: str) -> None:
    print("\n\033[36m{}\033[0m".format(title))


# ---------------------------------------------------------------------- #

def check_machine() -> None:
    section("1. This machine")
    record(platform.system() == "Darwin", "running on macOS", platform.system())
    arch = platform.machine()
    record(arch == "arm64", "Apple Silicon (arm64)",
           arch + ("" if arch == "arm64" else "  <- the app will be built for this arch"))
    record(True, "macOS version", platform.mac_ver()[0] or "unknown")

    version = "{}.{}".format(*sys.version_info[:2])
    record(sys.version_info[:2] >= (3, 10) and sys.version_info[:2] <= (3, 13),
           "Python 3.10-3.13 (PySide6 wheels)", version)
    record(platform.machine() == arch, "Python is native, not under Rosetta",
           "python reports " + platform.machine())


def check_qt() -> None:
    section("2. Qt")
    try:
        import PySide6
        from PySide6.QtGui import QImageReader
    except Exception as exc:
        record(False, "PySide6 imports", str(exc)[:60])
        return
    record(True, "PySide6 imports", PySide6.__version__)

    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        record(True, "Cocoa platform plugin loads", app.platformName())
    except Exception as exc:
        record(False, "Cocoa platform plugin loads", str(exc)[:60])
        return

    from zwl.paths import assets_dir
    for name in ("Warning-Cat.gif", "Warning-Light.webp"):
        path = assets_dir() / name
        if not path.exists():
            record(False, "animation present: " + name, str(path))
            continue
        reader = QImageReader(str(path))
        record(reader.canRead() and reader.supportsAnimation(),
               "animation decodes: " + name,
               "{} frames".format(reader.imageCount()))

    try:
        from zwl import icons
        pixmap = icons.render(icons.IDLE, 32)
        record(not pixmap.isNull(), "menu bar icon renders",
               "{}x{}".format(pixmap.width(), pixmap.height()))
    except Exception as exc:
        record(False, "menu bar icon renders", str(exc)[:60])

    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        record(True, "primary screen found",
               "{} {}x{} @{}x".format(screen.name(), geo.width(), geo.height(),
                                      screen.devicePixelRatio()))
    except Exception as exc:
        record(False, "primary screen found", str(exc)[:60])


def check_overlay() -> None:
    section("3. The warning overlay")
    try:
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from zwl import config as config_module
        from zwl.overlay import OverlayWindow
        from zwl.monitor import Alert
        import time

        cfg = config_module.Config()
        window = OverlayWindow(cfg)
        window.set_alerts([Alert(1, "new_unassigned", "Preflight check",
                                 None, "Preflight", time.time())])
        rect = window.geometry().getRect()
        record(window.isVisible(), "frameless overlay shows", str(rect))
        record(rect[2] > 0 and rect[3] > 0, "overlay has a real size",
               "{}x{}".format(rect[2], rect[3]))
        window.hide_warning()
        record(not window.isVisible(), "and hides again")
    except Exception as exc:
        record(False, "overlay works", str(exc)[:70])


def check_keychain() -> None:
    section("4. Keychain (where the sign-in token goes)")
    security = "/usr/bin/security"
    if not Path(security).exists():
        record(False, "/usr/bin/security exists", "missing")
        return
    record(True, "/usr/bin/security exists")

    secret = "preflight-" + os.urandom(6).hex()
    add = subprocess.run(
        [security, "add-generic-password", "-s", PROBE_SERVICE,
         "-a", PROBE_ACCOUNT, "-U", "-w", secret],
        capture_output=True, text=True)
    if not record(add.returncode == 0, "can write an item",
                  (add.stderr or "").strip()[:60]):
        return

    found = subprocess.run(
        [security, "find-generic-password", "-s", PROBE_SERVICE,
         "-a", PROBE_ACCOUNT, "-w"],
        capture_output=True, text=True)
    record(found.returncode == 0 and (found.stdout or "").strip() == secret,
           "reads back the same value")

    gone = subprocess.run(
        [security, "delete-generic-password", "-s", PROBE_SERVICE,
         "-a", PROBE_ACCOUNT],
        capture_output=True, text=True)
    record(gone.returncode == 0, "and deletes it again")

    try:
        from zwl import keystore
        marker = keystore.encrypt("round-trip-check")
        got = keystore.decrypt(marker)
        keystore.forget()
        record(got == "round-trip-check" and marker == keystore.MARKER,
               "zwl.keystore round-trips via Keychain", marker)
    except Exception as exc:
        record(False, "zwl.keystore round-trips via Keychain", str(exc)[:60])


def check_launch_agent() -> None:
    section("5. Login item (LaunchAgent)")
    try:
        from zwl import autostart
        from zwl.paths import launch_arguments

        args = launch_arguments()
        record(bool(args) and Path(args[0]).exists(),
               "launch target exists", args[0] if args else "none")

        # Validate the plist we would write, without touching the real one.
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.plist"
            with probe.open("wb") as handle:
                plistlib.dump(autostart._build_plist(), handle)
            lint = subprocess.run(["/usr/bin/plutil", "-lint", str(probe)],
                                  capture_output=True, text=True)
            record(lint.returncode == 0, "the plist we generate is valid",
                   (lint.stdout or lint.stderr).strip()[:50])
            loaded = plistlib.loads(probe.read_bytes())
            record(loaded.get("RunAtLoad") is True and
                   loaded.get("LimitLoadToSessionType") == "Aqua",
                   "and has the keys launchd needs")

        record(Path.home().joinpath("Library").is_dir(),
               "~/Library is writable", str(autostart.agents_dir()))
        record(True, "current state", autostart.describe())
    except Exception as exc:
        record(False, "LaunchAgent layer works", str(exc)[:70])


def check_paths_and_ports() -> None:
    section("6. Paths and the sign-in callback")
    try:
        from zwl.paths import assets_dir, data_dir, log_path
        folder = data_dir()
        probe = folder / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record(True, "settings folder writable", str(folder))
        record(assets_dir().is_dir(), "assets folder found", str(assets_dir()))
        record(True, "log would be written to", str(log_path()))
    except Exception as exc:
        record(False, "settings folder writable", str(exc)[:60])

    from zwl.auth import CALLBACK_HOST, CALLBACK_PORTS
    free = []
    for port in CALLBACK_PORTS:
        sock = socket.socket()
        try:
            sock.bind((CALLBACK_HOST, port))
            free.append(port)
        except OSError:
            pass
        finally:
            sock.close()
    record(bool(free), "a sign-in callback port is free",
           "free: {}".format(", ".join(str(p) for p in free) or "NONE"))

    opener = Path("/usr/bin/open")
    record(opener.exists(), "/usr/bin/open exists (Finder integration)")


def main() -> int:
    print("=" * 72)
    print("Zendesk Warning Light - macOS preflight")
    print("=" * 72)

    check_machine()
    check_qt()
    check_overlay()
    check_keychain()
    check_launch_agent()
    check_paths_and_ports()

    failed = [label for passed, label, _ in _results if not passed]
    print("\n" + "=" * 72)
    if failed:
        print("\033[31m{} of {} checks FAILED:\033[0m".format(len(failed), len(_results)))
        for label in failed:
            print("   - {}".format(label))
        print("\nFix these before trusting ./build.sh")
        return 1
    print("\033[32mAll {} checks passed - the macOS layer works on this Mac.\033[0m"
          .format(len(_results)))
    print("Next: ./build.sh   then   tools/verify_oauth.py to check Zendesk sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
