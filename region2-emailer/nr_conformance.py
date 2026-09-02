"""Check an NR upload CSV against the real Network_Rail_Order_Database format.

The rules below are not invented. They were derived from 47 CSVs that the
ORIGINAL Access database produced between 28/08/2026 and 02/09/2026 - files
Network Rail actually accepted - kept locally in _nr_truth/ (gitignored: they
carry real site contacts). Every threshold is a fact counted off that corpus,
and the count is quoted so a future reader can re-check it rather than trust it.

The single most important thing the corpus proves:

    THE GENUINE EXPORTER IS NOT A CSV WRITER.

It is a naive ",".join(35 fields) + CRLF. Splitting all 2,687 lines on a bare
comma with no quote awareness yields exactly 35 fields every time. There are two
double-quote characters in the whole corpus and both are literal data - one an
UNBALANCED opening quote that Python's csv.reader silently swallows four records
on. Network Rail accepted that file, so their importer splits naively too. Never
write these with csv.writer and never read them with csv.reader.

    python nr_conformance.py <file.csv> [more.csv ...]
    python nr_conformance.py --truth        # re-check the reference corpus
    python nr_conformance.py --pairs        # replay the ad hoc Material pick-list
"""
import os
import re
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
TRUTH = os.path.join(HERE, "_nr_truth")

WIDTH = 35                     # 2687/2687 lines, no exceptions
RECORDS = ("ORDER", "ORD_TASKS", "ORD_SUB_REFS", "ORD_LINES", "ITEMS")
# 431/431 genuine task rows use one of these, always with value "1".
# BANKSMAN is unseen in the 47 files but is a real CTMS code, so it is allowed
# rather than flagged - absence from a 47-file sample is not proof it is wrong.
TASK_CODES = ("HIAB", "REAR STEER", "LOG GRAB", "PTS", "ESCORTS", "MOFFETT",
              "BANKSMAN")
SUB_REFS = ("1002", "1003")
DT = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$")


def check(path):
    """Return a list of complaint strings. Empty list == conformant."""
    bad = []
    raw = open(path, "rb").read()

    # ---- bytes ----
    if raw.startswith(b"\xef\xbb\xbf") or raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        bad.append("has a BOM; 0 of 47 genuine files carry one")
    try:
        raw.decode("cp1252")
    except UnicodeDecodeError as e:
        bad.append(f"not decodable as cp1252 ({e}); the genuine export is "
                   f"single-byte ANSI, never UTF-8")
    if raw and b"\r\n" not in raw:
        bad.append("no CRLF anywhere - genuine files are CRLF throughout "
                   "(2687 CRLF, 0 bare LF across the corpus)")
    if re.search(rb"(?<!\r)\n", raw):          # a LF not preceded by CR
        bad.append("contains a bare LF; every genuine record ends CRLF")
    if raw and not raw.endswith(b"\r\n"):
        bad.append("last record is not terminated; 47/47 genuine files end CRLF")
    if b"\r\n\r\n" in raw:
        bad.append("blank line present; CRLF CRLF never occurs in the corpus")

    text = raw.decode("cp1252", errors="replace")
    lines = [l for l in text.split("\r\n") if l != ""]
    if not lines:
        return bad + ["empty file"]
    if not lines[0].startswith("ORDER,"):
        bad.append(f"starts {lines[0][:20]!r}; genuine files have no header and "
                   f"always open with 'ORDER,'")

    # ---- per line, split NAIVELY on purpose ----
    for n, line in enumerate(lines, 1):
        f = line.split(",")
        if len(f) != WIDTH:
            bad.append(f"line {n}: {len(f)} fields, expected exactly {WIDTH} "
                       f"(a comma survived into a value, or padding is wrong)")
            continue
        if f[0] not in RECORDS:
            bad.append(f"line {n}: unknown record type {f[0]!r}")
        if f[WIDTH - 1] != "":
            bad.append(f"line {n}: field 35 is {f[WIDTH - 1]!r}; it is empty on "
                       f"all 2687 genuine lines")
        if f[0] == "ORD_TASKS":
            if f[1] not in TASK_CODES:
                bad.append(f"line {n}: task code {f[1]!r} is not a real one "
                           f"(genuine: HIAB/REAR STEER/LOG GRAB/PTS/ESCORTS/MOFFETT)")
            if f[2] != "1":
                bad.append(f"line {n}: task value {f[2]!r}; genuine is always '1'")
        if f[0] == "ORD_SUB_REFS":
            if f[1] not in SUB_REFS:
                bad.append(f"line {n}: sub-ref code {f[1]!r}; genuine uses only "
                           f"1002 and 1003")
            if f[2].strip() == "":
                bad.append(f"line {n}: sub-ref {f[1]} is empty; the genuine "
                           f"export never emits an empty one (1003 defaults to '0')")
        if f[0] == "ITEMS" and f[1].strip() == "":
            bad.append(f"line {n}: ITEMS product is blank")
        if f[0] == "ORDER":
            for idx, what in ((13, "collection start"), (14, "collection end"),
                              (25, "delivery start"), (26, "delivery end")):
                v = f[idx]
                if v and not DT.match(v):
                    bad.append(f"line {n}: {what} {v!r} is not 'dd/mm/yyyy HH:MM'")

    # ---- block structure ----
    seq, order_n = [], 0
    for line in lines:
        t = line.split(",")[0]
        if t == "ORDER":
            order_n += 1
            if seq:
                bad.extend(_block(seq, order_n - 1))
            seq = [t]
        else:
            seq.append(t)
    if seq:
        bad.extend(_block(seq, order_n))
    return bad


def _block(seq, n):
    """One ORDER's records must run tasks -> sub-refs -> lines -> items."""
    out = []
    rank = {"ORDER": 0, "ORD_TASKS": 1, "ORD_SUB_REFS": 2, "ORD_LINES": 3,
            "ITEMS": 4}
    got = [rank.get(t, 9) for t in seq]
    if got != sorted(got):
        out.append(f"order block {n}: records out of order ({'|'.join(seq)}); "
                   f"genuine order is ORDER, ORD_TASKS, ORD_SUB_REFS, "
                   f"ORD_LINES, ITEMS")
    lines_ = seq.count("ORD_LINES")
    items = seq.count("ITEMS")
    subs = seq.count("ORD_SUB_REFS")
    if lines_ != items:
        out.append(f"order block {n}: {lines_} ORD_LINES but {items} ITEMS; "
                   f"they pair 1:1 (510 and 510 across the corpus)")
    if lines_ and subs != 2 * lines_:
        out.append(f"order block {n}: {subs} ORD_SUB_REFS for {lines_} ORD_LINES; "
                   f"the genuine export writes a 1002 and a 1003 PER LINE "
                   f"(1018 sub-refs against 510 lines)")
    return out


def pairs():
    """Replay the ad hoc Material -> ITEMS pairs the corpus proves.

    19 genuine orders carry the Haulage Request Form shape in their delivery
    instructions, which pairs each form Material with the ITEMS value the real
    database wrote. This runs our mapping over those same Materials and reports
    what still differs, so nr_csv.ADHOC_ITEMS cannot drift without saying so.

    Three Box rows are expected to differ: the corpus contradicts itself there
    ("Box" -> "Box." twice, "Box." -> "BOX" once) and we pass Box through
    rather than pick one. Anything ELSE differing is a regression.
    """
    import nr_csv
    pat = re.compile(r"^Material\s+(.*?)\s+Dimension", re.I)
    rows = []
    for p in sorted(glob.glob(os.path.join(TRUTH, "*.csv"))):
        cur = None
        for line in open(p, "rb").read().decode("cp1252", "replace").split("\r\n"):
            f = line.split(",")
            if len(f) != WIDTH:
                continue
            if f[0] == "ORDER":
                m = pat.match(f[27] or "")
                cur = (m.group(1).strip() if m else None, f[28])
            elif f[0] == "ITEMS" and cur and cur[0] is not None:
                rows.append((cur[0], f[1], cur[1]))
                cur = None
    if not rows:
        print(f"No reference corpus at {TRUTH}")
        return 2
    diff = [(m, g, nr_csv.adhoc_item(m, a)) for m, g, a in rows
            if nr_csv.adhoc_item(m, a) != g]
    for m, g, o in diff:
        print(f"  differs  Material {m!r}: genuine {g!r}, ours {o!r}")
    print(f"\n  {len(rows) - len(diff)}/{len(rows)} ad hoc Materials reproduce "
          f"the genuine ITEMS value")
    unexpected = [d for d in diff if d[0].strip().lower().rstrip(".") != "box"]
    if unexpected:
        print(f"  {len(unexpected)} UNEXPECTED - only the Box rows should differ")
        return 1
    return 0


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    if args and args[0] == "--pairs":
        return pairs()
    if args and args[0] == "--truth":
        args = sorted(glob.glob(os.path.join(TRUTH, "*.csv")))
        if not args:
            print(f"No reference corpus at {TRUTH}")
            return 2
    if not args:
        print(__doc__)
        return 2
    worst, failed = 0, 0
    for p in args:
        if not os.path.exists(p):
            print(f"  ??    {p} - not found")
            worst = 2
            continue
        bad = check(p)
        if bad:
            worst = worst or 1
            failed += 1
            print(f"  FAIL  {os.path.basename(p)}")
            seen = {}
            for b in bad:                       # collapse repeats, keep the first
                k = re.sub(r"line \d+", "line N",
                           re.sub(r"block \d+", "block N", b))
                seen.setdefault(k, [0, b])
                seen[k][0] += 1
            for k, (c, first) in list(seen.items())[:12]:
                print(f"          {first}" + (f"   (x{c})" if c > 1 else ""))
            if len(seen) > 12:
                print(f"          ... and {len(seen) - 12} more kind(s)")
        else:
            print(f"  ok    {os.path.basename(p)}")
    print(f"\n  {len(args) - failed}/{len(args)} conformant")
    return worst


if __name__ == "__main__":
    sys.exit(main())
