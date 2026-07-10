"""
Order-upload mapping: raw Synergy Haulier Extract -> enriched order rows (the
"Master Template with Mapping" logic) -> NR upload CSV (via nr_csv).

Replicates the Synergy Template File:
  * direct field copies from the extract
  * Supplier Details lookups by collection Site Name: Contact Name, Telephone,
    collection_time/_end (Collection Date + the site's loading-hour windows),
    Raised-by email (appended), collection Notes
  * postcode overrides for two sites; Shipment No derived from the Delivery
    Instructions when blank; Y/N fields default to N; a Serial of 0 -> blank
Collection sites not in the store are reported as UNMATCHED - the dashboard will
pop up to add them and remember (self-learning).

    python synergy_map.py "<raw extract .xlsx>"
"""
import os, json, sys, warnings
from datetime import datetime, timedelta
import openpyxl
import nr_csv, outbox

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
STORE = json.load(open(os.path.join(HERE, "_synergy_sites.json"), encoding="utf-8"))
SITES = STORE.get("sites", {})
OVERRIDES = STORE.get("postcode_overrides", {})
# template quirk: delivery time = collection time + ~1h (formula =M3+0.04236). FLAGGED.
DELIVERY_OFFSET = timedelta(minutes=61)


def _hours(s):
    try:
        h, m, sec = str(s).split(":")
        return timedelta(hours=int(h), minutes=int(m), seconds=int(float(sec)))
    except Exception:
        return None


def _as_dt(v):
    if isinstance(v, datetime):
        return datetime(v.year, v.month, v.day)
    if hasattr(v, "year"):                       # date
        return datetime(v.year, v.month, v.day)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(str(v).strip()[:10], fmt)
        except Exception:
            pass
    return None


def add_site(code, details):
    """Learn a new collection site: save it to the store so every future upload
    matches it automatically (the self-learning half of the site pop-up)."""
    global SITES
    code = str(code).strip()
    STORE.setdefault("sites", {})[code] = {
        "contact": details.get("contact", ""), "postcode": details.get("postcode", ""),
        "telephone": details.get("telephone", ""),
        "start_hours": details.get("start_hours", "") or "07:00:00",
        "close_hours": details.get("close_hours", "") or "17:00:00",
        "email": details.get("email", ""), "notes": details.get("notes", ""),
    }
    with open(os.path.join(HERE, "_synergy_sites.json"), "w", encoding="utf-8") as f:
        json.dump(STORE, f, indent=1)
    SITES = STORE["sites"]
    return code


def map_orders(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip().lower() if h is not None else "" for h in rows[0]]

    def gi(*names):
        for n in names:
            if n in hdr:
                return hdr.index(n)
        return None

    C = dict(order=gi("customer order no"), ship=gi("shipment no"),
             site=gi("site name - collection"), ocn=gi("order contact name"),
             oco=gi("order contact no"), a1=gi("address1", "address 1"),
             a2=gi("address 2"), a3=gi("address 3"), pc=gi("postcode"),
             cdate=gi("collection date"), dpoint=gi("delivery point"),
             dcn=gi("d contact name"), da1=gi("d address1", "d address 1"),
             da2=gi("d address 2"), da3=gi("d address 3"), dpc=gi("d postcode"),
             dphone=gi("ship to contact phone", "d telephone no"),
             ddate=gi("delivery date"), psc=gi("product / service code"),
             pd=gi("product / description"), qty=gi("product qty"),
             serial=gi("serial number"), instr=gi("shipping instructions", "delivery instructions"),
             raised=gi("raised by"), approver=gi("approver"), account=gi("account"),
             otype=gi("order type"), hiab=gi("hiab"), escort=gi("vehicle escort"),
             pts=gi("pts"), banksman=gi("banksman"), moffett=gi("moffett"),
             loggrab=gi("log grab"), rsteer=gi("rear steer"), vtype=gi("vehicle type"),
             cc=gi("cost centre"), ndel=gi("notes for delivery location comments"))

    def g(r, key):
        i = C.get(key)
        return r[i] if (i is not None and i < len(r) and r[i] is not None) else ""

    def yn(r, key):
        v = str(g(r, key)).strip()
        return v if v else "N"

    def nsite(s):   # tolerate trailing '-' / whitespace / case (extract vs store)
        return str(s).strip().rstrip("-").strip().lower()
    norm = {nsite(k): v for k, v in SITES.items()}

    mapped, unmatched = [], {}
    for r in rows[1:]:
        if not str(g(r, "order")).strip():
            continue
        site = str(g(r, "site")).strip()
        sd = SITES.get(site) or norm.get(nsite(site))
        if sd is None and site:
            unmatched[site] = unmatched.get(site, 0) + 1
        sd = sd or {}

        cdate = _as_dt(g(r, "cdate"))
        ct = cte = ""
        if cdate:
            sh, eh = _hours(sd.get("start_hours")), _hours(sd.get("close_hours"))
            if sh is not None:
                ct = (cdate + sh).strftime("%d/%m/%Y %H:%M")
            if eh is not None:
                cte = (cdate + eh).strftime("%d/%m/%Y %H:%M")
        dt = dte = ""
        try:
            if ct:
                dt = (datetime.strptime(ct, "%d/%m/%Y %H:%M") + DELIVERY_OFFSET).strftime("%d/%m/%Y %H:%M")
            if cte:
                dte = (datetime.strptime(cte, "%d/%m/%Y %H:%M") + DELIVERY_OFFSET).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass

        ship = str(g(r, "ship")).strip()
        if not ship:
            ship = str(g(r, "instr"))[20:36].strip()   # MID(Delivery Instructions, 21, 16)
        serial = g(r, "serial")
        serial = "" if str(serial).strip() in ("0", "") else serial
        raised, email = str(g(r, "raised")).strip(), sd.get("email", "")
        raisedby = (raised + ";" + email) if (raised and email) else (email or raised)

        mapped.append({
            "Customer Order No": g(r, "order"), "Shipment No": ship,
            "Site Name - Collection": site, "Contact Name": sd.get("contact", ""),
            "Address 1": g(r, "a1"), "Address 2": g(r, "a2"), "Address 3": g(r, "a3"),
            "Postcode": OVERRIDES.get(site, g(r, "pc")), "Telephone No": sd.get("telephone", ""),
            "collection time": ct, "collection time end": cte,
            "Delivery Point": g(r, "dpoint"), "D Contact Name": g(r, "dcn"),
            "D Address 1": g(r, "da1"), "D Address 2": g(r, "da2"), "D Address 3": g(r, "da3"),
            "D Postcode": g(r, "dpc"), "D Telephone No": g(r, "dphone"),
            "delivery time": dt, "delivery time end": dte,
            "Product / Service Code": g(r, "psc"), "Product / Description": g(r, "pd"),
            "Product Qty": g(r, "qty"), "Serial Number": serial,
            "Delivery Instructions": g(r, "instr"), "Raised by": raisedby,
            "Cost Centre": g(r, "cc") or None, "Account": g(r, "account"),
            "Vehicle Type": g(r, "vtype"), "HIAB": yn(r, "hiab"),
            "Vehicle Escort": yn(r, "escort"), "PTS": yn(r, "pts"),
            "Banksman": yn(r, "banksman"), "Moffett": yn(r, "moffett"),
            "Log Grab": yn(r, "loggrab"), "Rear Steer": yn(r, "rsteer"),
            "Notes for Collection Location Comments": sd.get("notes", ""),
            "Notes for Delivery Location Comments": g(r, "ndel"), "Est Cost": None,
        })
    return mapped, unmatched


UNMATCHED_FILE = os.path.join(HERE, "_synergy_unmatched.json")
NEWSITES_FILE = os.path.join(HERE, "_synergy_newsites.json")


def main():
    args = sys.argv[1:]
    if args and args[0] == "addsites":
        # learn sites the dashboard collected (written to _synergy_newsites.json)
        try:
            sites = json.load(open(NEWSITES_FILE, encoding="utf-8"))
        except Exception:
            sites = {}
        for code, det in sites.items():
            add_site(code, det)
        print(f"Learned {len(sites)} new site(s): {', '.join(sites)}")
        return
    if not args or not os.path.exists(args[0]):
        print("Usage: python synergy_map.py <raw extract .xlsx>  |  synergy_map.py addsites"); return
    mapped, unmatched = map_orders(args[0])
    # record the misses for the dashboard site pop-up
    with open(UNMATCHED_FILE, "w", encoding="utf-8") as f:
        json.dump([{"site": s, "count": n} for s, n in sorted(unmatched.items(), key=lambda x: -x[1])],
                  f, indent=1)
    records = nr_csv.transform(mapped)
    name = "NR_upload_" + datetime.now().strftime("%d%m%Y%H%M%S") + ".csv"
    out = nr_csv.write_csv(records, outbox.path(name))
    print(f"Mapped {len(mapped)} order line(s).")
    if unmatched:
        print(f"  !! {len(unmatched)} collection site(s) NOT in the store - add these:")
        for s, n in sorted(unmatched.items(), key=lambda x: -x[1]):
            print(f"     {n:3}x  {s}")
    else:
        print("  all collection sites matched.")
    print(f"  CSV: {out}")


if __name__ == "__main__":
    main()
