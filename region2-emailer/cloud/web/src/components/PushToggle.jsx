import { useCallback, useEffect, useState } from 'react';

// Phone alerts (push_notify.py on the home PC, 24/11): an alert on this phone or computer when an email needs him now,
// even with the desk closed. The keys and the list of devices live on the home PC - the cloud forgets everything on a
// redeploy - so the home PC hands its public key up on its panel: `push` is {vapid, subs}, with `error` when it can't
// send yet. Turn on subscribes this browser with that key and sends the subscription home (push_subscribe); Send a test
// asks the home PC for one (push_test); Turn off unsubscribes here and tells the home PC (push_unsubscribe).
// In Settings it is a card; `compact` is the small button in the Needs-you card's head.

const IOS_HINT = 'On iPhone: tap Share > Add to Home Screen, open the desk from there, then turn alerts on';
const BLOCKED = "The browser blocked alerts for the desk. Allow notifications for this site in the browser's settings, "
  + 'then come back here.';

export function urlBase64ToUint8Array(s) {
  const b64 = (s + '='.repeat((4 - (s.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

const supported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const isIos = () => /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const installed = () => navigator.standalone === true
  || !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);

// made with the home PC's key now? One made with an older key never gets an alert again
function sameKey(sub, vapid) {
  try {
    const k = sub.options && sub.options.applicationServerKey;
    if (!k || !vapid) return true;                      // can't tell: keep it
    const a = new Uint8Array(k);
    const b = urlBase64ToUint8Array(vapid);
    return a.length === b.length && a.every((v, i) => v === b[i]);
  } catch {
    return true;
  }
}

// the promise and the older callback form both (Safari had only the callback)
function askPermission() {
  return new Promise((resolve) => {
    let done = false;
    const end = (p) => { if (!done) { done = true; resolve(p || Notification.permission); } };
    try {
      const r = Notification.requestPermission(end);
      if (r && typeof r.then === 'function') r.then(end, () => end(Notification.permission));
    } catch {
      end(Notification.permission);
    }
  });
}

const within = (p, ms) => Promise.race([p, new Promise((ok) => setTimeout(() => ok(null), ms))]);

function usePush(push, onCommand) {
  const [perm, setPerm] = useState(() => (supported() ? Notification.permission : 'unsupported'));
  const [sub, setSub] = useState(null);                 // this browser's PushSubscription
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState('');
  const [sentAt, setSentAt] = useState(0);              // a subscription went home: its count comes on the next panel
  const vapid = (push && push.vapid) || '';

  // how this browser stands - again whenever the desk comes back into view (alerts allowed in the settings meanwhile)
  useEffect(() => {
    if (!supported()) return undefined;
    let live = true;
    const look = () => {
      setPerm(Notification.permission);
      navigator.serviceWorker.getRegistration()
        .then((reg) => (reg ? reg.pushManager.getSubscription() : null))
        .then((s) => { if (live) setSub(s); })
        .catch(() => { if (live) setSub(null); });
    };
    look();
    document.addEventListener('visibilitychange', look);
    return () => { live = false; document.removeEventListener('visibilitychange', look); };
  }, []);

  const turnOn = useCallback(async () => {
    if (!vapid) return;
    setBusy(true);
    setSaid('');
    try {
      const p = await askPermission();                  // first, while the tap still counts (Safari wants that)
      setPerm(p);
      if (p !== 'granted') {
        setSaid(p === 'denied' ? BLOCKED : 'Alerts were not allowed - turn them on again and tap Allow.');
        return;
      }
      if (!(await navigator.serviceWorker.getRegistration())) await navigator.serviceWorker.register('/sw.js');
      const reg = await within(navigator.serviceWorker.ready, 15000);
      if (!reg) throw new Error("the desk's service worker didn't start - reload the page and try again");
      let s = await reg.pushManager.getSubscription();
      if (s && !sameKey(s, vapid)) { await s.unsubscribe(); s = null; }
      if (!s) s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(vapid) });
      setSub(s);
      if (await onCommand({ action: 'push_subscribe', data: { sub: s.toJSON() } })) setSentAt(Date.now());
    } catch (e) {
      setSaid('Alerts could not be turned on: ' + String((e && e.message) || e));
    } finally {
      setBusy(false);
    }
  }, [vapid, onCommand]);

  const turnOff = useCallback(async () => {
    if (!sub) return;
    setBusy(true);
    setSaid('');
    try {
      const { endpoint } = sub;
      await sub.unsubscribe();
      setSub(null);
      await onCommand({ action: 'push_unsubscribe', data: { endpoint } });
    } catch (e) {
      setSaid('Alerts could not be turned off: ' + String((e && e.message) || e));
    } finally {
      setBusy(false);
    }
  }, [sub, onCommand]);

  const test = useCallback(() => onCommand({ action: 'push_test' }), [onCommand]);

  const devices = push && typeof push.subs === 'number' ? push.subs : null;
  return {
    known: !!push,
    vapid,
    devices,
    error: (push && push.error) || '',
    iosHint: isIos() && !installed(),
    supported: supported(),
    blocked: perm === 'denied',
    on: perm === 'granted' && !!sub && sameKey(sub, vapid),
    waiting: Date.now() - sentAt < 60000,
    busy,
    said,
    turnOn,
    turnOff,
    test,
  };
}

function devicesText(n) {
  if (n === null) return '';
  return n === 0 ? 'No device gets them yet.' : `${n} device${n === 1 ? ' gets' : 's get'} them.`;
}

export default function PushToggle({ push, onCommand, compact }) {
  const p = usePush(push, onCommand);
  const notKnown = !p.known ? "The home PC hasn't said yet - it does once it runs the new code."
    : !p.vapid ? (p.error || 'The home PC has no alert key yet.') : '';
  // on here, but the home PC has nobody on its list (it never got this one, say): Turn on sends it again
  const orphan = p.on && p.devices === 0 && !p.waiting;
  const onButton = (cls) => (
    <button className={cls} disabled={p.busy || !p.vapid} onClick={p.turnOn} title={notKnown || undefined}>
      {p.busy ? <span className="spin" /> : 'Turn on phone alerts'}
    </button>
  );

  if (compact) {
    if (p.iosHint) return <button className="btn mini" onClick={() => window.alert(IOS_HINT)}>Phone alerts</button>;
    if (!p.supported || !p.vapid) return null;
    if (p.blocked) return <button className="btn mini" disabled title={BLOCKED}>Alerts blocked</button>;
    if (p.on && !orphan) {
      return (
        <button className="btn mini go" disabled={p.busy} onClick={p.test}
          title="Phone alerts are on for this device - tap to send a test">Alerts on</button>
      );
    }
    return (
      <>
        {onButton('btn mini')}
        {p.said && <span className="push-said">{p.said}</span>}
      </>
    );
  }

  const state = p.iosHint || !p.supported ? 'off' : p.blocked ? 'blocked by the browser' : p.on ? 'on' : 'off';
  let controls;
  if (p.iosHint) controls = <div className="settings-muted">{IOS_HINT}</div>;
  else if (!p.supported) controls = <div className="settings-muted">This browser can&rsquo;t show alerts from the desk.</div>;
  else if (p.blocked) controls = <div className="settings-muted">{BLOCKED}</div>;
  else if (!p.on) controls = onButton('btn go');
  else {
    controls = (
      <div className="push-btns">
        {orphan && onButton('btn go')}
        <button className="btn" disabled={p.busy} onClick={p.test}>Send a test</button>
        <button className="btn" disabled={p.busy} onClick={p.turnOff}>Turn off</button>
      </div>
    );
  }
  return (
    <div className="card settings-card">
      <div className="settings-head">
        <h3>Phone alerts</h3>
        <span className={'settings-dot' + (p.on ? ' on' : p.blocked ? ' paused' : '')}>{state}</span>
      </div>
      <div className="settings-row">
        <div className="settings-what">
          <div className="settings-label">This device</div>
          <div className="settings-muted">
            An alert on this phone or computer when an email needs you now, even with the desk closed.
            {' '}{devicesText(p.devices)}
          </div>
          {orphan && (
            <div className="settings-muted">
              This device is on, but the home PC has no device on its list - turn alerts on again to send it.
            </div>
          )}
        </div>
        {controls}
      </div>
      {(notKnown || (p.vapid && p.error)) && <div className="settings-said bad">{notKnown || p.error}</div>}
      {p.said && <div className="settings-said bad">{p.said}</div>}
    </div>
  );
}
