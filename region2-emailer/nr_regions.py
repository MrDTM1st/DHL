"""Which Network Rail region a postcode belongs to - R1 / R2 / R3 / R4.

Built from the "Postcode Areas Search" workbook, which is the authoritative
list. This is NOT the same thing as `postcode_regions.json`: that one maps a
postcode DISTRICT to an administrative region and town ("DN16" -> "North
Lincolnshire" / "Scunthorpe") and feeds the region/town columns of the NR
upload. This maps a postcode AREA to the NR OPERATING region, which is what
decides whether a job is ours at all.

Region is keyed on the AREA (the letters), and that is safe rather than a
simplification: the source workbook lists per-district rows for the big
single-letter areas (B1..B99, S1..S99, and the same for E, G, L, M, N, W), and
every one of those districts agrees with its own area's region. No area is
split across two NR regions, so there is nothing finer to encode.

    nr_regions.region_of("DN16 1BP")   -> "R2"
    nr_regions.region_of("BS119DE")    -> "R3"
    nr_regions.is_region("S60 1BX", "R2") -> True
"""
import json
import os

import postcodes

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, "nr_regions.json")

with open(_PATH, encoding="utf-8") as _f:
    AREAS = json.load(_f)


def region_of(pc):
    """NR region for a postcode, or "" when the area isn't in the list."""
    return (AREAS.get(postcodes.area(pc)) or {}).get("region", "")


def town_of(pc):
    """The town the workbook names for that postcode area, or ""."""
    return (AREAS.get(postcodes.area(pc)) or {}).get("town", "")


def is_region(pc, region):
    return bool(region) and region_of(pc) == str(region).strip().upper()


def areas_in(region):
    """Every postcode area in a region - e.g. the Region 2 scope list."""
    region = str(region).strip().upper()
    return sorted(a for a, v in AREAS.items() if v.get("region") == region)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for pc in sys.argv[1:]:
            r = region_of(pc)
            print(f"{pc:<12} {r or 'not in the list':<8} {town_of(pc)}")
    else:
        for r in sorted({v["region"] for v in AREAS.values()}):
            a = areas_in(r)
            print(f"{r}  ({len(a):>2}): {' '.join(a)}")
