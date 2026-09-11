"""Start-at-login must understand a machine-wide install, not just a per-user one.

A machine-wide deployment (Intune in system context) writes the Run value under HKLM.
If the app only looked at HKCU it would report "off" while demonstrably starting at
login, and ticking the box would add a second Run entry.

The real registry is never touched: a fake winreg stands in.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zwl import autostart  # noqa: E402

_failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}  (got {!r}, expected {!r})".format(label, actual, expected))
        _failures.append(label)


HKLM = "HKLM"
HKCU = "HKCU"


class FakeWinreg:
    """Just enough winreg to exercise the branching, recording every write."""

    HKEY_LOCAL_MACHINE = HKLM
    HKEY_CURRENT_USER = HKCU
    KEY_READ = 1
    KEY_WRITE = 2
    KEY_WOW64_64KEY = 256
    REG_SZ = 1

    def __init__(self, values: dict[str, str]):
        self.values = dict(values)
        self.writes: list[tuple[str, str]] = []
        self.deletes: list[str] = []

    # -- reading -------------------------------------------------------- #

    class _Key:
        def __init__(self, parent, hive):
            self.parent, self.hive = parent, hive

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, hive, path, reserved=0, access=0):   # noqa: N802
        if hive not in self.values:
            raise FileNotFoundError(path)
        return self._Key(self, hive)

    def CreateKeyEx(self, hive, path, reserved=0, access=0):  # noqa: N802
        return self._Key(self, hive)

    def QueryValueEx(self, key, name):                     # noqa: N802
        if key.hive not in self.values:
            raise FileNotFoundError(name)
        return (self.values[key.hive], self.REG_SZ)

    # -- writing -------------------------------------------------------- #

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.writes.append((key.hive, value))
        self.values[key.hive] = value

    def DeleteValue(self, key, name):                      # noqa: N802
        self.deletes.append(key.hive)
        if key.hive in self.values:
            del self.values[key.hive]
        else:
            raise FileNotFoundError(name)


def use(values: dict[str, str]) -> FakeWinreg:
    fake = FakeWinreg(values)
    autostart._winreg = lambda: fake
    return fake


def run() -> None:
    print("\n1. Nothing set anywhere")
    use({})
    check("not enabled", autostart.is_enabled(), False)
    check("not machine-wide", autostart.is_machine_wide(), False)
    check("describe", autostart.describe(), "not set")

    print("\n2. Per-user only (a normal /CURRENTUSER install)")
    use({HKCU: r"C:\Users\x\AppData\Local\Programs\ZWL\ZWL.exe"})
    check("enabled", autostart.is_enabled(), True)
    check("not machine-wide", autostart.is_machine_wide(), False)
    check("describe names the scope", "set for you only" in autostart.describe(), True)

    print("\n3. REGRESSION: machine-wide only (an /ALLUSERS install)")
    use({HKLM: r"C:\Program Files\ZWL\ZWL.exe"})
    check("reported as enabled", autostart.is_enabled(), True)
    check("and as machine-wide", autostart.is_machine_wide(), True)
    check("describe says who set it",
          "by your administrator" in autostart.describe(), True)

    print("\n4. A machine-wide entry is never duplicated into HKCU")
    fake = use({HKLM: r"C:\Program Files\ZWL\ZWL.exe"})
    check("enabling reports satisfied", autostart.set_enabled(True), True)
    check("but wrote nothing", fake.writes, [])
    check("and deleted nothing", fake.deletes, [])

    print("\n5. A machine-wide entry cannot be turned off from the app")
    fake = use({HKLM: r"C:\Program Files\ZWL\ZWL.exe"})
    check("disabling is refused", autostart.set_enabled(False), False)
    check("HKLM left alone", fake.values.get(HKLM) is not None, True)
    check("nothing deleted", fake.deletes, [])

    print("\n6. Per-user toggling still works normally")
    fake = use({})
    check("enable succeeds", autostart.set_enabled(True), True)
    check("wrote to HKCU", [hive for hive, _ in fake.writes], [HKCU])
    check("now enabled", autostart.is_enabled(), True)
    check("disable succeeds", autostart.set_enabled(False), True)
    check("deleted from HKCU", fake.deletes, [HKCU])
    check("now off", autostart.is_enabled(), False)

    print("\n7. Disabling when it was never set is not an error")
    fake = use({})
    check("returns True", autostart.set_enabled(False), True)

    print("\n8. Both scopes set: machine-wide takes precedence")
    use({HKLM: r"C:\Program Files\ZWL\ZWL.exe", HKCU: r"C:\Users\x\ZWL.exe"})
    check("machine-wide wins", autostart.is_machine_wide(), True)
    check("describe mentions the administrator",
          "administrator" in autostart.describe(), True)


if __name__ == "__main__":
    run()
    print("\n" + "=" * 60)
    if _failures:
        print("{} FAILING CHECK(S): {}".format(len(_failures), ", ".join(_failures)))
        sys.exit(1)
    print("All checks passed.")
