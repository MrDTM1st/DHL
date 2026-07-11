"""Team profiles and recipient guards.

Team file: config/team.json (copy config/team.json.example and fill in — the
real file is gitignored because it holds real names/addresses).
"""
import json
import re


def load_team(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _split(addrs):
    return [a.strip() for a in re.split(r"[;,]", str(addrs or "")) if a.strip()]


def find_member(team, name_or_email):
    """Resolve a dashboard-typed name/email to a team member dict, or None."""
    q = str(name_or_email or "").strip().lower()
    if not q:
        return None
    for m in team.get("members", []):
        if m.get("email", "").lower() == q or m.get("name", "").lower() == q:
            return m
    for m in team.get("members", []):
        if q in m.get("name", "").lower():
            return m
    return None


def clean_recipients(to, cc="", me=""):
    """Drop the sender's own address and duplicates from To/Cc.

    Returns (to, cc, removed) with To/Cc as semicolon-joined strings — apply
    to EVERY outgoing email so nobody accidentally emails themselves.
    """
    me_n = str(me or "").strip().lower()
    seen, removed = set(), []

    def keep(addrs):
        out = []
        for a in _split(addrs):
            al = a.lower()
            if al == me_n:
                removed.append(a)
            elif al not in seen:
                seen.add(al)
                out.append(a)
        return out

    to_l = keep(to)
    cc_l = keep(cc)
    return "; ".join(to_l), "; ".join(cc_l), removed


def is_internal(email, team):
    domains = [d.lower().lstrip("@") for d in team.get("internal_domains", ["dhl.com"])]
    m = re.search(r"@([\w.-]+)$", str(email or "").strip().lower())
    return bool(m) and any(m.group(1) == d or m.group(1).endswith("." + d)
                           for d in domains)


def split_internal_external(addrs, team):
    """One recipient string -> (internal list, external list)."""
    ints, exts = [], []
    for a in _split(addrs):
        (ints if is_internal(a, team) else exts).append(a)
    return ints, exts
