"""The Network Rail card's own logic - runs tests/nr_card.test.mjs (the dashboard's orders.js) under Node, skipped
where Node isn't installed. Made-up orders only.

    python -m pytest -q tests/test_nr_card.py
"""
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def test_the_card_under_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, os.path.join(HERE, "nr_card.test.mjs")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
