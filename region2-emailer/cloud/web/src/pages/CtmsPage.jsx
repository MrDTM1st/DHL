import { useState, useEffect, useRef } from 'react';
import { I } from '../icons.jsx';
import * as api from '../api.js';

// The CTMS page: CTMS as the work PC's bridge (work_pc/ctms_bridge.py) sees
// it, and "Look mum, no hands" - the switch that lets the haulage desk run it.
//
// It talks to its own channel (/api/ctms/*), not the home agent's queue. The
// haulage desk (Claude on the home PC, through ctms_remote.py) can always LOOK;
// it can only click, type and choose while Look mum, no hands mode is on - a
// switch that lives here, that only this page can turn on, and that turns
// itself off again. Anything that books, saves, submits or deletes still waits
// for his go-ahead in the chat.

const MODE = 'Look mum, no hands';

// What the work PC is doing, in words, while it does it.
const DOING = {
  look: 'taking a picture', net: 'switching recording', see: 'looking at the screen', click: 'clicking',
  type: 'typing', key: 'pressing a key', select: 'choosing an option', scroll: 'scrolling', hover: 'pointing',
  goto: 'opening a page', back: 'going back', forward: 'going forward', reload: 'reloading the page',
  dialog: 'answering a dialog box', wait: 'waiting for the page', tabs: 'listing tabs', tab: 'switching tab',
  update: 'updating its code from GitHub', steps: 'working through a run of steps', paste: 'pasting',
  drag: 'dragging', use: 'bringing a window up', fields: 'reading the fields', probe: 'checking the window',
};
const DURATIONS = [[15, '15 min'], [60, '1 hour'], [240, '4 hours']];
const leftText = (s) => (s >= 3600 ? Math.floor(s / 3600) + ' h ' + Math.floor((s % 3600) / 60) + ' min'
  : s >= 60 ? Math.ceil(s / 60) + ' min' : s + 's');
const clock = (s) => new Date(Date.now() + s * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// The work PC's bridge words its own messages, and its code only changes when
// it is updated, so some of them still name Claude and "Claude can act". Say
// them the way this page does.
const deskWords = (t) => String(t || '')
  .replace(/['"]Claude can act['"]/g, MODE + ' mode')
  .replace(/(^|[.!?:]\s+)Claude\b/g, '$1The haulage desk')
  .replace(/\bClaude\b/g, 'the haulage desk');

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

const agoText = (s) => (s == null ? '' : s < 2 ? 'just now' : s < 60 ? Math.round(s) + 's ago'
  : s < 3600 ? Math.floor(s / 60) + ' min ago' : Math.floor(s / 3600) + ' h ago');
const hostOf = (u) => { try { return new URL(u).host; } catch { return ''; } };

const CODE_ZIP = 'https://github.com/MrDTM1st/DHL/archive/refs/heads/main.zip';

// One file sets the work PC up. A web page cannot start programs on the PC
// by itself, so this is the one double-click; after it, the bridge starts at
// log-in (if ticked) and the Update button keeps it current.
function SetupPanel({ onDownload }) {
  const [allow, setAllow] = useState(true);
  const [auto, setAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onDownload(allow, auto); } finally { setBusy(false); }
  };
  return (
    <div className="ctms-setup">
      <div className="ctms-sub">
        One file sets the work PC up: it gets the code, connects it to this dashboard and starts the bridge.
        Nothing to type. Do this on the work PC.
      </div>
      <label className="ctms-check">
        <input type="checkbox" checked={allow} onChange={(e) => setAllow(e.target.checked)} />
        Let the haulage desk run CTMS when I turn on {MODE} mode
      </label>
      <label className="ctms-check">
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
        Start the bridge by itself when I log in
      </label>
      <button className="btn primary ctms-setupbtn" disabled={busy} onClick={go}>
        {busy ? <span className="spin" /> : 'Download the setup'}
      </button>
      <ol className="ctms-steps">
        <li>Open <b>CTMS bridge setup.cmd</b> from your downloads. If Windows says it protected your PC,
          choose <b>More info</b>, then <b>Run anyway</b>.</li>
        <li>It does the rest. Then open CTMS in your normal Edge as always - this page lights up by itself.</li>
      </ol>
      <div className="ctms-muted">
        If it says it can&rsquo;t get the code, <a href={CODE_ZIP} target="_blank" rel="noreferrer">download the
        code here</a> (it saves to Downloads) and run the setup again.
      </div>
      <details className="ctms-manual">
        <summary>Or set it up by hand</summary>
        <SetupSteps />
      </details>
    </div>
  );
}

function SetupSteps() {
  return (
    <ol className="ctms-steps">
      <li>On the work PC, open Command Prompt in the <span className="mono">region2-emailer\work_pc</span> folder.</li>
      <li>Run <span className="mono">python ctms_bridge.py</span> and leave that window open.</li>
      <li>The first time, it asks for the key you log into this dashboard with. It keeps only a key made
        from it, which opens the bridge&rsquo;s channel and nothing else. It also asks whether the haulage
        desk may run CTMS when you turn on {MODE} mode here.</li>
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
  const [actual, setActual] = useState(false);
  const [mins, setMins] = useState(60);
  const [ctlBusy, setCtlBusy] = useState(false);
  const [showSetup, setShowSetup] = useState(false);

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

  // A finished command answers here - toast it, so an update never just
  // silently happens (or silently doesn't).
  useEffect(() => {
    if (!st) return;
    const done = (st.results || []).filter((r) => pending[r.id]);
    if (!done.length) return;
    done.forEach((r) => {
      if (r.ok && r.action === 'look') return;
      const title = r.ok ? ({ update: 'Work PC updating' }[r.action] || 'Done') : 'CTMS bridge: not done';
      pushToast(title, deskWords(r.detail), r.ok ? 'go' : 'warn');
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
          + 's: it only runs if the bridge checks in by then, so nothing happens late.', 'warn');
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
      pushToast('Stopped', 'Anything queued is cancelled and ' + MODE + ' mode is off.', 'go');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
    }
  };

  const setControl = async (on) => {
    setCtlBusy(true);
    try {
      await api.ctmsControl(on, mins);
      pushToast(on ? MODE + ' mode is on' : MODE + ' mode is off',
        on ? 'The haulage desk can run CTMS for you until ' + clock(mins * 60) + '. Anything that books, saves, '
            + 'submits or deletes still waits for your go-ahead in the chat.'
          : 'The haulage desk is back to looking only. Anything it had queued is cancelled.', on ? 'warn' : 'go');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Not changed', String((e && e.message) || e), 'warn');
    }
    setCtlBusy(false);
  };

  const getSetup = async (allow, auto) => {
    try {
      await api.downloadCtmsSetup(allow, auto);
      pushToast('Setup downloaded', 'Open "CTMS bridge setup.cmd" from your downloads - on the work PC.', 'go');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Not downloaded', String((e && e.message) || e), 'warn');
    }
  };

  const update = () => {
    if (!window.confirm('Update the bridge on the work PC from GitHub (main)?\n\nIt tries the new code first, '
      + 'restarts on it, and puts the old code back by itself if it will not start.')) return;
    send({ action: 'update', branch: 'main' });
  };

  const s = (st && st.state) || {};
  const online = !!(st && st.online);
  const everSeen = !!(st && st.seen_ago != null);
  const attached = online && !!s.attached;
  const shotMeta = st && st.shot;
  const fresh = attached && !!shotMeta && shotMeta.ago < 6;
  const results = (st && st.results) || [];
  const queued = (st && st.queued) || [];
  const ctl = (st && st.control) || { armed: false, left: 0 };
  // an older bridge does not say - it refuses on its own side anyway
  const allowed = s.control !== false;
  const acting = !!ctl.armed && allowed;
  const updating = queued.some((q) => q.action === 'update') || (st && st.running && st.running.action === 'update');

  let tone = 'off';
  let head = 'Connecting…';
  let body = null;
  if (st && !everSeen) {
    head = 'Set up the work PC';
    body = <SetupPanel onDownload={getSetup} />;
  } else if (st && !online) {
    head = 'Work PC bridge offline';
    body = 'Last checked in ' + agoText(st.seen_ago) + '. '
      + (s.autostart ? 'It starts by itself when the work PC is on and you are logged in. '
        : 'Is it still running on the work PC? ')
      + 'To start it again, run the setup there (Setup file, below).';
  } else if (st && !attached) {
    tone = 'warn';
    head = 'Bridge online - CTMS not open';
    body = deskWords(s.error) || 'Open CTMS in your Edge as normal; the bridge finds its window by itself.';
  } else if (st && s.view === 'window') {
    // CTMS's own window in his normal Edge - it runs in IE mode, which no
    // automation browser can open, so this is the bridge's main way in
    const w = s.window || {};
    tone = w.minimized ? 'warn' : 'on';
    head = 'Connected to CTMS';
    body = (w.title || 'CTMS') + ' - your own Edge window'
      + (w.minimized ? '. It is minimised: restore it so it can be pictured (it can sit behind other windows).' : '.');
  } else if (st) {
    tone = 'on';
    head = 'Connected to CTMS';
    body = s.tab_title || hostOf(s.tab_url);
  }

  return (
    <div className="scroll"><div className="container page-anim">
      <div className="pagehead">
        <div>
          <div className="kicker">Work PC · CTMS</div>
          <h1 className="h1">CTMS bridge</h1>
          <p>Let the haulage desk run CTMS for you: turn on {MODE} mode and watch it work here, live from the work PC.</p>
        </div>
        <div className="ctms-headbtns">
          <span className={'ctms-mode' + (acting ? ' act' : '')}
            title={acting ? 'The haulage desk is running CTMS until ' + clock(ctl.left) + '. Anything that books, saves, submits or deletes waits for your go-ahead.'
              : 'The haulage desk can look at CTMS but not click, type or choose anything in it. Turn on ' + MODE + ' mode to let it run CTMS for you.'}>
            {acting ? MODE + ' · ' + leftText(ctl.left) : 'Look only'}
          </span>
          <button className="btn red" disabled={!everSeen} onClick={stop}
            title={'Cancel anything queued and turn ' + MODE + ' mode off'}>Stop</button>
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
              {shot ? <img src={'data:' + (shot.mime || 'image/jpeg') + ';base64,' + shot.data} alt="CTMS on the work PC" /> : (
                <div className="ctms-empty">
                  {I.ctms}
                  <div>{!st ? 'Connecting…' : !online ? 'Nothing to show until the work PC bridge is running.'
                    : attached ? 'The first picture is on its way…' : (deskWords(s.error) || 'No CTMS tab yet.')}</div>
                </div>
              )}
            </div>
            <div className="ctms-viewft">
              {shotMeta ? 'Picture from ' + agoText(shotMeta.ago) : ''}
              {attached && s.error ? <span className="ctms-err">{shotMeta ? ' · ' : ''}{deskWords(s.error)}</span> : null}
            </div>
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
                {[s.machine, s.browser, s.match ? 'tabs matching "' + s.match + '"' : '',
                  s.autostart ? 'starts when you log in' : ''].filter(Boolean).join(' · ')}
              </div>
            )}
            {online && s.dialog && <div className="ctms-warnbox">A dialog box is open in CTMS: {s.dialog}</div>}
            {online && st.running && (
              <div className="ctms-busy"><span className="spin" />
                {st.running.by === 'home PC' ? 'The haulage desk is ' : 'Work PC is '}
                {st.running.action === 'capture' ? 'capturing "' + st.running.name + '"' : DOING[st.running.action] || st.running.action}…
              </div>
            )}
            {everSeen && (
              <div className="ctms-code">
                <span className="ctms-muted">
                  Bridge code: <span className="mono">{s.code || (s.version ? 'v' + s.version : '?')}</span>
                  {s.code_at ? ' · since ' + s.code_at.replace('T', ' ').slice(0, 16) : ''}
                </span>
                <span className="ctms-codebtns">
                  <button className="btn mini" disabled={!online || updating} onClick={update}
                    title="The work PC fetches the bridge's code from GitHub (main), tries it, and restarts on it">
                    {updating ? <span className="spin" /> : 'Update'}
                  </button>
                  <button className="btn mini" onClick={() => setShowSetup((v) => !v)}
                    title="The one-file setup for the work PC - to set it up again, start it, or change your choices">
                    Setup file
                  </button>
                </span>
              </div>
            )}
            {everSeen && showSetup && <SetupPanel onDownload={getSetup} />}
            {s.rolled_back && <div className="ctms-warnbox">Rolled back: {deskWords(s.rolled_back)}</div>}
          </div>

          <div className={'card statuscard ctms-control' + (acting ? ' on' : '')}>
            <div className="statushd">
              <span className="lbl">{MODE}</span>
              <button className={'switch' + (acting ? ' on' : '')} style={{ marginLeft: 'auto' }}
                role="switch" aria-checked={acting} aria-label={MODE + ' mode'} disabled={!online || !allowed || ctlBusy}
                onClick={() => setControl(!ctl.armed)}>
                <span className="knob" />
                <span className="swlabel">{acting ? leftText(ctl.left) + ' left' : 'Turn on'}</span>
              </button>
            </div>
            <div className="ctms-sub">
              {acting
                ? <>The haulage desk is running CTMS for you until {clock(ctl.left)}, doing what you ask in the chat.
                    Anything that books, saves, submits or deletes waits for your go-ahead. It never touches the sign-in page.</>
                : <>Let the haulage desk run CTMS for you: turn this on and it clicks, types and chooses while you
                    watch, then switches itself off again. Until then it can only look.</>}
            </div>
            {!allowed && online && (
              <div className="ctms-warnbox">This work PC is set to look only. To let the haulage desk run CTMS, run{' '}
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
            <div className="statushd"><span className="lbl">Activity</span></div>
            {queued.map((q) => (
              <div className="ctms-act" key={'q' + q.id}>
                <span className="ctms-actdot wait" />
                <span className="t mono">{q.age}s</span>
                <span className="d">{q.by === 'home PC' && <span className="ctms-by">Haulage desk</span>}
                  {q.action}{q.name ? ' "' + q.name + '"' : ''}: waiting for the work PC</span>
              </div>
            ))}
            {results.slice(0, 10).map((r) => (
              <div className="ctms-act" key={r.id + '-' + r.at}>
                <span className={'ctms-actdot ' + (r.ok ? 'ok' : 'bad')} />
                <span className="t mono">{r.at}</span>
                <span className="d">{r.by === 'home PC' && <span className="ctms-by">Haulage desk</span>}{deskWords(r.detail)}</span>
              </div>
            ))}
            {!queued.length && !results.length && <div className="ctms-muted">Nothing yet.</div>}
          </div>
        </div>
      </div>
    </div></div>
  );
}
