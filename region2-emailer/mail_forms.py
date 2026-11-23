"""Every Haulage Request form in one email onto the map, and forms that share an order number as ONE order.

monitor_tick used to take only the first form in an email; the rest were never processed. And two forms carrying the
SAME order number would have replaced each other on the map anyway, since a map record is keyed on its order numbers.
On 16/11 a rails form and a switch half set form came in one email like that: one order number, one lorry asked for, two
drops. Only the rails reached the map; the half set was found a day later.

So the forms of one email are taken together:
  * a form whose order number no other form in the email has goes through process_form.py, exactly as a lone form does;
  * forms that share their order number become ONE order on the map. The first keeps the number and the rest become
    <ref>_1, <ref>_2 - the multi-drop shape of the reference uploads (see adhoc_multidrop.py): one ORDER per drop, all
    in ONE upload, the first form's order exactly as it comes out on its own. The map record carries every order, every
    pick-up, a `drops` list and a Notes line naming each drop, and says where the forms disagree (day, pick-up,
    vehicle) - it never settles that itself.

A form with more than one row (a return leg) is never folded into another: which leg goes with which drop can't be told.
The first form goes on as it would alone, and the others are said, not put on the map (they would replace it).

    python mail_forms.py FORM1 FORM2 ...     (FORM.mail.json beside a form: the email it came in, as monitor_tick saves it)

Writes the uploads and the map. Sends nothing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

import nr_csv
import outbox
import process_form as PF

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = "RESULT"           # one line per form at the end, for monitor_tick: RESULT <tab> ok|no <tab> form <tab> what


def _mail(path):
    """The email a saved form came in (monitor_tick writes it beside the form), or None."""
    try:
        with open(path + ".mail.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _label(path):
    """The form's name as it was attached - the saved copy has a time stamp in front."""
    return str((_mail(path) or {}).get("file") or "") or os.path.basename(path)


def rows_of(path):
    """The form's rows as process_form.main reads them: order numbers hyphenated, a repeated row left out."""
    seen, out = set(), []
    for d in PF.read_rhpc_rows(path) or []:
        d["Customer Order No"] = PF._norm_order(d.get("Customer Order No"))
        if str(d.get("Shipment No") or "").strip():
            d["Shipment No"] = PF._norm_order(d.get("Shipment No"))
        ref = str(d.get("Customer Order No"))
        if ref not in seen:
            seen.add(ref)
            out.append(d)
    return out


def groups(paths, read=None):
    """[(ref, [(path, rows)])] in the email's order, forms with the same first order number together. A form that can't
    be read, or whose number is missing or cut short, goes alone with ref "" - process_form says what is wrong."""
    read = read or rows_of
    out, at = [], {}
    for p in paths:
        try:
            rows = read(p)
        except Exception:
            rows = []
        ref = str(rows[0].get("Customer Order No") or "").strip() if rows else ""
        if not ref or PF._ref_incomplete(ref):
            out.append(("", [(p, rows)]))
        elif ref in at:
            out[at[ref]][1].append((p, rows))
        else:
            at[ref] = len(out)
            out.append((ref, [(p, rows)]))
    return out


def alone(path):
    """One form through process_form.py, exactly as a lone form in an email goes. -> (on the map?, what, its output)"""
    args = [sys.executable, os.path.join(HERE, "process_form.py"), path]
    if os.path.exists(path + ".mail.json"):
        args += ["--mail", path + ".mail.json"]
    try:
        p = subprocess.run(args, cwd=HERE, capture_output=True, text=True, errors="replace", timeout=240)
        out = (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        out = f"FAILED process_form.py {os.path.basename(path)}: {e}"
    ok, what = PF.outcome(out)
    return ok, what, out


def _next_ref(ref, taken):
    k = 1
    while f"{ref}_{k}" in taken:
        k += 1
    return f"{ref}_{k}"


def _address(d):
    parts = (str(d.get(k) or "").strip() for k in ("D Address 1", "D Address 2", "D Address 3"))
    return ", ".join(x for x in parts if x and x != "0")


def merged(recs, rows, labels):
    """One map record for one lorry's drops: the first drop's record, carrying every order, every pick-up and every
    drop, and a Notes line that names each drop and says where the forms disagree."""
    rec = json.loads(json.dumps(recs[0]))
    det = rec.setdefault("details", {})

    def vals(key):
        return [str(((r.get("details") or {}).get(key) or {}).get("value") or "") for r in recs]

    # the lorry needs whatever any one of its drops needs
    for key in ("pts", "rear_steer"):
        if "yes" in vals(key):
            det[key] = {"value": "yes"}
    offs = vals("offloading")
    for off in ("HIAB", "MOFFETT"):
        if off in offs:
            det["offloading"] = {"value": off}
            break
    colls, seen = [], set()
    for r in recs:
        for c in r.get("collections") or []:
            k = (str(c.get("site") or "").strip().upper(), str(c.get("pc") or "").replace(" ", "").upper())
            if k not in seen:
                seen.add(k)
                colls.append(c)
    drops = [{"order": r["orders"][0], "site": r.get("site") or "", "address": _address(d), "pc": r.get("postcode") or "",
              "qty": r.get("materials") or "", "delivery_date": r.get("delivery_date") or "",
              "time": (r.get("details") or {}).get("time") or {}} for r, d in zip(recs, rows)]
    checks = []
    for what, got in (("collection days", [r.get("collection_date") or "" for r in recs]),
                      ("delivery days", [r.get("delivery_date") or "" for r in recs]),
                      ("vehicles", vals("vehicle"))):
        if len(set(got)) > 1:
            checks.append(f"the forms give different {what} ({', '.join(dict.fromkeys(g or 'none' for g in got))})")
    if len(colls) > 1:
        checks.append("the forms collect from different places ("
                      + "; ".join(" ".join(x for x in (c.get("site"), c.get("pc")) if x) for c in colls) + ")")
    sites = list(dict.fromkeys(r.get("site") for r in recs if r.get("site")))
    det["notes"] = {"value": (
        f"One order, {len(recs)} drops: {len(recs)} forms with the same order number came in one email. "
        + " ".join(f"Drop {i + 1} {dr['order']}: {dr['qty'] or 'see its form'} to "
                   + ", ".join(x for x in (dr["site"], dr["address"], dr["pc"]) if x) + "."
                   for i, dr in enumerate(drops))
        + (" Check: " + "; ".join(checks) + "." if checks else ""))}
    rec.update({
        "orders": [o for r in recs for o in r.get("orders") or []],
        "worksite": " + ".join(sites) if len(sites) > 1 else rec.get("worksite") or "",
        "collections": colls or rec.get("collections") or [],
        "materials": " + ".join(r["materials"] for r in recs if r.get("materials")),
        "qty": "",                  # one figure can't stand for several orders' lines
        "product": " + ".join(dict.fromkeys(r["product"] for r in recs if r.get("product"))),
        "weight": " + ".join(r["weight"] for r in recs if r.get("weight")),
        "drops": drops,
        "form_files": [r.get("form_file") or "" for r in recs],
        "combined": {"forms": list(labels), "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "checks": checks},
    })
    return rec


def combine(ref, members, avoid=(), stamp=None):
    """Forms sharing order number `ref` -> ONE order on the map and ONE upload, printed as process_form.main prints.
    members: [(path, rows)]. -> [(on the map?, what, form)], one per form."""
    labels = [_label(p) for p, _ in members]
    if any(len(rows) != 1 for _, rows in members):
        ok, what, out = alone(members[0][0])
        print(out.rstrip())
        res = [(ok, what, labels[0])]
        for lab in labels[1:]:
            print(f"!! {lab}: the same order number as {labels[0]} ({ref}), and one of them has more than one row - "
                  "not folded together, and not put on the map: it would replace the other. Check both forms.")
            res.append((False, f"same order number {ref} as {labels[0]} - not combined, check both forms", lab))
        return res

    taken, rows = {ref} | set(avoid), []
    for i, (_, rr) in enumerate(members):
        d = dict(rr[0])
        if i:
            d["Customer Order No"] = d["Shipment No"] = _next_ref(ref, taken)
            taken.add(d["Customer Order No"])
        rows.append(d)
    print(f"FORMS: {len(members)} with order number {ref} in one email - one order, "
          f"{' / '.join(d['Customer Order No'] for d in rows)}: " + "; ".join(labels))

    transformed = [PF.to_transform_row(d) for d in rows]
    records = nr_csv.transform(transformed)
    import date_query
    backwards = date_query.raise_query(transformed, str(rows[0].get("Raised by") or "").split(";")[0].strip(),
                                       f"Ad hoc {ref}")
    if backwards:
        print(f"!! {len(backwards)} DELIVERY BEFORE COLLECTION - not bookable as they stand:")
        for p in backwards:
            print(f"     {p['ref']}  collect {p['collection']}  deliver {p['delivery']}  ({p['back_by']} earlier)")
        print("   An email asking them to confirm is ready for Review & send.")
    print(f"BACKWARDS_DATES {len(backwards)}")
    safe = re.sub(r"[^A-Za-z0-9]+", "-", ref).strip("-")[:24]
    name = "NR_heavy_" + (safe + "_" if safe else "") + (stamp or datetime.now()).strftime("%d%m%Y%H%M%S") + ".csv"
    out = nr_csv.write_csv(records, outbox.path(name))

    os.makedirs(PF.FORMS_DIR, exist_ok=True)
    recs = []
    for (path, _), d in zip(members, rows):
        form_file = ("Haulage Request Form " + re.sub(r"[^A-Za-z0-9._-]", "-", str(d["Customer Order No"]))
                     + os.path.splitext(path)[1])
        try:
            shutil.copyfile(path, os.path.join(PF.FORMS_DIR, form_file))
        except OSError:
            form_file = ""
        recs.append(PF._adhoc_record(d, name, form_file=form_file, mail=_mail(members[0][0])))
    rec = merged(recs, rows, labels)
    n = PF.store_adhocs([rec])
    if n:
        print("MAP : job saved for the dashboard map (form kept for forwarding).")
    else:
        print("MAP : NOT on the map - every job in this form was refused, see the SKIP line(s) above.")
    for d, tr in zip(rows, transformed):
        print(f"Order {d.get('Customer Order No')} | {d.get('Site Name - Collection')} -> {d.get('Delivery Point')} | "
              f"qty {d.get('Product Qty')} | acct {PF.account_for(d)}")
        missing = [lbl for lbl, k in (("collection", "collection time"), ("delivery", "delivery time")) if not tr[k]]
        if missing:
            print(f"!! {d.get('Customer Order No')}: {' & '.join(missing)} has NO DATE on the form at all - times "
                  "are BLANK in the CSV; fill in before uploading.")
    for c in rec["combined"]["checks"]:
        print(f"CHECK {ref}: {c}")
    print(f"CSV : {out}")
    if not n:
        return [(False, "already booked in - not put back on the map", lab) for lab in labels]
    said = f"{' / '.join(rec['orders'])} (one order from {len(labels)} forms)"
    if rec["combined"]["checks"]:
        said += " - check its Notes: the forms differ"
    return [(True, said, labels[0])] + [(True, "", lab) for lab in labels[1:]]     # "": said with the first


def run(paths):
    """Every form of one email. -> [(on the map?, what, form)], one per form, in the email's order."""
    gs = groups(paths)
    avoid = {ref for ref, _ in gs if ref}
    results = []
    for ref, members in gs:
        try:
            if len(members) == 1:
                ok, what, out = alone(members[0][0])
                print(out.rstrip())
                results.append((ok, what, _label(members[0][0])))
            else:
                results += combine(ref, members, avoid=avoid)
        except Exception as e:               # one group failing must not cost the others
            print(f"!! {ref or 'a form'}: {type(e).__name__}: {e}")
            results += [(False, f"{type(e).__name__}: {e}", _label(p)) for p, _ in members]
    return results


def outcomes(out, forms=()):
    """What a run of this script said -> [(on the map?, its order or why not, the form)], for monitor_tick. Forms that
    say nothing (the run died) come back as not processed."""
    res = []
    for ln in out.splitlines():
        parts = ln.rstrip("\r").split("\t", 3)
        if len(parts) == 4 and parts[0] == RESULT:
            res.append((parts[1] == "ok", parts[3], parts[2]))
    said = {r[2] for r in res}
    return res + [(False, "the forms did not finish processing", f) for f in forms if f not in said]


def main(argv):
    try:
        sys.stdout.reconfigure(errors="replace")    # a character the pipe's code page lacks must not end the run
    except Exception:
        pass
    paths = [a for a in argv if os.path.exists(a)]
    if not paths:
        print("usage: mail_forms.py FORM1 FORM2 ...")
        return 2
    for ok, what, form in run(paths):
        print("\t".join((RESULT, "ok" if ok else "no", form.replace("\t", " "), str(what).replace("\t", " "))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
