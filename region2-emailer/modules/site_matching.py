"""Synergy delivery-site matching with a self-learning store.

The agent feeds raw delivery-site names from uploads; this answers with a
confident match, or queues a decision for the dashboard when unsure. Every
correction made on the dashboard (or by an R2 UPDATE email) is remembered in
the store and applied automatically from then on.

Store file is JSON (use an underscore name like _sites.json — .gitignore
keeps region2-emailer/_*.json out of git).
"""
import difflib
import json
import os
import re
import threading

AUTO_ACCEPT = 0.92      # fuzzy score treated as a confident match
SUGGEST_FLOOR = 0.55    # below this a site isn't even suggested
MAX_SUGGESTIONS = 8


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


class SiteStore:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._data = {"mappings": {}, "sites": [], "pending": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            for k in self._data:
                if isinstance(loaded.get(k), type(self._data[k])):
                    self._data[k] = loaded[k]
        except Exception:
            pass  # missing/corrupt store: start fresh rather than crash the agent

    def _save_locked(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def sites(self):
        with self._lock:
            return sorted(self._data["sites"])

    def add_sites(self, sites):
        """Grow the universe of valid Synergy sites (e.g. seeded from history)."""
        with self._lock:
            known = {_norm(s) for s in self._data["sites"]}
            added = 0
            for s in sites:
                s = str(s).strip()
                if s and _norm(s) not in known:
                    self._data["sites"].append(s)
                    known.add(_norm(s))
                    added += 1
            if added:
                self._save_locked()
        return added

    def match(self, raw):
        """Returns (site, how) with how in exact|learned|fuzzy,
        or (None, suggestions) when a human needs to decide."""
        n = _norm(raw)
        if not n:
            return None, []
        with self._lock:
            for s in self._data["sites"]:
                if _norm(s) == n:
                    return s, "exact"
            learned = self._data["mappings"].get(n)
            if learned:
                return learned, "learned"
            scored = sorted(
                ((difflib.SequenceMatcher(None, n, _norm(s)).ratio(), s)
                 for s in self._data["sites"]),
                key=lambda t: t[0], reverse=True)
        if scored and scored[0][0] >= AUTO_ACCEPT:
            return scored[0][1], "fuzzy"
        return None, [s for sc, s in scored[:MAX_SUGGESTIONS] if sc >= SUGGEST_FLOOR]

    def request_decision(self, raw, context=""):
        """Match, or queue a dashboard decision. Returns the site or None."""
        site, out = self.match(raw)
        if site:
            return site
        with self._lock:
            self._data["pending"][str(raw)] = {"context": str(context), "options": out}
            self._save_locked()
        return None

    def pending(self):
        """Decision list in the dashboard panel shape."""
        with self._lock:
            return [{"raw": r, "context": p.get("context", ""), "options": p.get("options", [])}
                    for r, p in self._data["pending"].items()]

    def resolve(self, raw, site):
        """A human said raw -> site. Remember it forever."""
        site = str(site).strip()
        if not site:
            return False
        with self._lock:
            self._data["mappings"][_norm(raw)] = site
            self._data["pending"].pop(str(raw), None)
            if _norm(site) not in {_norm(s) for s in self._data["sites"]}:
                self._data["sites"].append(site)
            self._save_locked()
        return True
