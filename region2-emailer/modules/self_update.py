"""Self-updating from Outlook "update emails".

The supervisor polls the inbox every minute (COM adapter snippet in
../INTEGRATE_ON_HOMEPC.md) and hands plain dicts to process_messages(); rules
found in the body are applied to the site store / team file / settings file.
Processed message ids go in a ledger so nothing is applied twice.

An update email must have the subject prefix (default "R2 UPDATE") and come
from a team member (or an update_email.allowed_senders entry). Body lines
understood, one rule per line (case-insensitive keywords, reply-quoting '>'
tolerated):

    site: RAW UPLOAD NAME => Synergy Site Name
    add site: Synergy Site Name
    team add: Full Name <email@dhl.com>
    team remove: email-or-name
    setting: key = value
"""
import json
import os
import re


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def allowed_sender(sender, team):
    s = str(sender or "").strip().lower()
    extra = [a.lower() for a in team.get("update_email", {}).get("allowed_senders", [])]
    members = [m.get("email", "").lower() for m in team.get("members", [])]
    return bool(s) and (s in extra or s in members)


def is_update_email(msg, team):
    prefix = team.get("update_email", {}).get("subject_prefix", "R2 UPDATE").lower()
    return str(msg.get("subject", "")).lower().startswith(prefix)


def parse_rules(body):
    rules = []
    for line in str(body or "").splitlines():
        line = line.strip().lstrip(">").strip()
        m = re.match(r"(?i)^site\s*:\s*(.+?)\s*=>\s*(.+)$", line)
        if m:
            rules.append(("site", m.group(1).strip(), m.group(2).strip()))
            continue
        m = re.match(r"(?i)^add\s+site\s*:\s*(.+)$", line)
        if m:
            rules.append(("add_site", m.group(1).strip()))
            continue
        m = re.match(r"(?i)^team\s+add\s*:\s*(.+?)\s*<([^>]+)>\s*$", line)
        if m:
            rules.append(("team_add", m.group(1).strip(), m.group(2).strip()))
            continue
        m = re.match(r"(?i)^team\s+remove\s*:\s*(.+)$", line)
        if m:
            rules.append(("team_remove", m.group(1).strip()))
            continue
        m = re.match(r"(?i)^setting\s*:\s*([\w.\-]+)\s*=\s*(.+)$", line)
        if m:
            rules.append(("setting", m.group(1).strip(), m.group(2).strip()))
            continue
    return rules


def process_messages(msgs, site_store, team_path, settings_path, seen_path):
    """msgs: [{"id","sender","subject","body"}]. Returns applied-action strings.

    Matching messages are marked seen even when no rules parse, so a
    malformed update isn't retried forever (send a corrected email instead).
    """
    seen = set(_load_json(seen_path, []))
    team = _load_json(team_path, {"members": []})
    applied = []
    for msg in msgs or []:
        mid = str(msg.get("id", ""))
        if (not mid or mid in seen or not is_update_email(msg, team)
                or not allowed_sender(msg.get("sender"), team)):
            continue
        for rule in parse_rules(msg.get("body", "")):
            kind = rule[0]
            if kind == "site":
                site_store.resolve(rule[1], rule[2])
                applied.append(f"site mapping: {rule[1]} => {rule[2]}")
            elif kind == "add_site":
                site_store.add_sites([rule[1]])
                applied.append(f"site added: {rule[1]}")
            elif kind == "team_add":
                if not any(m.get("email", "").lower() == rule[2].lower()
                           for m in team.get("members", [])):
                    team.setdefault("members", []).append(
                        {"name": rule[1], "email": rule[2]})
                    _save_json(team_path, team)
                applied.append(f"team add: {rule[1]} <{rule[2]}>")
            elif kind == "team_remove":
                q = rule[1].lower()
                kept = [m for m in team.get("members", [])
                        if m.get("email", "").lower() != q
                        and m.get("name", "").lower() != q]
                if len(kept) != len(team.get("members", [])):
                    team["members"] = kept
                    _save_json(team_path, team)
                    applied.append(f"team remove: {rule[1]}")
            elif kind == "setting":
                settings = _load_json(settings_path, {})
                settings[rule[1]] = rule[2]
                _save_json(settings_path, settings)
                applied.append(f"setting: {rule[1]} = {rule[2]}")
        seen.add(mid)
    _save_json(seen_path, sorted(seen)[-500:])
    return applied
