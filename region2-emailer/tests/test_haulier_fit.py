"""Who the map lists for a job - runs tests/haulier_fit.test.mjs (the dashboard's own orders.js) under Node.
Made-up hauliers and orders only.

    python tests/test_haulier_fit.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP  node is not installed - the haulier-fit tests need it")
        return 0
    r = subprocess.run([node, os.path.join(HERE, "haulier_fit.test.mjs")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    print(r.stdout.rstrip())
    if r.returncode:
        print(r.stderr.rstrip())
        print("FAILED")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
