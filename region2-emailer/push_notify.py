"""Phone alerts (Web Push), 24/11: the desk, installed on his phone from the dashboard, shows an alert when an email
needs him now - even with the desk closed. The inbox assistant calls notify() when a "now" item turns up.

The keys and the list of devices live here on the home PC and nowhere else. The cloud keeps nothing (every redeploy
wipes it), so the agent sends the public half up again on each panel push (panel()):

  _vapid.json       the VAPID key pair (P-256), made the first time it is asked for. The private half never leaves this
                    PC; a browser subscribes with the public half (public_key). A key file that is there but can't be
                    read is never replaced by a new key: every device subscribed with the old one would go quiet.
  _push_subs.json   each browser's PushSubscription, one per endpoint (subscribe / unsubscribe / count).

notify(title, body, url, tag) sends one alert to every device through pywebpush (pip install pywebpush - it brings
py_vapid and cryptography). A device whose push service answers 404 or 410 has gone (unsubscribed, the app removed) and
is dropped. It never raises: what happened comes back as {"sent": n, "dropped": m, "error": str|None}. pywebpush and
cryptography are imported only when they are needed, so importing this module never fails.

    python push_notify.py key          the public key a browser subscribes with
    python push_notify.py count        how many devices get alerts
    python push_notify.py test         a test alert to every device
"""
import base64
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
VAPID = os.path.join(HERE, "_vapid.json")
SUBS = os.path.join(HERE, "_push_subs.json")
CLOUD = os.path.join(HERE, "cloud.json")     # the dashboard's https address: the keys' contact (the JWT's "sub")
LOCK = "push_notify"                         # outlook_gate.named_lock: the two agents and inbox_assist write in turn

MAX_SUBS = 20                                # the oldest goes when one more turns up
TTL = 4 * 3600                               # a phone that is off for a while still gets it within 4 hours
TIMEOUT = 10                                 # seconds per device
# the browsers' push services (Chrome and Android, Safari and iPhone, Firefox, Edge). A subscription pointing anywhere
# else is refused, so the home PC only ever posts to these.
PUSH_HOSTS = ("googleapis.com", "push.apple.com", "push.services.mozilla.com", "notify.windows.com")
FALLBACK_SUBJECT = "mailto:alerts@example.com"
NO_PYWEBPUSH = "pywebpush is not installed on the home PC - run: pip install pywebpush"

_MISSING, _BAD = object(), object()


# ---------- small helpers ----------
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64u(s):
    s = str(s).strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _read(path, tries=8):
    """A JSON file's contents; _MISSING when there is no file, _BAD when it is there but can't be read. Windows refuses
    a file for a moment while another process swaps it in, so that is tried again first. (Every write here is whole -
    a .tmp swapped in - so a file that won't parse is broken, not half-written: that is not tried again.)"""
    for i in range(tries):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return _MISSING
        except PermissionError:
            if i == tries - 1:
                return _BAD
            time.sleep(0.1)
        except (OSError, ValueError):
            return _BAD
    return _BAD


def _write(path, data):
    """Write it whole to a .tmp beside it, then swap it in. Windows refuses the swap while another process has the
    file open (an agent counting the devices, say), so wait a moment and try again. OSError when it never goes."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(tmp, 0o600)                 # the key file: this user only (Windows: the folder's own rights stand)
    except OSError:
        pass
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(tmp, path)


def _lock(wait=10):
    """The store's lock (a Windows mutex, so a crash never leaves it held) -> a handle, or None if still busy."""
    try:
        import outlook_gate
        return outlook_gate.named_lock(LOCK, wait)
    except Exception:
        return True


def _unlock(h):
    try:
        import outlook_gate
        outlook_gate.release(h)
    except Exception:
        pass


# ---------- the keys ----------
def _make_keys():
    """A new P-256 key pair: the private number d and the uncompressed public point, both base64url. cryptography makes
    it - py_vapid, which pywebpush signs with, is a wrapper round it and reads d back with Vapid.from_string."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    d = key.private_numbers().private_value.to_bytes(32, "big")
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"private_key": _b64u(d), "public_key": _b64u(point), "made": _now()}


def _keys():
    """The key pair, made and saved the first time - or None when there is none (it can't be made, or the file is
    there but unreadable, which is never overwritten)."""
    k = _read(VAPID)
    if k is _MISSING:
        h = _lock()
        if h is None:
            return None
        try:
            k = _read(VAPID)                 # another process may have made them while this one waited
            if k is _MISSING:
                k = _make_keys()
                _write(VAPID, k)
        finally:
            _unlock(h)
    if isinstance(k, dict) and k.get("private_key") and k.get("public_key"):
        return k
    return None


def public_key():
    """The applicationServerKey a browser subscribes with: the public key as an uncompressed P-256 point, base64url.
    "" when there is no key and none can be made (panel() says why)."""
    try:
        k = _keys()
    except Exception:
        return ""
    return str(k["public_key"]) if k else ""


def _why_no_key():
    k = _read(VAPID)
    if k is _BAD or (k is not _MISSING and not (isinstance(k, dict) and k.get("private_key") and k.get("public_key"))):
        return ("the alert key file (_vapid.json) on the home PC can't be read - delete it to make a new one, then "
                "turn alerts on again on each device")
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return "the home PC can't make an alert key without cryptography - run: pip install pywebpush"
    return "the home PC has no alert key yet"


def _subject(keys):
    """The contact the push services are given (the JWT's "sub"): mailto: or https:, never a person's address in the
    code - a "subject" in _vapid.json, else the dashboard's own https address from cloud.json."""
    s = str(keys.get("subject") or "").strip()
    if s.startswith(("mailto:", "https://")):
        return s
    c = _read(CLOUD)
    if isinstance(c, dict):
        u = str(c.get("url") or "").strip().rstrip("/")
        if u.startswith("https://") and "YOUR-APP-URL" not in u:
            return u
    return FALLBACK_SUBJECT


# ---------- the devices ----------
def _subs():
    """The kept subscriptions (a list), or None when the file is there but can't be read."""
    d = _read(SUBS)
    if d is _MISSING:
        return []
    if d is _BAD:
        return None
    rows = d.get("subs", []) if isinstance(d, dict) else d
    return [s for s in rows if isinstance(s, dict) and s.get("endpoint") and isinstance(s.get("keys"), dict)] \
        if isinstance(rows, list) else None


def _clean(sub):
    """A browser's PushSubscription JSON -> (what is kept, "") or (None, why not)."""
    if not isinstance(sub, dict):
        return None, "no subscription came from the browser"
    ep = str(sub.get("endpoint") or "").strip()
    keys = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    p256dh, auth = str(keys.get("p256dh") or "").strip(), str(keys.get("auth") or "").strip()
    if not (ep and p256dh and auth):
        return None, "the browser's subscription came without its address or keys"
    if len(ep) > 2048 or len(p256dh) > 200 or len(auth) > 100:
        return None, "the browser's subscription is not one the desk can use"
    u = urlparse(ep)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
        return None, f"{host or 'that address'} is not a browser push service the desk knows"
    try:
        good = len(_unb64u(p256dh)) == 65 and len(_unb64u(auth)) >= 16
    except ValueError:
        good = False
    if not good:
        return None, "the browser's subscription keys are not right"
    return {"endpoint": ep, "keys": {"p256dh": p256dh, "auth": auth}, "added": _now()}, ""


def subscribe(sub):
    """Keep a browser's PushSubscription (its toJSON(): endpoint, keys.p256dh, keys.auth). One per endpoint: the same
    browser again only takes its newest keys. -> {"ok", "said", "subs"}; never raises."""
    try:
        clean, why = _clean(sub)
        if not clean:
            return {"ok": False, "said": why, "subs": count()}
        h = _lock()
        if h is None:
            return {"ok": False, "said": "the list of devices is busy - try again in a moment", "subs": count()}
        try:
            subs = _subs()
            if subs is None:
                return {"ok": False, "said": "the list of devices (_push_subs.json) on the home PC can't be read",
                        "subs": 0}
            old = next((s for s in subs if s["endpoint"] == clean["endpoint"]), None)
            if old:
                old.update({k: v for k, v in clean.items() if k != "added"})
            else:
                subs = (subs + [clean])[-MAX_SUBS:]
            _write(SUBS, {"subs": subs})
        finally:
            _unlock(h)
        n = len(subs)
        return {"ok": True, "subs": n, "new": old is None,
                "said": ("on for this device." if old is None else "this device was already on (its keys are kept up to "
                         "date).") + f" {n} device{'' if n == 1 else 's'} get{'s' if n == 1 else ''} them."}
    except Exception as e:
        return {"ok": False, "said": f"the device couldn't be kept: {e}", "subs": count()}


def _drop(endpoints):
    """Take these endpoints off the list -> how many went."""
    gone = {str(e or "").strip() for e in endpoints} - {""}
    if not gone:
        return 0
    h = _lock()
    if h is None:
        return 0
    try:
        subs = _subs()
        if not subs:
            return 0
        keep = [s for s in subs if s["endpoint"] not in gone]
        if len(keep) != len(subs):
            _write(SUBS, {"subs": keep})
        return len(subs) - len(keep)
    finally:
        _unlock(h)


def unsubscribe(endpoint):
    """Forget the device with this endpoint -> True when it was on the list; never raises."""
    try:
        return _drop([endpoint]) > 0
    except Exception:
        return False


def count():
    """How many devices get alerts."""
    try:
        return len(_subs() or [])
    except Exception:
        return 0


def panel():
    """For the agent's panel push: {"vapid": public key, "subs": devices}, with "error" when alerts can't go yet."""
    out = {"vapid": public_key(), "subs": count()}
    if not out["vapid"]:
        out["error"] = _why_no_key()
    else:
        try:
            import importlib.util
            if importlib.util.find_spec("pywebpush") is None:
                out["error"] = NO_PYWEBPUSH
        except Exception:
            pass
    return out


# ---------- sending ----------
def _webpush():
    """pywebpush's webpush(), imported only when an alert goes (ImportError when it isn't installed)."""
    from pywebpush import webpush
    return webpush


def _payload(title, body, url, tag):
    """What the service worker shows (sw.js's push event): title, body, the desk page a tap opens, and a tag (an alert
    with the same tag replaces the last one). Kept well inside the push services' 4 KB."""
    url = str(url or "/").strip()
    if not url.startswith("/") or url.startswith("//"):
        url = "/"                            # only the desk's own pages
    d = {"title": str(title or "Haulage Desk")[:120], "body": str(body or "")[:1000], "url": url[:300]}
    if tag:
        d["tag"] = str(tag)[:64]
    data = json.dumps(d, ensure_ascii=False)
    while len(data.encode("utf-8")) > 3000 and d["body"]:
        d["body"] = d["body"][:-100]
        data = json.dumps(d, ensure_ascii=False)
    return data


def _failed(e, code):
    words = str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__
    return f"{words} ({code})" if code and str(code) not in words else words


def notify(title, body, url="/", tag=None):
    """One alert to every device. A device whose push service answers 404 or 410 is dropped; any other failure is said
    and the device kept. Never raises. -> {"sent": n, "dropped": m, "error": str|None}"""
    out = {"sent": 0, "dropped": 0, "error": None}
    try:
        try:
            webpush = _webpush()
        except ImportError:
            out["error"] = NO_PYWEBPUSH
            return out
        keys = _keys()
        if not keys:
            out["error"] = _why_no_key()
            return out
        subs = _subs()
        if subs is None:
            out["error"] = "the list of devices (_push_subs.json) on the home PC can't be read"
            return out
        data = _payload(title, body, url, tag)
        claims = {"sub": _subject(keys)}
        gone, failed = [], []
        for s in subs:
            try:
                # fresh dicts each time: pywebpush writes the push service's "aud" into the claims and its own headers
                # into these, and the next device may be on another service
                webpush(subscription_info={"endpoint": s["endpoint"], "keys": dict(s["keys"])}, data=data,
                        vapid_private_key=keys["private_key"], vapid_claims=dict(claims), ttl=TTL,
                        timeout=TIMEOUT, headers={"Urgency": "high"})
                out["sent"] += 1
            except Exception as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (404, 410):
                    gone.append(s["endpoint"])
                else:
                    failed.append(_failed(e, code))
        if gone:
            out["dropped"] = _drop(gone)
        if failed:
            out["error"] = failed[0] + (f" (and {len(failed) - 1} more)" if len(failed) > 1 else "")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "key":
        print(public_key() or panel().get("error", ""))
    elif what == "count":
        print(count())
    elif what == "test":
        print(json.dumps(notify("Test alert", "Phone alerts are working", "/")))
    else:
        print(__doc__)
