"""
Which code a haulier is booked under in CTMS. The contact list's carrier codes aren't CTMS's: "everyone that is an NOC now
has a DH variant" (his 29/10), and some go by another name altogether. So CTMS's own list is read off its carrier screen into
_carriers.json (gitignored: {"read", "codes": [...], "book": {haulier's name: code}}, the book map being what no rule finds),
and the order panel's Book offers each haulier by the code worked out here - his to correct on the form.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "_carriers.json")


def load(path=None):
    try:
        with open(path or FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _plain(code):
    """A code to compare by: its DigiHaul ending off, capitals and digits only."""
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"_DH$", "", str(code or "").strip().upper()))


def match(listed, codes):
    """The code in CTMS's list for what the contact list has: the same name's _DH one first, then the same name, then a _DH
    one the name starts with or that starts with it (three letters at least). "" when nothing does."""
    want = _plain(listed)
    if not want or not codes:
        return ""
    same = [c for c in codes if _plain(c) == want]
    dh = [c for c in same if str(c).upper().endswith("_DH")]
    if dh or same:
        return (dh or same)[0]
    near = [c for c in codes if str(c).upper().endswith("_DH") and len(_plain(c)) >= 2
            and (want.startswith(_plain(c)) or _plain(c).startswith(want)) and min(len(want), len(_plain(c))) >= 2]
    return near[0] if len(near) == 1 else ""


def book_code(haulier, data=None):
    """A contact list entry's code to book under: his map first, else matched - else the contact list's own, left for the form."""
    d = load() if data is None else data
    return (d.get("book") or {}).get(haulier.get("name")) or match(haulier.get("ctms"), d.get("codes") or []) \
        or str(haulier.get("ctms") or "")
