"""The order well's reader lives with the bridge now (work_pc/ctms_rows.py), the Book button needing it on the work PC."""
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "work_pc"))
from ctms_rows import *                 # noqa: E402,F401,F403
from ctms_rows import _cells, _columns, _frame  # noqa: E402,F401
