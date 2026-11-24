"""The cover request's "Rails:" line - runs tests/rail_details.test.mjs (the dashboard's own orders.js) under Node.

    python -m pytest tests/test_rail_details.py
"""
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def test_rail_details_under_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, os.path.join(HERE, "rail_details.test.mjs")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
