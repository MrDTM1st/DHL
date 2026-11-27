"""
Bagged ballast onto vehicles - his rule (27/11, on an order of 30 bags booked as 15 + 15 on two artics): "What you were
supposed to do was put 10 on a rigid and 20 on an Arctic. You don't ever split it down into 15s to put on 2 Arctics
because you're just wasting space. Unless I explicitly say so ... 99% of the time, you'll do 10 and 20."

Every vehicle is filled to the most it takes before the next one is used (his load rule of 31/10): an artic HIAB takes
20 one-tonne bags (20,280 kg), a rigid HIAB 10. What is left for the last vehicle goes on a rigid when it is 10 bags or
fewer:

    30 bags, an artic picked  ->  20 on the artic, 10 on a rigid
    45 bags, an artic picked  ->  20, 20, then 5 on a rigid
    35 bags, an artic picked  ->  20, then 15 on a second artic (15 is more than a rigid takes)
    30 bags, a rigid picked   ->  three rigids of 10 (his "3 manifests of 10", the same day, when the fleet asked)

Only for an order that is nothing but 1 t bags of ballast (ctms_run_plan.ballast_bags): its bag count is its weight.
CTMS's Split Orders only halves a line, so Book splits it, sets each part's quantity to its load, and books each part
on its own trailer (work_pc/ctms_book.py). "Split equally" on the Book form is his say-so for the old way.
"""
RIGID = "NR_FLAT_RIG"
ARTIC = "NR_ARTIC_FL"
RIGID_BAGS = 10                                  # a rigid HIAB: 10,000 kg
ARTIC_BAGS = 20                                  # an artic HIAB: 20,280 kg
RIGIDS = {RIGID}
ARTICS = {ARTIC}


def most(trailer, carrier=""):
    """The bags one vehicle of this trailer takes; None for a trailer the rule doesn't know. (carrier: kept for a
    haulier whose artic takes fewer - none is set.)"""
    if trailer in RIGIDS:
        return RIGID_BAGS
    if trailer in ARTICS:
        return ARTIC_BAGS
    return None


def loads(bags, trailer, carrier=""):
    """[(bags, trailer)], a vehicle each in booking order - each full before the next, what is left on a rigid when it is
    10 bags or fewer. trailer: the one picked for the job; a rigid keeps every vehicle a rigid. None when the rule
    doesn't cover it: no bags, or a trailer that is neither the artic nor the rigid flat."""
    bags = int(bags or 0)
    cap = most(trailer, carrier)
    if bags <= 0 or cap is None:
        return None
    full, rest = divmod(bags, cap)
    out = [(cap, trailer)] * full
    if rest:
        out.append((rest, RIGID if rest <= RIGID_BAGS else trailer))
    return out


def as_job(plan):
    """The loads as a booking job carries them: [{"qty", "trailer"}]."""
    return [{"qty": q, "trailer": t} for q, t in plan or []]


def said(plan):
    """The loads in his words: "20 bags on NR_ARTIC_FL and 10 on NR_FLAT_RIG"."""
    bits = [f"{q} on {t}" for q, t in plan or []]
    if not bits:
        return ""
    bits[0] = bits[0].replace(" on ", " bags on ", 1)
    return bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " and " + bits[-1]


def check(job_loads, bags=None):
    """A job's loads as given ([{"qty", "trailer"}]) -> [(qty, trailer)], or ValueError saying what's wrong: each load a
    whole number of bags over 0 on a trailer, and - when the order's bags are known - adding up to them exactly (never
    more in the well than the order holds, his 26/11)."""
    out = []
    for x in job_loads or []:
        try:
            q, t = float(x.get("qty")), str(x.get("trailer") or "").strip()
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"a load reads {x!r}, not a quantity and a trailer")
        if q <= 0 or q != int(q) or not t:
            raise ValueError(f"a load reads {x!r}: it needs a whole quantity over 0 and a trailer")
        out.append((int(q), t))
    if len(out) < 2:
        raise ValueError("loads are for a job going on two vehicles or more")
    if bags is not None and sum(q for q, _ in out) != int(bags):
        raise ValueError(f"the loads add up to {sum(q for q, _ in out)}, not the order's {int(bags)}")
    return out
