"""Regression tests for the Groups tab.

A colleague on a plain agent account installed the app and the group list came up
empty. These pin down every way that could happen, because an empty picker with no
explanation is the worst outcome: it looks configured when it is not.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from zwl import auth as auth_module  # noqa: E402
from zwl import paths as paths_module  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
paths_module.data_dir = lambda: Path(_tmp.name)
auth_module.tokens_path = lambda: Path(_tmp.name) / "tokens.json"

from zwl.auth import SignedInUser, TokenStore  # noqa: E402
from zwl import modes  # noqa: E402
from zwl.config import Config  # noqa: E402
from zwl.modes import DayMode  # noqa: E402
from zwl.settings_ui import SettingsDialog  # noqa: E402

GROUPS = [
    {"id": 43806224142865, "name": "BL - Admin"},
    {"id": 15962684745105, "name": "Group - Example Co"},
    {"id": 18564583439761, "name": "NL - Helpdesk"},
    {"id": 25431951885841, "name": "NL - Billing"},
]
MINE = {43806224142865, 15962684745105}

_failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}  (got {!r}, expected {!r})".format(label, actual, expected))
        _failures.append(label)


def dialog(restricted: bool = False, watched=None, extra_modes=None,
           rules=None) -> SettingsDialog:
    tokens = TokenStore(base_url="https://example.zendesk.com")
    tokens._refresh_token = "rt"
    tokens.user = SignedInUser(id=12064701124497, name="Agent", email="a@x.se",
                               role="agent", restricted_agent=restricted)
    primary = DayMode(id="primary", name="Primary",
                      watched_group_ids=list(watched or []))
    for rule, value in (rules or {}).items():
        primary.set_rule(rule, value)
    cfg = Config(mode="primary", day_modes=[primary] + list(extra_modes or []),
                 schedule={k: "primary" for k in modes.WEEKDAY_KEYS})
    return SettingsDialog(cfg, tokens)


def rows(d: SettingsDialog) -> list[str]:
    return [d.group_list.item(i).text() for i in range(d.group_list.count())]


def greyed(d: SettingsDialog) -> list[str]:
    return [d.group_list.item(i).text() for i in range(d.group_list.count())
            if d.group_list.item(i).toolTip()]


def ticked(d: SettingsDialog) -> set[int]:
    return {int(d.group_list.item(i).data(Qt.UserRole))
            for i in range(d.group_list.count())
            if d.group_list.item(i).checkState() == Qt.Checked}


def run() -> None:
    print("\n1. Unrestricted agent, membership known (Lars-Goran's shape)")
    d = dialog(restricted=False)
    d._on_groups_loaded({"all": GROUPS, "mine": MINE, "error": ""})
    check("every group listed", len(rows(d)), 4)
    check("non-members greyed with a tooltip", len(greyed(d)), 2)
    check("own groups pre-ticked", ticked(d), MINE)
    check("status names both counts", "member of 2" in d.groups_status.text(), True)
    d.close()

    print("\n2. Restricted agent, membership known -> narrowed")
    d = dialog(restricted=True)
    d._on_groups_loaded({"all": GROUPS, "mine": MINE, "error": ""})
    check("only their own groups listed", len(rows(d)), 2)
    check("nothing greyed, they are all members", greyed(d), [])
    d.close()

    print("\n3. REGRESSION: restricted agent, membership set came back EMPTY")
    d = dialog(restricted=True)
    d._on_groups_loaded({"all": GROUPS, "mine": set(), "error": ""})
    check("list is NOT blank", len(rows(d)), 4)
    check("hint explains why it is not narrowed",
          "would not confirm which" in d.groups_hint.text(), True)
    check("nothing pre-ticked, which watches everything visible", ticked(d), set())
    d.close()

    print("\n4. REGRESSION: restricted agent, membership unknown (None)")
    d = dialog(restricted=True)
    d._on_groups_loaded({"all": GROUPS, "mine": None, "error": ""})
    check("list is NOT blank", len(rows(d)), 4)
    check("status says membership is unknown",
          "would not say which" in d.groups_status.text(), True)
    d.close()

    print("\n5. REGRESSION: Zendesk refused to list groups at all")
    d = dialog(restricted=False)
    d._on_groups_loaded({
        "all": [], "mine": None,
        "error": "GET /api/v2/groups.json failed (403): Forbidden",
    })
    status = d.groups_status.text()
    check("the failure is stated", "would not list the groups" in status, True)
    check("the HTTP status is shown", "403" in status, True)
    check("and it says the app still works",
          "every group your account can see" in status, True)
    d.close()

    print("\n6. Membership is preserved when the list is redrawn")
    d = dialog(restricted=False, watched=[18564583439761])
    d._on_groups_loaded({"all": GROUPS, "mine": MINE, "error": ""})
    check("an existing choice is not overwritten by the default",
          ticked(d), {18564583439761})
    d.close()

    print("\n6b. THE NEW BIT: each mode keeps its own group selection")
    other = DayMode(id="other", name="Other", watched_group_ids=[25431951885841])
    d = dialog(watched=[18564583439761], extra_modes=[other])
    d._on_groups_loaded({"all": GROUPS, "mine": MINE, "error": ""})
    check("editing Primary shows its groups", ticked(d), {18564583439761})
    d.mode_combo.setCurrentIndex(d.mode_combo.findData("other"))
    check("switching to Other shows its groups", ticked(d), {25431951885841})
    for i in range(d.group_list.count()):
        if int(d.group_list.item(i).data(Qt.UserRole)) == 43806224142865:
            d.group_list.item(i).setCheckState(Qt.Checked)
    d.mode_combo.setCurrentIndex(d.mode_combo.findData("primary"))
    check("Primary is unaffected by edits to Other", ticked(d), {18564583439761})
    d.mode_combo.setCurrentIndex(d.mode_combo.findData("other"))
    check("Other remembers the extra tick",
          ticked(d), {25431951885841, 43806224142865})
    d.close()

    print("\n6c. A reopen-only mode hides the group list, which it cannot use")
    d = dialog(rules={modes.RULE_NEW_UNASSIGNED: False,
                      modes.RULE_BECAME_UNASSIGNED: False})
    d._on_groups_loaded({"all": GROUPS, "mine": MINE, "error": ""})
    check("group box disabled", d.groups_box.isEnabled(), False)
    check("list emptied", d.group_list.count(), 0)
    check("and it explains why", "tied to a group" in d.groups_hint.text(), True)
    d.close()

    print("\n7. REGRESSION: a sign-in in flight must not block the group load")
    import threading
    hold = threading.Event()
    d = dialog()
    started = []

    d._run_async("sign-in", lambda: hold.wait(5), started.append, [])
    check("sign-in is in flight", "sign-in" in d._busy, True)

    d._run_async("groups", lambda: hold.wait(5), started.append, [])
    check("the group load still started", "groups" in d._busy, True)
    check("two independent threads running", len(d._threads), 2)

    d._run_async("groups", lambda: hold.wait(5), started.append, [])
    check("but a duplicate of the same key is ignored", len(d._threads), 2)

    hold.set()
    for thread in list(d._threads):
        thread.wait(5000)
    d.close()

    print("\n8. 'Only my groups' explains itself when membership is unknown")
    d = dialog(restricted=False)
    d._on_groups_loaded({"all": GROUPS, "mine": None, "error": ""})
    check("no membership to narrow to", d._my_group_ids, None)
    d.close()


if __name__ == "__main__":
    QApplication([])
    run()
    print("\n" + "=" * 60)
    if _failures:
        print("{} FAILING CHECK(S): {}".format(len(_failures), ", ".join(_failures)))
        sys.exit(1)
    print("All checks passed.")
