"""
The bank-holiday calendar. Nothing else.

This module used to work out NIGHT, SATURDAY and SUN_BANK_HOL from a delivery
time and nr_csv.py put an ORD_TASKS row on the upload for each one. That is
gone: no upload adds a service flag by itself any more. If a job genuinely
needs one it goes on by hand, where whoever puts it there has decided it.

Do not reinstate the derivation here or in a mapper - the point is that no
route adds these silently. Deciding a job is a night or weekend job is a
person's call, not the uploader's.

What is left is the England & Wales bank-holiday list, which phase2.py imports
for the chaser cadence - one list, so the chasers can never disagree with
anything else about whether a day is worked. Extend as the years roll on.
"""

BANK_HOLIDAYS = {
    "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25",
    "2026-08-31", "2026-12-25", "2026-12-28",
    "2027-01-01", "2027-03-26", "2027-03-29", "2027-05-03", "2027-05-31",
    "2027-08-30", "2027-12-27", "2027-12-28",
}


def is_bank_holiday(d):
    return d is not None and d.strftime("%Y-%m-%d") in BANK_HOLIDAYS


if __name__ == "__main__":
    print(__doc__)
    print(f"  {len(BANK_HOLIDAYS)} bank holidays: "
          f"{', '.join(sorted(BANK_HOLIDAYS))}")
