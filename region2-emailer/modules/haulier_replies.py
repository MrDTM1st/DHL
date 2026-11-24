"""What did a haulier say back to a cover request? - quote, a plain no, or
something that needs the planner.

Used to file the plain no's out of the Inbox (decline_sweep.py): a ring-round
asks 5-10 hauliers per job, most say no, and the no's buried the quotes and the
questions. Only a CLEAN no is filed - anything with a price, a question, an
offer of another day or vehicle, a chase, or wording we are not sure of stays
where the planner will see it. Every pattern below is from a real reply (02/10/2026).
"""
import re

# a price - but not a liability limit in a signature ("£100 PER TONNE")
PRICE = re.compile(r"£\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?!\s*(?:per|/)\s*(?:tonne|ton)\b)", re.I)
DECLINE = re.compile(
    r"(?i)(\bunable\b|\bcan'?t\b|\bcannot\b|\bno availability\b|\bnot available\b|\bfully booked\b|"
    r"\bdecline\b|\bpass on this\b|\bno vehicles?\b|^\s*no\b|\bno,? sorry\b|\bstruggl(e|ing)\b|"
    r"\bout of (my|our) area\b|\bnothing for (this|that|you)\b|\bnot at such short notice\b|"
    r"\bnothing in\b|\bhave nothing\b|"
    r"\bbooked up\b|\bnot (for )?us\b|\bwon'?t be able\b|\bcouldn'?t\b|\bnot able\b|"
    r"\bno drivers?\b|\bdon'?t have (any )?(drivers?|vehicles?|trucks?|wagons?)\b|"
    r"\bnot this time\b|\bunfortunately not\b)")
# anything that turns a "no" into "no, but..." - an offer the planner should see
OFFER = re.compile(
    r"(?i)(\binstead\b|\bother day\b|\banother day\b|\bany other day\b|\bcould do\b|\bcan do\b|"
    r"\bwould be able\b|\bbe able to do\b|\bavailable (on|for|from|next)\b|\bif (that|it) helps?\b|"
    r"\bif you can\b|\bif the date\b|\bif you could\b|\bwould work\b|\bmonday|\btuesday|\bwednesday|"
    r"\bthursday|\bfriday|\bsaturday|\bsunday|\btomorrow\b|\bnext week\b|\bone of\b|\bdo \d\b|\bpart\b|"
    r"\brigid\b|\bartic\b|\bflat\b|\bhiab\b|\btipper\b|\binstead\b|\bshort trailer\b|"
    # "we usually collect this order from Land Recovery - if the collection
    # point changes, give us a call and we may be able to cover" (a haulier, 05/10)
    r"\bif\b|\busually\b|\bnormally\b|\bgive (us|me) a (call|ring|bell)\b|\bcall (us|me)\b|"
    r"\bmay be able\b|\bmight be able\b|\bcould\b|\bchange[sd]?\b)")
QUESTION = re.compile(r"\?")
AUTOACK = re.compile(r"(?i)(reply above this line|your request #|has been received|automatic reply|"
                     r"out of (the )?office|auto-?reply)")
SIGNOFF = re.compile(r"(?i)^\s*(kind regards|best regards|many thanks|regards|thanks|thank you|"
                     r"best wishes|cheers|sent from my \w+)[\s,!.]*$")
QUOTE_START = re.compile(r"\s*(From:|Sent:|-----Original|On .* wrote:|_{6,})")


def own_text(body):
    """The reply itself: above the quoted ask AND above the signature."""
    out = []
    for line in str(body or "").replace("’", "'").splitlines():
        if QUOTE_START.match(line) and any(x.strip() for x in out):
            break
        if SIGNOFF.match(line) and any(x.strip() for x in out):
            break
        out.append(line)
    return "\n".join(out).strip()


def classify(body):
    """'quote' | 'decline' | 'other'. Only 'decline' is ever filed away."""
    t = own_text(body)
    if not t:
        return "other"
    if PRICE.search(t):
        return "quote"
    if AUTOACK.search(t):
        return "other"
    if QUESTION.search(t):
        return "other"            # a question back - the planner owes them an answer
    if not DECLINE.search(t):
        return "other"
    if OFFER.search(t):
        return "other"            # "no, but I could do Tuesday / one rigid" - worth seeing
    if len(t) > 400:
        return "other"            # a long reply is rarely just a no
    return "decline"
