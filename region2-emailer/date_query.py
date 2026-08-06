"""
Dates that run backwards - spot them, and ask the requester before uploading.

A delivery timed BEFORE its own collection is not a job anyone can do. The
Media Sets Input Sheet already flags it in its audit column ("Date Error"), but
only once someone opens the workbook and looks - and by then the CSV may be
uploaded. Every upload route goes through here instead, so the run itself stops
and says so.

What it produces is a question, not a correction. Nobody here can know whether
the collection date was a day early or the delivery a day late, so the toolkit
never guesses: it writes the email that asks, and you send it.

    _date_queries.json   what was found, for the dashboard
    _pending_email.json  the email, ready for Review & send

Sends nothing on its own.
"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
QUERIES = os.path.join(HERE, "_date_queries.json")


def _dt(v):
    if isinstance(v, datetime):
        return v
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(str(v).strip(), f)
        except Exception:
            pass
    return None


def backwards(orders):
    """The orders whose delivery lands before their collection.

    Only compares when BOTH ends have a real datetime - a missing time is a
    different problem and must not be reported as a backwards date.
    """
    out = []
    for o in orders:
        c, d = _dt(o.get("collection time")), _dt(o.get("delivery time"))
        if c is None or d is None or d >= c:
            continue
        out.append({
            "ref": str(o.get("Customer Order No") or "").strip(),
            "collection": f"{c:%a %d/%m/%Y %H:%M}",
            "delivery": f"{d:%a %d/%m/%Y %H:%M}",
            "from_site": str(o.get("Site Name - Collection") or ""),
            "from_pc": str(o.get("Postcode") or ""),
            "to_site": str(o.get("Delivery Point") or ""),
            "to_pc": str(o.get("D Postcode") or ""),
            "back_by": _gap(c, d),
        })
    return out


def _gap(c, d):
    mins = int((c - d).total_seconds() // 60)
    if mins >= 1440:
        days = mins // 1440
        return f"{days} day{'s' if days > 1 else ''}"
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"


def save(problems, source=""):
    """Record what was found so the dashboard can show it."""
    with open(QUERIES, "w", encoding="utf-8") as f:
        json.dump({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "source": source, "problems": problems}, f, indent=1)
    return QUERIES


def load():
    try:
        with open(QUERIES, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"problems": []}


def clear():
    try:
        os.remove(QUERIES)
    except OSError:
        pass


def build_email(problems, to, what, cc=""):
    """One email covering every backwards row, in the _pending_email.json shape
    the Review & send panel and send_order.py sendjson already use.

    One email, not one per row: they all go to whoever raised the sheet, and a
    reply that answers five rows at once is easier for them and for us.
    """
    lines = [f"Hi,", "",
             f"Before I raise {what}, could you check the dates on the run"
             f"{'s' if len(problems) > 1 else ''} below? The delivery is timed "
             f"before the collection, so as they stand {'they' if len(problems) > 1 else 'it'} "
             f"cannot be booked.", ""]
    for p in problems:
        lines.append(f"    {p['ref']}")
        lines.append(f"        {p['from_site']} {p['from_pc']} -> {p['to_site']} {p['to_pc']}")
        lines.append(f"        collection: {p['collection']}")
        lines.append(f"        delivery:   {p['delivery']}   ({p['back_by']} earlier)")
        lines.append("")
    lines.append("Could you confirm which of the two is right, and I will get "
                 "them raised straight away?")
    first = problems[0] if problems else {}
    return {
        "to": to, "cc": cc, "name": "",
        "subject": f"{what} - please confirm these delivery dates",
        "message": "\n".join(lines),
        # the tracker wants a date; the first affected run's is the honest one
        "date": (first.get("delivery") or "").split(" ")[1] if first.get("delivery") else "",
        "area": "", "orders": [p["ref"] for p in problems if p.get("ref")],
        "product_codes": [], "materials": "", "site": first.get("to_site", ""),
        "postcode": first.get("to_pc", ""), "source": what,
    }


def raise_query(orders, to, what, cc=""):
    """Find backwards dates, save them and stage the email. Returns the list."""
    problems = backwards(orders)
    if not problems:
        clear()
        return []
    save(problems, what)
    email = build_email(problems, to, what, cc)
    pending = os.path.join(HERE, "_pending_email.json")
    with open(pending, "w", encoding="utf-8") as f:
        json.dump([email], f, indent=1)
    return problems


if __name__ == "__main__":
    d = load()
    for p in d.get("problems", []):
        print(f"  {p['ref']:26} collect {p['collection']}  deliver {p['delivery']}"
              f"  ({p['back_by']} earlier)")
    print(f"  -> {len(d.get('problems', []))} backwards date(s), found {d.get('at', '?')}")
