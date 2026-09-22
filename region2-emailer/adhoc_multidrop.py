"""Build the upload for an ad hoc that drops at more than one site.

process_form reads the form's RHPC Admin row, and that row holds exactly ONE
delivery address. A multi-drop request does not fit it. On AH23/9/26FKEH the
second drop existed only inside the collection notes:

    ...PICK UP 1 X IBJ & 4 X 60FT RAILS - DROP OFF 1 X IBJ AT NEWBRIDGE YARD
    ///pegs.recruited.lentil & DROP OFF 4 X 60FT RAILS AT DRUMGELLOCH...

so process_form saw one delivery, to Newbridge, and the Drumgelloch rails had
no line at all. The job sat without a CSV.

The reference corpus writes a multi-drop as the base order ref followed by
_1, _2 (PW-2682026CVYO / _1 / _2 in NR_heavy_02092026091159.csv): one ORDER
record per drop, every one sharing the same collection. That is what this
writes. An earlier hand-built attempt used _S1/_S2, which appears nowhere in
the corpus.

The drops themselves come from _adhocs.json, which already holds them parsed
off the form, so the same record drives the map and the upload and the two
cannot drift apart. Everything else - tasks, cost centre, raised-by, vehicle
- is read from the form's RHPC row, unchanged.

Writes a file. Sends nothing.
"""
import datetime as dt
import json
import os
import re
import sys

import nr_csv
import outbox
import process_form

HERE = os.path.dirname(os.path.abspath(__file__))
ADHOCS = os.path.join(HERE, "_adhocs.json")
FORMS_DIR = os.path.join(HERE, "_adhoc_forms")


def record(order):
    """The _adhocs.json record for this order, or None."""
    want = str(order).strip().upper()
    try:
        with open(ADHOCS, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return None
    for e in rows:
        if any(str(o).strip().upper() == want for o in (e.get("orders") or [])):
            return e
    return None


def _safe_ref(order):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(order).strip()).strip("-")


def form_path(order, rec=None):
    """The filled form to read the RHPC row from.

    Prefers the copy filed under the order ref, then whatever name the record
    kept, then the mailbox. A form that only ever lived in a temp directory is
    how the first rebuild of AH23/9/26FKEH had nothing to read.
    """
    cand = [os.path.join(FORMS_DIR, "Haulage Request Form %s.xlsx" % _safe_ref(order))]
    if rec and rec.get("form_file"):
        cand.append(os.path.join(FORMS_DIR, rec["form_file"]))
    for p in cand:
        if os.path.exists(p):
            return p
    try:
        p, _, _ = process_form.find_form(order)
        return p or ""
    except Exception:
        return ""


def _pc_ok(pc):
    """A UK postcode whose inward half is a digit and two letters.

    'ML6 BZ' is missing its digit. Left in, it reads as a real postcode to
    everything downstream and puts a 60ft artic somewhere in Airdrie.
    """
    parts = str(pc or "").strip().upper().split()
    return len(parts) == 2 and re.fullmatch(r"\d[A-Z]{2}", parts[1]) is not None


def legs(order, rec, base, day=None, start=None):
    """One RHPC-shaped row per drop: base ref first, then _1, _2, ..."""
    drops = rec.get("drops") or []
    if not drops:
        raise ValueError("%s has no drops on its record - nothing to build." % order)

    date_s = str(day or rec.get("collection_date") or "").strip()
    if not date_s:
        raise ValueError("%s has no date - refusing to invent one." % order)
    when = dt.datetime.strptime(date_s, "%d/%m/%Y")
    hhmm = str(start or (rec.get("details", {}).get("collection_time", {}) or {})
               .get("earliest") or "").strip()
    h, m = (int(x) for x in hhmm.split(":")) if ":" in hhmm else (0, 0)

    product = str(rec.get("product") or "").strip()
    out = []
    for i, dr in enumerate(drops):
        d = dict(base)
        ref = str(order) if i == 0 else "%s_%d" % (order, i)
        d["Customer Order No"] = ref
        d["Shipment No"] = ref
        d["Collection Date"] = when
        d["collection_time"] = when.replace(hour=h, minute=m) if hhmm else None
        # Deliberately blank: close_window() closes it on its own date, so a
        # date change cannot leave the old date hiding in the window's end.
        d["collection_time_end"] = None
        d["Delivery Date"] = when
        d["delivery_time"] = None
        d["delivery_time_end"] = None
        d["Delivery Point"] = dr.get("site") or ""
        addr = str(dr.get("address") or "")
        bits = [b.strip() for b in addr.split(",") if b.strip()]
        d["D Address 1"] = bits[0] if bits else "0"
        d["D Address 2"] = bits[1] if len(bits) > 1 else "0"
        d["D Address 3"] = "0"
        d["D Postcode"] = dr.get("pc") or ""
        d["Product Qty"] = dr.get("qty") or ""
        # The form's account reads "Please select"; account_for treats any
        # preset as authoritative, so that string would land in the upload.
        d["Account"] = "NRADHOC"
        instr = " - ".join(x for x in (
            ("Material " + product) if product else "",
            dr.get("qty") or "",
            ("what3words " + dr["w3w"]) if dr.get("w3w") else "",
        ) if x)
        if not _pc_ok(d["D Postcode"]):
            instr += " - POSTCODE INCOMPLETE ON REQUEST - CONFIRM WITH SITE BEFORE DELIVERY"
        d["Delivery Instructions"] = instr
        out.append(d)
    return out


def build(order, day=None, start=None, stamp=None, out_name=None):
    """Write the multi-drop upload. Returns (path, rows, warnings)."""
    rec = record(order)
    if rec is None:
        raise ValueError("%s is not on the ad hoc list." % order)
    path = form_path(order, rec)
    if not path:
        raise ValueError("No filled form found for %s." % order)
    rows = process_form.read_rhpc_rows(path)
    if not rows:
        raise ValueError("The form for %s has no RHPC Admin row." % order)

    built = legs(order, rec, dict(rows[0]), day=day, start=start)
    warn = [("%s: postcode %r is not a full postcode"
             % (r["Customer Order No"], r["D Postcode"]))
            for r in built if not _pc_ok(r["D Postcode"])]

    transformed = [process_form.to_transform_row(d) for d in built]
    records = nr_csv.transform(transformed)
    ts = stamp or dt.datetime.now()
    name = out_name or ("NR_heavy_%s_%s.csv"
                        % (_safe_ref(order), ts.strftime("%d%m%Y%H%M%S")))
    return nr_csv.write_csv(records, outbox.path(name)), transformed, warn


def main(argv):
    if not argv:
        print("usage: adhoc_multidrop.py <order> [dd/mm/yyyy] [HH:MM]")
        return 2
    order = argv[0]
    day = argv[1] if len(argv) > 1 else None
    start = argv[2] if len(argv) > 2 else None
    path, rows, warn = build(order, day=day, start=start)
    for r in rows:
        print("  %-18s %s %s -> %s  |  coll %s -> %s  del %s -> %s"
              % (r["Customer Order No"], r["Delivery Point"], r["D Postcode"],
                 r["Product Qty"], r["collection time"], r["collection time end"],
                 r["delivery time"], r["delivery time end"]))
    for w in warn:
        print("  !! " + w)
    print("WROTE: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
