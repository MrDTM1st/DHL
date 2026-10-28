"""
CTMS screen capture - the walkthrough, without you saving anything by hand.

With the debug browser open (run start_here.py first) and CTMS logged in:

    python ctms_capture.py

It walks you through the screens the booking automation needs, in the order
you would meet them doing the job. Get each one on screen in the browser,
press ENTER here, and it snapshots: URL, title, full HTML including inside
frames, every field with its id/name/label/dropdown options, a PNG, and the
network calls the page made.

You drive CTMS. This only ever takes pictures - it never clicks, types or
submits. The one screen it asks you to fill in yourself is the booking form,
and it asks you NOT to submit it.

Guided rather than free-form on purpose: a walkthrough that comes back
without the filled-in booking form has to be done again, and the point is
that this takes one pass.

NOTE it records page text, field values, and (if you say yes) request URLs
and POST bodies from your own session - so it will contain order data.
Avoid capturing screens showing anything you would not want in your own
mailbox.
"""
import base64
import json
import os
import re
import sys
from datetime import datetime

# The websocket client and the page walkers live in cdp.py now, shared with
# ctms_bridge.py - the dashboard's "Capture this screen" takes exactly the
# snapshot this script does, so the two must never drift apart.
from cdp import FIELDS_JS, HTML_JS, WS, http_json

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "ctms_capture")


def pick_page():
    pages = [t for t in http_json("/json") if t.get("type") == "page"]
    if not pages:
        print("No tabs found - is the debug browser open?")
        sys.exit(1)
    if len(pages) == 1:
        return pages[0]
    print("\nWhich tab?")
    for i, t in enumerate(pages):
        print(f"  [{i}] {t.get('title','?')[:55]} | {t.get('url','?')[:60]}")
    return pages[int(input("number: ").strip() or 0)]


# The exact screens CTMS_BOOKING_SPEC needs, in the order you would meet them
# doing the job. Guided rather than free-form because a walkthrough that comes
# back missing the filled-in booking form is a walkthrough that has to be done
# again - and the whole point is that this takes one pass.
SCREENS = [
    ("home", "the landing page after you log in"),
    ("order-search", "the order search screen, BEFORE you search"),
    ("search-results", "the results list for a real order"),
    ("order-open", "one order opened, showing its detail"),
    ("booking-form-empty", "the booking form, before you type anything"),
    ("booking-form-filled", "the SAME form filled in for a real job - do NOT submit yet."
                            "  *** the most important capture of the lot ***"),
    ("confirmation", "after you submit it by hand - the confirmation/reference"),
    ("booked-job", "an already-booked job reopened (the update flow)"),
    ("validation-error", "a form with a validation error, if one is easy to provoke"),
]


def capture(ws, label, n, want_network):
    """One screen: URL, title, HTML (frames included), fields, PNG, network."""
    ws.call("Runtime.enable")
    url = ws.evaluate("location.href")
    title = ws.evaluate("document.title")
    html = ws.evaluate(HTML_JS) or ""
    fields = json.loads(ws.evaluate(FIELDS_JS) or "[]")
    shot = None
    try:
        ws.call("Page.enable")
        shot = ws.call("Page.captureScreenshot", {"format": "png"}).get("data")
    except Exception as e:
        print(f"  (no screenshot: {type(e).__name__}: {e})")

    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)[:40]
    stamp = datetime.now().strftime("%H%M%S")
    base = os.path.join(OUTDIR, f"{n:02d}_{safe}_{stamp}")
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(base + "_fields.json", "w", encoding="utf-8") as f:
        f.write(json.dumps({"url": url, "title": title, "fields": fields}, indent=1))
    if shot:
        with open(base + ".png", "wb") as f:
            f.write(base64.b64decode(shot))

    calls = []
    if want_network:
        for ev in ws.events:
            if ev.get("method") == "Network.requestWillBeSent":
                r = ev["params"].get("request", {})
                calls.append({"method": r.get("method"), "url": (r.get("url") or "")[:300],
                              "postData": (r.get("postData") or "")[:2000],
                              "type": ev["params"].get("type")})
        ws.events.clear()
        if calls:
            with open(base + "_network.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(calls, indent=1))

    frames = sorted({f.get("where") for f in fields} - {"page"})
    print(f"  captured: {title} | {url}")
    print(f"  {len(fields)} field(s)"
          + (f" across {len(frames)} frame/shadow root(s)" if frames else "")
          + (f", {len(calls)} network call(s)" if calls else ""))
    return base


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    print(__doc__)

    want_network = input(
        "Also record the network calls CTMS makes? That tells us whether it\n"
        "posts bookings to an API (much more reliable to automate) or submits\n"
        "a form. It records URLs and POST bodies of YOUR OWN session - so it\n"
        "may include order data. [Y/n]: ").strip().lower() not in ("n", "no")

    page = pick_page()
    ws = WS(page["webSocketDebuggerUrl"])
    if want_network:
        try:
            ws.call("Network.enable")
            print("  network recording on")
        except Exception as e:
            print(f"  network recording unavailable: {type(e).__name__}: {e}")
            want_network = False

    n = 0
    print("\nWork through CTMS as normal. For each screen below, get it on")
    print("screen in the browser, then press ENTER here. 's' skips one.\n")
    try:
        for label, what in SCREENS:
            ans = input(f"  [{label}] {what}\n  ENTER to capture / s to skip: ").strip().lower()
            if ans == "s":
                print("  skipped\n")
                continue
            n += 1
            base = capture(ws, label, n, want_network)
            print(f"  -> {os.path.basename(base)}.*\n")

        while True:
            extra = input("Any other screen worth having? Name it, or ENTER to finish: ").strip()
            if not extra:
                break
            n += 1
            capture(ws, extra, n, want_network)
    finally:
        ws.close()
    print(f"\nDone. {n} screen(s) in {OUTDIR}")
    print("Zip that folder and email it to yourself, subject: CTMS walkthrough")
    return


if __name__ == "__main__":
    main()
