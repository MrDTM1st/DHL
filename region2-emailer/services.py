"""
Night, weekend and bank-holiday services on an order.

One rule, used by every upload - media sets, Synergy, ad hoc forms - so a job
cannot pick up NIGHT on one route and not on another.

    NIGHT          delivery between 21:00 and 04:00
    SATURDAY       the driver's day is a Saturday
    SUN_BANK_HOL   the driver's day is a Sunday or a bank holiday

The day service is the day the DRIVER FINISHES, not always the delivery date.
A job delivering late at night is still on the road after midnight, so from
23:00 onwards the day rolls forward. That is why a Friday 23:00 drop is a
SATURDAY job, and so is one timed 00:00 on the Friday - midnight is already
into the small hours as far as the driver is concerned.

The two thresholds are deliberately different, and it is not a typo:

    21:00  a job is a NIGHT job from here
    23:00  the day rolls to tomorrow from here

So a 22:00 delivery on a Friday is a night job that still counts as Friday;
23:00 on the same Friday is a night job that counts as Saturday.

Sunday and bank holidays share one service - SUN_BANK_HOL - because they are
charged the same. Any bank holiday counts, not only the Monday ones: Good
Friday and Boxing Day are worked no differently.

Keep the labels free of punctuation. CTMS silently refused the one order
carrying "SUN/BANK_HOL" while NIGHT and SATURDAY went through in the same
upload, and a refused order looks like nothing at all until someone notices it
missing days later. If a new service is ever added, name it in the same style.
"""
from datetime import date, datetime, time, timedelta

NIGHT_FROM = time(21, 0)      # a NIGHT job from here...
NIGHT_TO = time(4, 0)         # ...until here, the next morning
ROLL_FROM = time(23, 0)       # ...but the DAY only rolls forward from here

NIGHT = "NIGHT"
SATURDAY = "SATURDAY"
# Underscore, NOT a slash. CTMS rejected the order carrying "SUN/BANK_HOL"
# while the same week's NIGHT and SATURDAY orders went through untouched - the
# two labels with no punctuation in them. It is the only label that appeared
# solely on the failed order, so the name is what it choked on, not the rule.
SUN_BANK_HOL = "SUN_BANK_HOL"

# England & Wales bank holidays. phase2.py imports this rather than keeping a
# second copy - one list, so the chasers and the services can never disagree
# about whether a day is worked. Extend as the years roll on.
BANK_HOLIDAYS = {
    "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25",
    "2026-08-31", "2026-12-25", "2026-12-28",
    "2027-01-01", "2027-03-26", "2027-03-29", "2027-05-03", "2027-05-31",
    "2027-08-30", "2027-12-27", "2027-12-28",
}


def is_bank_holiday(d):
    return d is not None and d.strftime("%Y-%m-%d") in BANK_HOLIDAYS


def _as_dt(v):
    """A delivery datetime out of whatever the mapper had to hand."""
    if isinstance(v, datetime):
        return v
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S",
              "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(str(v).strip(), f)
        except Exception:
            pass
    return None


def is_night(t):
    """21:00 to 04:00, wrapping midnight."""
    return t is not None and (t >= NIGHT_FROM or t < NIGHT_TO)


def rolls_over(t):
    """23:00 to 04:00 - the driver finishes on the following day."""
    return t is not None and (t >= ROLL_FROM or t < NIGHT_TO)


def driver_day(delivery_dt):
    """The date the driver is actually working, or None."""
    dt = _as_dt(delivery_dt)
    if dt is None:
        return None
    return dt.date() + timedelta(days=1) if rolls_over(dt.time()) else dt.date()


def for_delivery(delivery_dt):
    """The services this delivery attracts, e.g. ['NIGHT', 'SATURDAY'].

    Empty for a weekday daytime drop, which is most of them.
    """
    dt = _as_dt(delivery_dt)
    if dt is None:
        return []
    out = []
    if is_night(dt.time()):
        out.append(NIGHT)
    day = driver_day(dt)
    if day.weekday() == 5:
        out.append(SATURDAY)
    elif day.weekday() == 6 or is_bank_holiday(day):
        out.append(SUN_BANK_HOL)
    return out


def explain(delivery_dt):
    """One line for a preview, so the reason is visible before it is uploaded."""
    dt = _as_dt(delivery_dt)
    if dt is None:
        return "no delivery time - no services"
    svc = for_delivery(dt)
    day = driver_day(dt)
    rolled = " (rolled to the next day)" if day != dt.date() else ""
    return (f"{dt:%a %d/%m %H:%M} -> driver's day {day:%a %d/%m}{rolled}"
            f" -> {', '.join(svc) if svc else 'no services'}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(explain(" ".join(sys.argv[1:])))
    else:
        print(__doc__)
        for s in ("2026-08-07 14:00", "2026-08-07 22:00", "2026-08-07 23:00",
                  "2026-08-07 00:00", "2026-08-08 10:00", "2026-08-08 23:30",
                  "2026-08-09 09:00", "2026-08-31 10:00", "2026-08-30 23:30"):
            print("  " + explain(s))
