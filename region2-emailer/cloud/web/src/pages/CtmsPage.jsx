import { useState, useEffect, useRef } from 'react';
import { I } from '../icons.jsx';
import * as api from '../api.js';

// The CTMS page: what the work PC's bridge (work_pc/ctms_bridge.py) can see,
// and the switch that lets Claude act in it.
//
// It talks to its own channel (/api/ctms/*), not the home agent's queue. Claude
// (on the home PC, through ctms_remote.py) can always LOOK; it can only click,
// type and choose while "Claude can act" is on - a switch that lives here, that
// only this page can turn on, and that turns itself off again. Anything that
// books, saves, submits or deletes still waits for his go-ahead in the chat.

// What the work PC is doing, in words, while it does it.
const DOING = {
  look: 'taking a picture', net: 'switching recording', see: 'looking at the screen', click: 'clicking',
  type: 'typing', key: 'pressing a key', select: 'choosing an option', scroll: 'scrolling', hover: 'pointing',
  goto: 'opening a page', back: 'going back', forward: 'going forward', reload: 'reloading the page',
  dialog: 'answering a dialog box', wait: 'waiting for the page', tabs: 'listing tabs', tab: 'switching tab',
  update: 'updating its code from GitHub',
};
const DURATIONS = [[15, '15 min'], [60, '1 hour'], [240, '4 hours']];
const leftText = (s) => (s >= 3600 ? Math.floor(s / 3600) + ' h ' + Math.floor((s % 3600) / 60) + ' min'
  : s >= 60 ? Math.ceil(s / 60) + ' min' : s + 's');
const clock = (s) => new Date(Date.now() + s * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// True while this tab is on screen. Only then does the page ask for pictures
// (watch=1), so a dashboard left open in a background tab is not streaming
// CTMS screenshots up through the cloud all day.
function usePageVisible() {
  const [v, setV] = useState(document.visibilityState !== 'hidden');
  useEffect(() => {
    const f = () => setV(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', f);
    return () => document.removeEventListener('visibilitychange', f);
  }, []);
  return v;
}

// "20261028-074825_order-search.zip" -> "order-search" (the bridge's file name)
const capLabel = (name) => String(name || '').replace(/^\d{8}-\d{6}_/, '').replace(/\.zip$/i, '');
// the same cleaning the bridge applies to a screen name before filing it
const safeName = (s) => String(s || '').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 40);

const agoText = (s) => (s == null ? '' : s < 2 ? 'just now' : s < 60 ? Math.round(s) + 's ago'
  : s < 3600 ? Math.floor(s / 60) + ' min ago' : Math.floor(s / 3600) + ' h ago');
const sizeText = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB');
const hostOf = (u) => { try { return new URL(u).host; } catch { return ''; } };
const pathOf = (u) => { try { const x = new URL(u); return x.pathname + x.search; } catch { return u; } };
const shortMime = (m) => String(m || '').replace(/^application\//, '').replace(/^text\//, '');

// The one fact the network recording is for - does CTMS post bookings to an
// API (drive that: stable) or submit a form (drive the screen: brittle)?
function apiVerdict(tail) {
  const sent = tail.filter((e) => ['POST', 'PUT', 'PATCH'].includes(e.method));
  if (sent.some((e) => /json/i.test(e.mime))) {
    return ['go', 'CTMS sent data and got JSON back: there is an API behind the screen. That is the easier, sturdier thing to automate.'];
  }
  if (sent.some((e) => e.type === 'Document')) {
    return ['warn', 'CTMS posted a form and got a whole page back: a classic form submit. Workable, but the automation would drive the screen itself.'];
  }
  if (sent.length) return ['', 'CTMS has sent data. Capture the screen straight after to keep exactly what went.'];
  return ['', 'Nothing sent yet. With this on, run a search or open a booking in CTMS and watch what appears.'];
}

function SetupSteps() {
  return (
    <ol className="ctms-steps">
      <li>On the work PC, open Command Prompt in the <span className="mono">region2-emailer\work_pc</span> folder.</li>
      <li>Run <span className="mono">python ctms_bridge.py</span> and leave that window open.</li>
      <li>The first time, it asks for the key you log into this dashboard with. It keeps only a key made
        from it, which opens the bridge&rsquo;s channel and nothing else. It also asks whether Claude may act
        in CTMS when you switch that on here.</li>
      <li>Log into CTMS in the browser window it opens. This page lights up on its own.</li>
    </ol>
  );
}

export default function CtmsPage({ onAuthFail, pushToast }) {
  const visible = usePageVisible();
  const [st, setSt] = useState(null);
  const [shot, setShot] = useState(null);
  const shotId = useRef(null);
  const [pending, setPending] = useState({});   // command id -> what was asked
  const [other, setOther] = useState('');
  const [actual, setActual] = useState(false);
  const [dl, setDl] = useState('');
  const [mins, setMins] = useState(60);
  const [ctlBusy, setCtlBusy] = useState(false);

  // Chained timeouts rather than setInterval: fetching a picture can take
  // longer than the gap, and overlapping polls would pile up on a phone.
  useEffect(() => {
    let live = true;
    let timer = null;
    const tick = async () => {
      try {
        const s = await api.ctmsStatus(visible);
        if (!live) return;
        setSt(s);
        if (s.shot && s.shot.id !== shotId.current) {
          const sh = await api.ctmsShot();
          if (live && sh && sh.id) { shotId.current = sh.id; setShot(sh); }
        }
      } catch (e) {
        if (e instanceof api.AuthError) { onAuthFail(); return; }
      }
      if (live) timer = setTimeout(tick, visible ? 1200 : 6000);
    };
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [visible, onAuthFail]);

  // A finished command answers here - toast it, so a capture never just
  // silently appears (or silently doesn't).
  useEffect(() => {
    if (!st) return;
    const done = (st.results || []).filter((r) => pending[r.id]);
    if (!done.length) return;
    done.forEach((r) => {
      if (r.ok && r.action === 'look') return;
      const title = r.ok ? ({ capture: 'Screen captured', net: 'Recording switched', update: 'Work PC updating' }[r.action] || 'Done')
        : 'CTMS bridge: not done';
      pushToast(title, r.detail, r.ok ? 'go' : 'warn');
    });
    setPending((p) => { const n = { ...p }; done.forEach((r) => { delete n[r.id]; }); return n; });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st]);

  const send = async (body) => {
    try {
      const r = await api.ctmsCommand(body);
      setPending((p) => ({ ...p, [r.id]: body }));
      if (!r.online) {
        pushToast('Work PC bridge offline', 'Held for ' + ((st && st.ttl) || 60)
          + 's: it only runs if the bridge checks in by then, so nothing is captured late under the wrong name.', 'warn');
      }
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Not sent', String((e && e.message) || e), 'warn');
    }
  };

  const stop = async () => {
    try {
      await api.ctmsStop();
      setPending({});
      pushToast('Stopped', 'Anything queued is cancelled, recording is off and Claude can no longer act.', 'go');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
    }
  };

  const setControl = async (on) => {
    setCtlBusy(true);
    try {
      await api.ctmsControl(on, mins);
      pushToast(on ? 'Claude can act in CTMS' : 'Claude is back to looking only',
        on ? 'Until ' + clock(mins * 60) + '. Anything that books, saves, submits or deletes still waits for your go-ahead in the chat.'
          : 'Anything it had queued is cancelled.', on ? 'warn' : 'go');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Not changed', String((e && e.message) || e), 'warn');
    }
    setCtlBusy(false);
  };

  const update = () => {
    if (!window.confirm('Update the bridge on the work PC from GitHub (main)?\n\nIt tries the new code first, '
      + 'restarts on it, and puts the old code back by itself if it will not start.')) return;
    send({ action: 'update', branch: 'main' });
  };

  const grab = async (name) => {
    setDl(name);
    try { await api.downloadCtmsCapture(name); } catch {
      pushToast('Download failed', name + ' is no longer on the cloud - it restarted, or it was one of the oldest. '
        + 'The home PC and the work PC both keep a copy in work_pc\\ctms_capture.', 'warn');
    }
    setDl('');
  };

  const s = (st && st.state) || {};
  const online = !!(st && st.online);
  const everSeen = !!(st && st.seen_ago != null);
  const attached = online && !!s.attached;
  const shotMeta = st && st.shot;
  const fresh = attached && !!shotMeta && shotMeta.ago < 6;
  const captures = (st && st.captures) || [];
  const results = (st && st.results) || [];
  const queued = (st && st.queued) || [];
  const screens = s.screens || [];
  const tail = s.net_tail || [];
  const have = new Set(captures.map((c) => capLabel(c.name)));
  const asked = new Set(Object.values(pending).filter((c) => c.action === 'capture').map((c) => safeName(c.name)));
  const doneCount = screens.filter(([label]) => have.has(label)).length;
  const [vTone, vText] = apiVerdict(tail);
  const ctl = (st && st.control) || { armed: false, left: 0 };
  // an older bridge does not say - it refuses on its own side anyway
  const allowed = s.control !== false;
  const acting = !!ctl.armed && allowed;
  const updating = queued.some((q) => q.action === 'update') || (st && st.running && st.running.action === 'update');

  let tone = 'off';
  let head = 'Connecting…';
  let body = null;
  if (st && !everSeen) {
    head = 'The work PC bridge is not running yet';
    body = <SetupSteps />;
  } else if (st && !online) {
    head = 'Work PC bridge offline';
    body = 'Last checked in ' + agoText(st.seen_ago) + '. Is ctms_bridge.py still running on the work PC?';
  } else if (st && !attached) {
    tone = 'warn';
    head = 'Bridge online, no CTMS tab';
    body = s.error || 'Open CTMS in the automation browser and log in.';
  } else if (st) {
    tone = 'on';
    head = 'Connected to CTMS';
    body = s.tab_title || hostOf(s.tab_url);
  }

  const capture = (name) => { if (name.trim()) send({ action: 'capture', name: name.trim() }); };

  return (
    <div className="scroll"><div className="container page-anim">
      <div className="pagehead">
        <div>
          <div className="kicker">Work PC · CTMS</div>
          <h1 className="h1">CTMS bridge</h1>
          <p>CTMS as it is on the work PC: watch it here, let Claude work it with you, and capture the screens the booking automation is built from.</p>
        </div>
        <div className="ctms-headbtns">
          <span className={'ctms-mode' + (acting ? ' act' : '')}
            title={acting ? 'Claude can click, type and choose in CTMS until ' + clock(ctl.left) + '. Anything that books, saves, submits or deletes waits for your go-ahead.'
              : 'Claude can look at CTMS, but not click, type or choose anything in it. Switch "Claude can act" on to let it.'}>
            {acting ? 'Claude can act · ' + leftText(ctl.left) : 'Look only'}
          </span>
          <button className="btn red" disabled={!everSeen} onClick={stop}
            title="Cancel anything queued, stop recording, and switch 'Claude can act' off">Stop</button>
        </div>
      </div>

      <div className="ctmsgrid">
        <div className="ctms-col">
          <div className="card ctms-view">
            <div className="ctms-viewhd">
              <span className={'livepill ' + (fresh ? 'on' : online ? 'wait' : 'off')}>
                <span className="ldot" />{fresh ? 'Live' : !online ? 'Offline' : attached ? 'Waiting' : 'No CTMS tab'}
              </span>
              <span className="ctms-tab">{(shot && shot.title) || s.tab_title || 'CTMS'}</span>
              <span className="ctms-host mono">{hostOf((shot && shot.url) || s.tab_url)}</span>
              <button className="btn mini" disabled={!attached} onClick={() => send({ action: 'look' })}>Refresh</button>
              <button className="btn mini" disabled={!shot} onClick={() => setActual((v) => !v)}>{actual ? 'Fit' : 'Actual size'}</button>
            </div>
            <div className={'ctms-screen' + (actual ? ' actual' : '') + (shot && !fresh ? ' stale' : '')}>
              {shot ? <img src={'data:image/jpeg;base64,' + shot.data} alt="The CTMS tab on the work PC" /> : (
                <div className="ctms-empty">
                  {I.ctms}
                  <div>{!st ? 'Connecting…' : !online ? 'Nothing to show until the work PC bridge is running.'
                    : attached ? 'The first picture is on its way…' : (s.error || 'No CTMS tab yet.')}</div>
                </div>
              )}
            </div>
            <div className="ctms-viewft">
              {shotMeta ? 'Picture from ' + agoText(shotMeta.ago) : ''}
              {attached && s.error ? <span className="ctms-err">{shotMeta ? ' · ' : ''}{s.error}</span> : null}
            </div>
          </div>

          <div className="card statuscard">
            <div className="statushd">
              <span className="lbl">What CTMS sends</span>
              <button className={'switch' + (s.net ? ' on' : '')} style={{ marginLeft: 'auto' }}
                role="switch" aria-checked={!!s.net} disabled={!attached}
                onClick={() => send({ action: 'net', on: !s.net })}>
                <span className="knob" />
                <span className="swlabel">{s.net ? 'Recording' : 'Not recording'}</span>
              </button>
            </div>
            <div className="ctms-sub">
              Records the requests the CTMS tab makes, into every capture while it is on. It answers the one
              question that decides how bookings get automated: does CTMS post to an API, or submit a form?
              Sign-in requests and passwords are never recorded.
            </div>
            {s.net && <div className={'ctms-verdict ' + vTone}>{vText}</div>}
            {s.net && tail.length > 0 && (
              <div className="ctms-net">
                {tail.slice().reverse().map((e, i) => (
                  <div className="ctms-netrow" key={i}>
                    <span className="m">{e.method}</span>
                    <span className="u mono" title={e.url}>{pathOf(e.url)}</span>
                    <span className="st mono">{e.status}</span>
                    <span className="mi">{shortMime(e.mime)}</span>
                  </div>
                ))}
              </div>
            )}
            {s.net && <div className="ctms-muted">{s.net_count || 0} request(s) since recording started · {s.net_count && !tail.length ? 'none of them page or data calls yet' : 'newest first'}</div>}
          </div>
        </div>

        <div className="ctms-col">
          <div className="card statuscard">
            <div className="statushd">
              <span className={'sdot ctms-dot ' + tone} />
              <b className="ctms-head">{head}</b>
              {everSeen && <span className="stime mono">{online ? 'checked in ' + agoText(st.seen_ago) : ''}</span>}
            </div>
            <div className="statusdetail">{body}</div>
            {everSeen && (s.machine || s.browser) && (
              <div className="ctms-muted" style={{ marginTop: 8 }}>
                {[s.machine, s.browser, s.match ? 'tabs matching "' + s.match + '"' : ''].filter(Boolean).join(' · ')}
              </div>
            )}
            {online && s.dialog && <div className="ctms-warnbox">A dialog box is open in CTMS: {s.dialog}</div>}
            {online && st.running && (
              <div className="ctms-busy"><span className="spin" />
                {st.running.by === 'home PC' ? 'Claude is ' : 'Work PC is '}
                {st.running.action === 'capture' ? 'capturing "' + st.running.name + '"' : DOING[st.running.action] || st.running.action}…
              </div>
            )}
            {everSeen && (
              <div className="ctms-code">
                <span className="ctms-muted">
                  Bridge code: <span className="mono">{s.code || (s.version ? 'v' + s.version : '?')}</span>
                  {s.code_at ? ' · since ' + s.code_at.replace('T', ' ').slice(0, 16) : ''}
                </span>
                <button className="btn mini" disabled={!online || updating} onClick={update}
                  title="The work PC fetches the bridge's code from GitHub (main), tries it, and restarts on it">
                  {updating ? <span className="spin" /> : 'Update'}
                </button>
              </div>
            )}
            {s.rolled_back && <div className="ctms-warnbox">Rolled back: {s.rolled_back}</div>}
          </div>

          <div className={'card statuscard ctms-control' + (acting ? ' on' : '')}>
            <div className="statushd">
              <span className="lbl">Claude can act</span>
              <button className={'switch' + (acting ? ' on' : '')} style={{ marginLeft: 'auto' }}
                role="switch" aria-checked={acting} disabled={!online || !allowed || ctlBusy}
                onClick={() => setControl(!ctl.armed)}>
                <span className="knob" />
                <span className="swlabel">{acting ? leftText(ctl.left) + ' left' : 'Off'}</span>
              </button>
            </div>
            <div className="ctms-sub">
              {acting
                ? <>Claude can click, type and choose in CTMS until {clock(ctl.left)}, doing what you ask in the chat.
                    Anything that books, saves, submits or deletes waits for your go-ahead. It never touches the sign-in page.</>
                : <>Off: Claude can look at CTMS but not click, type or choose anything in it. Switch it on while you
                    talk it through a job; it switches itself off again.</>}
            </div>
            {!allowed && online && (
              <div className="ctms-warnbox">This work PC is set to observe only. To allow acting, run{' '}
                <span className="mono">python ctms_bridge.py --allow-control</span> there.</div>
            )}
            {!acting && allowed && (
              <div className="ctms-durs">
                <span className="ctms-muted">For</span>
                {DURATIONS.map(([m, label]) => (
                  <button key={m} className={'chip' + (mins === m ? ' active' : '')} onClick={() => setMins(m)}>{label}</button>
                ))}
              </div>
            )}
          </div>

          <div className="card statuscard">
            <div className="statushd">
              <span className="lbl">Walkthrough</span>
              {screens.length > 0 && <span className="stime">{doneCount}/{screens.length} captured</span>}
            </div>
            <div className="ctms-sub">
              Bring each screen up in CTMS on the work PC, then capture it here. Every field and dropdown,
              the page itself and a picture go to the home PC, where the booking automation gets written from them.
            </div>
            {!screens.length && <div className="ctms-muted">The list appears once the bridge has checked in.</div>}
            {screens.map(([label, hint]) => {
              const got = have.has(label);
              const waiting = asked.has(label);
              const key = /most important/i.test(hint);
              return (
                <div className={'ctms-shotrow' + (got ? ' got' : '') + (key ? ' key' : '')} key={label}>
                  <span className="ctms-tick">{got ? I.check : null}</span>
                  <div className="ctms-shotinfo">
                    <div className="ctms-shotname mono">{label}{key && <span className="lbadge">MOST IMPORTANT</span>}</div>
                    <div className="ctms-shothint">{hint.replace(/\*+[^*]*\*+/g, '').trim()}</div>
                  </div>
                  <button className={'btn mini' + (got ? '' : ' primary')} disabled={!attached || waiting}
                    onClick={() => capture(label)}>
                    {waiting ? <span className="spin" /> : got ? 'Again' : <>{I.camera} Capture</>}
                  </button>
                </div>
              );
            })}
            <div className="ctms-other">
              <input placeholder="Any other screen - give it a name" value={other}
                onChange={(e) => setOther(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && attached) { capture(other); setOther(''); } }} />
              <button className="btn mini" disabled={!attached || !other.trim()}
                onClick={() => { capture(other); setOther(''); }}>Capture</button>
            </div>
          </div>

          <div className="card statuscard">
            <div className="statushd" style={{ marginBottom: 8 }}>
              <span className="sdot" style={{ background: 'var(--yellow)' }} />
              <b>Captures</b>
              <span className="ctms-muted" style={{ marginLeft: 6 }}>· collected by the home PC</span>
            </div>
            {captures.length ? captures.map((c) => (
              <div className="filerow" key={c.name}>
                <div className="fn mono">{c.name}</div>
                <div className="fm">{sizeText(c.size)} · {c.at}</div>
                <button className="btn mini" disabled={dl === c.name} onClick={() => grab(c.name)}>
                  {dl === c.name ? '…' : 'Download'}
                </button>
              </div>
            )) : <div className="ctms-muted">None yet.</div>}
          </div>

          <div className="card statuscard">
            <div className="statushd"><span className="lbl">Activity</span></div>
            {queued.map((q) => (
              <div className="ctms-act" key={'q' + q.id}>
                <span className="ctms-actdot wait" />
                <span className="t mono">{q.age}s</span>
                <span className="d">{q.by === 'home PC' && <span className="ctms-by">Claude</span>}
                  {q.action}{q.name ? ' "' + q.name + '"' : ''}: waiting for the work PC</span>
              </div>
            ))}
            {results.slice(0, 10).map((r) => (
              <div className="ctms-act" key={r.id + '-' + r.at}>
                <span className={'ctms-actdot ' + (r.ok ? 'ok' : 'bad')} />
                <span className="t mono">{r.at}</span>
                <span className="d">{r.by === 'home PC' && <span className="ctms-by">Claude</span>}{r.detail}</span>
              </div>
            ))}
            {!queued.length && !results.length && <div className="ctms-muted">Nothing yet.</div>}
          </div>
        </div>
      </div>
    </div></div>
  );
}
