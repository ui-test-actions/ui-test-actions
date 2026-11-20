import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop_driver import linux_tree


class Node:
    name = ""

    def __init__(self, children=(), text="", role="filler"):
        self.children = children
        self.childCount = len(children)
        self.text = text
        self.characterCount = len(text)
        self.role = role

    def __getitem__(self, index):
        return self.children[index]

    def getRoleName(self):
        return self.role

    def getRole(self):
        return self.role

    def getState(self):
        return SimpleNamespace(contains=lambda state: state in ("visible", "enabled", "editable", "active"))

    def queryComponent(self):
        return SimpleNamespace(getExtents=lambda _: SimpleNamespace(x=0, y=0, width=10, height=10))

    def queryText(self):
        return self

    def getText(self, start, end):
        return self.text[start:end]


class LinuxTreeTests(unittest.TestCase):
    def test_deep_menu_cannot_hide_editor_from_first_page(self):
        editor = Node(text="مرحبًا ١٢٣", role="text")
        menu = Node(children=[Node() for _ in range(350)])
        window = Node(children=[menu, editor])
        pyatspi = SimpleNamespace(Registry=SimpleNamespace(getDesktop=lambda _: [[window]]), DESKTOP_COORDS=0,
                                 STATE_SHOWING="visible", STATE_ENABLED="enabled", STATE_ACTIVE="active",
                                 STATE_FOCUSED="focus", STATE_CHECKED="checked", STATE_SELECTED="selected",
                                 STATE_EDITABLE="editable", ROLE_PASSWORD_TEXT="password")
        with patch.dict(sys.modules, {"pyatspi": pyatspi}):
            snapshot = linux_tree()
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(snapshot["nodes"][2]["text"], "مرحبًا ١٢٣")
        self.assertTrue(snapshot["nodes"][2]["properties"]["editable"])
