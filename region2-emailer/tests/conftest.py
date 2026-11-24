"""Shared pytest fixtures.

`tmp`: a fresh folder as a plain string path. test_modules.py and test_adhoc_from_mail.py were written to be run as
scripts too (their __main__ hands each test a tempfile.TemporaryDirectory()), so under pytest they asked for a
fixture that didn't exist and errored on every run - six errors that hid real failures in the deploy gate.
"""
import pytest


@pytest.fixture
def tmp(tmp_path):
    return str(tmp_path)
