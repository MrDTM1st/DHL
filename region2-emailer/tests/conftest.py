"""Shared pytest fixtures.

`tmp`: a fresh folder as a plain string path. test_modules.py and test_adhoc_from_mail.py were written to be run as
scripts too (their __main__ hands each test a tempfile.TemporaryDirectory()), so under pytest they asked for a
fixture that didn't exist and errored on every run - six errors that hid real failures in the deploy gate.
"""
import os

import pytest

# Book reads an order's Business Type off its card in the real CTMS when it can't tell it (book_run.order_strategy, a
# subprocess to ctms_routes.py). No test may ever reach the real CTMS that way: their stand-in clients only fake Book's
# own ask.
os.environ["R2_NO_CARD_READ"] = "1"


@pytest.fixture
def tmp(tmp_path):
    return str(tmp_path)
