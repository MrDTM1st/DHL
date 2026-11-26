"""
What the toolkit did to an order's lines, kept so he can answer for it. His 26/11: "I'm gonna be questioned on it, and I
won't be able to give them a definitive answer because I don't really know what you just did."

Every split, copy, cancel, restore, non-conformance and quantity change a CTMS route makes is written here, one line each
(_order_ledger.jsonl), with the order's original quantity once it's known (order-audit --original). A copy or re-upload
the toolkit made - as a replacement for a line cancelled, aborted or non-conformed, or on purpose with a reason - or one
he cleared by name, is a line Book may book. Any other copy is one nobody here made, and it can add to the order: on
26/11 a sleeper order's hand-made copy would have put a whole load over what was ordered.

    python order_ledger.py ORDER              the order's history, in plain words
    python order_ledger.py allow LINE "why"   a copy made by hand, cleared for Book after a look (order-audit first)
"""
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_order_ledger.jsonl")
ADDED = re.compile(r"_(?:C\d+|RB\d*)$", re.I)        # a copied line or a re-upload: lines that add to an order

WORDS = {"split": "split", "copy": "copied", "cancel": "cancelled", "restore": "restored", "qty": "quantity changed",
         "nc": "non-conformed", "allow": "cleared for booking", "original": "original quantity noted",
         "audit": "audited"}


def order_of(ref):
    """'1234567-1-1_C1' -> '1234567': a Network Rail order's number. An ad hoc's or a DTS's ref, its suffix off."""
    ref = str(ref or "").strip()
    m = re.match(r"(\d{7})(?:-\d+-\d+)?", ref)
    return m.group(1) if m else re.sub(r"_(?:[SC]\d+|RB\d*)$", "", ref, flags=re.I)


def log(action, ref, said, path=None, now=None, **extra):
    """One thing done to one line, written at once."""
    e = {"at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), "order": order_of(ref), "ref": str(ref),
         "action": action, "said": said}
    e.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    with open(path or PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(e) + "\n")
    return e


def events(order=None, path=None):
    """Everything kept - for one order when it's named - oldest first."""
    out = []
    try:
        with open(path or PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if order is None or e.get("order") == order_of(order):
                    out.append(e)
    except OSError:
        pass
    return out


def known_lines(orders, path=None):
    """These orders' copies and re-uploads Book may book: made here (a replacement, or extra with a reason) or cleared by
    him by name."""
    want = {order_of(o) for o in orders or ()}
    out = set()
    for e in events(path=path):
        if e.get("order") not in want:
            continue
        if e.get("action") == "copy":
            out.update(e.get("new") or [])
        elif e.get("action") == "allow":
            out.add(e["ref"])
    return sorted(out)


def non_conformed(ref, path=None):
    """Whether this line had a non-conformance put on it here (order-nc)."""
    return any(e.get("action") == "nc" and str(e.get("ref", "")).lower() == str(ref).lower() for e in events(ref, path))


def remember_original(order, qty, path=None, said=""):
    return log("original", order, said or f"ordered {qty:g}", path=path, qty=qty)


def original(order, path=None):
    """The order's quantity as ordered, once order-audit has been told it - None until then."""
    got = [e for e in events(order, path) if e.get("action") == "original"]
    return got[-1]["qty"] if got else None


def history(order, path=None):
    """The order's history in plain words, for him to answer with."""
    out = [f"{order_of(order)}: what the toolkit did to its lines"]
    evs = events(order, path)
    if not evs:
        return out + ["  nothing kept: any change to it was made outside the toolkit (or before 26/11)"]
    for e in evs:
        out.append(f"  {e['at'][:16]}  {e['ref']}: {WORDS.get(e['action'], e['action'])} - {e.get('said', '')}"
                   + (f" (why: {e['why']})" if e.get("why") else ""))
    return out


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) == 4 and argv[1] == "allow":
        if not ADDED.search(argv[2]):
            print(f"{argv[2]} isn't a copy or a re-upload - nothing to clear")
            return 2
        log("allow", argv[2], "cleared for Book by hand", why=argv[3])
        print(f"{argv[2]} cleared for Book ({argv[3]})")
        return 0
    if len(argv) == 2:
        print("\n".join(history(argv[1])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
