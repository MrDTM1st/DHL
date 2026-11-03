import { useState, useRef, useEffect } from 'react';
import { I } from '../icons.jsx';
import { isUrgent, isReady, ordLabel, within3, dateShort } from '../lib/orders.js';
import { fileToB64, getFiles, downloadFile, ctmsRail, ctmsStatus, mailPending, mailApprove, mailControl } from '../api.js';
import FlowPanels from '../components/FlowPanels.jsx';
import BookingsCard from '../components/BookingsCard.jsx';

// ---- Holiday cover / handover card ----
function HolidayCard({ panel, onCommand }) {
  const h = (panel && panel.handover) || {};
  const team = (panel && panel.team) || [];
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(5);
  const [cover, setCover] = useState('');
  const [notes, setNotes] = useState('');
  const [forward, setForward] = useState(true);
  const active = !!h.active;

  const start = () => {
    if (!cover) { window.alert('Who is covering? Pick a team member.'); return; }
    if (!window.confirm('Start handover: ' + cover + ' covers for ' + days + ' day(s)?\n\nThis sends them the outstanding-work email now.')) return;
    setOpen(false);
    onCommand({ action: 'handover_start', data: { days, cover, notes, forward } });
  };
  const stop = () => {
    if (!window.confirm('End the handover now and stop forwarding?')) return;
    onCommand({ action: 'handover_stop', data: {} });
  };

  return (
    <div className="card statuscard">
      <div className="statushd"><span className="lbl">Holiday cover</span></div>
      {active ? (
        <>
          <div className="statusdetail" style={{ fontSize: 13 }}>
            Handover active — {h.cover_name || h.cover_email || '?'} covers until {h.end || '?'}
            {h.forward ? ' · replies auto-forward' : ' · no forwarding'}.
          </div>
          <button className="btn block" style={{ marginTop: 12 }} onClick={stop}>End handover now</button>
        </>
      ) : !open ? (
        <>
          <div className="statusdetail" style={{ fontSize: 13 }}>
            No handover active. Going away? Hand your outstanding work to a colleague and auto-forward replies.
          </div>
          <button className="btn block" style={{ marginTop: 12 }} onClick={() => setOpen(true)}>{I.plane} Set up handover</button>
        </>
      ) : (
        <div className="formcol" style={{ marginTop: 4 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="number" min={1} max={60} value={days} onChange={(e) => setDays(parseInt(e.target.value, 10) || 5)} style={{ width: 90 }} title="Days away" />
            <select value={cover} onChange={(e) => setCover(e.target.value)} style={{ flex: 1 }}>
              <option value="">Covering team member…</option>
              {team.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
          </div>
          <textarea rows={2} placeholder="Notes for whoever covers (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <label className="hint" style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>
            <input type="checkbox" checked={forward} onChange={(e) => setForward(e.target.checked)} style={{ width: 'auto' }} />
            auto-forward incoming replies while away
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn go" onClick={start}>Start handover</button>
            <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---- Work mail: Claude's drafts waiting for his OK ----
// Claude (outlook_remote.py send) can only DRAFT in the DHL mailbox; a send
// lands here and goes out from Outlook on the home PC only when he presses
// Send. Polls itself; shows nothing unless something is waiting or was just
// decided. The switch turns Claude's mail access off altogether.
function MailApprovals({ hint }) {
  const [st, setSt] = useState(null);
  const [open, setOpen] = useState({});
  const [busy, setBusy] = useState(0);
  const load = () => mailPending().then(setSt).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, hint ? 4000 : 10000);
    return () => clearInterval(t);
  }, [hint]);
  if (!st) return null;
  const list = (st.pending || []).filter((p) => p.state === 'waiting' || p.state === 'sending'
    || p.state === 'sent' || p.state === 'failed').slice(-6).reverse();
  if (!list.length && st.on) return null;
  const decide = async (p, ok) => {
    if (ok && !window.confirm('Send this from your DHL mailbox now?\n\nTo: ' + p.to + '\nSubject: ' + p.subject)) return;
    setBusy(p.id);
    try { await mailApprove(p.id, ok); } catch { /* the next poll shows it */ }
    setBusy(0); load();
  };
  const toggle = async () => {
    if (st.on && !window.confirm('Switch off Claude\'s access to your work mail? Anything it has queued is dropped.')) return;
    try { await mailControl(!st.on); } catch { /* */ }
    load();
  };
  const col = { waiting: 'var(--red)', sending: 'var(--yellow-d)', sent: 'var(--go)', failed: 'var(--red)' };
  return (
    <div className="card statuscard" style={{ marginBottom: 14 }}>
      <div className="statushd" style={{ justifyContent: 'space-between' }}>
        <span className="lbl">Work mail · Claude&rsquo;s sends</span>
        <button className="btn" style={{ padding: '3px 10px', fontSize: 12 }} onClick={toggle}>
          {st.on ? 'Switch off' : 'Off · switch on'}
        </button>
      </div>
      {!st.home_pc && <div className="statusdetail" style={{ fontSize: 12, color: 'var(--muted)' }}>The home PC is not answering for mail right now.</div>}
      {list.map((p) => (
        <div key={p.id} style={{ borderTop: '1px solid var(--line, #e6e6e6)', padding: '10px 0' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <b style={{ color: col[p.state], fontSize: 12, textTransform: 'uppercase' }}>{p.state}</b>
            <span style={{ fontSize: 13, fontWeight: 600, overflowWrap: 'anywhere' }}>{p.subject || '(no subject)'}</span>
            <span style={{ fontSize: 12, color: 'var(--faint)' }}>{p.at}</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)', overflowWrap: 'anywhere' }}>
            To {p.to}{p.cc ? ' · Cc ' + p.cc : ''}{p.bcc ? ' · Bcc ' + p.bcc : ''}
            {p.attachments && p.attachments.length ? ' · ' + p.attachments.length + ' attachment(s)' : ''}
          </div>
          {p.why && <div style={{ fontSize: 12, marginTop: 3 }}>Claude: {p.why}</div>}
          {p.said && <div style={{ fontSize: 12, marginTop: 3 }}>{p.said}</div>}
          {p.state === 'waiting' && (
            <>
              <button className="btn" style={{ marginTop: 6, padding: '2px 8px', fontSize: 12 }}
                onClick={() => setOpen((o) => ({ ...o, [p.id]: !o[p.id] }))}>{open[p.id] ? 'Hide email' : 'Read email'}</button>
              {open[p.id] && (
                <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, maxHeight: 320, overflow: 'auto', background: 'var(--bg2, #f6f6f6)', padding: 10, borderRadius: 8, marginTop: 6 }}>{p.body}</pre>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button className="btn go" disabled={busy === p.id} onClick={() => decide(p, true)}>Send</button>
                <button className="btn" disabled={busy === p.id} onClick={() => decide(p, false)}>Don&rsquo;t send</button>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- Order upload card (file -> /api/upload -> order_upload command) ----
function UploadCard({ onUpload, busy }) {
  const fileRef = useRef(null);
  const [name, setName] = useState('');
  const [drag, setDrag] = useState(false);
  const pick = (file) => { if (file) { setName(file.name); onUpload(file); } };
  return (
    <div className="cmd"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
      <div className="top"><div className="ci">{I.up}</div><h3>Order upload</h3></div>
      <div className="desc">Drop a Synergy extract (.xlsx) to map deliveries and build the CSV.</div>
      <input ref={fileRef} type="file" accept=".xlsx,.xls" style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])} />
      <div className={'dropzone' + (drag ? ' drag' : '')} style={{ margin: '6px 0 0' }} onClick={() => fileRef.current && fileRef.current.click()}>
        <div className="di">{I.file}</div>
        <div className="d1">{busy ? 'Uploading…' : name ? name : 'Drop .xlsx here, or click'}</div>
        <div className="d2">Synergy Region 2 extract</div>
      </div>
    </div>
  );
}

// ---- Seasonal treatments card ----
// The autumn railhead-treatment and winter programmes. One Seasonal Treatment
// Order per file, and one file per drop - /api/upload is a single slot, so
// there is nowhere to put a second. Dropping them one after another is safe:
// seasonal.py MERGES its cover requests into the pending list rather than
// replacing it, so order 2 does not wipe out order 1's email.
function SeasonalCard({ onUpload, busy }) {
  const fileRef = useRef(null);
  const [name, setName] = useState('');
  const [drag, setDrag] = useState(false);
  const pick = (file) => { if (file) { setName(file.name); onUpload(file); } };
  return (
    <div className="cmd"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
      <div className="top"><div className="ci">{I.up}</div><h3>Seasonal treatments</h3></div>
      <div className="desc">Drop a Seasonal Treatment Order (.xlsx) to build the upload CSV and stage a cover request to that site&rsquo;s allocated haulier.</div>
      <input ref={fileRef} type="file" accept=".xlsx,.xlsm" style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])} />
      <div className={'dropzone' + (drag ? ' drag' : '')} style={{ margin: '6px 0 0' }} onClick={() => fileRef.current && fileRef.current.click()}>
        <div className="di">{I.file}</div>
        <div className="d1">{busy ? 'Uploading…' : name ? name : 'Drop .xlsx here, or click'}</div>
        <div className="d2">Seasonal Treatment Order</div>
      </div>
    </div>
  );
}

// ---- Media sets card ----
// Same shape as the Synergy upload, different form: a weekly courier sheet in,
// the NR upload CSV out. The `if (await onUpload(file))` guard at the mount
// site is what stops the agent pulling an empty or stale upload slot.
function MediaSetsCard({ onUpload, busy }) {
  const fileRef = useRef(null);
  const [name, setName] = useState('');
  const [drag, setDrag] = useState(false);
  const pick = (file) => { if (file) { setName(file.name); onUpload(file); } };
  return (
    <div className="cmd"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
      <div className="top"><div className="ci">{I.up}</div><h3>Media sets</h3></div>
      <div className="desc">Drop the weekly courier sheet (.xlsx) to build the media sets upload CSV.</div>
      <input ref={fileRef} type="file" accept=".xlsx,.xlsm" style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])} />
      <div className={'dropzone' + (drag ? ' drag' : '')} style={{ margin: '6px 0 0' }} onClick={() => fileRef.current && fileRef.current.click()}>
        <div className="di">{I.file}</div>
        <div className="d1">{busy ? 'Uploading…' : name ? name : 'Drop .xlsx here, or click'}</div>
        <div className="d2">Week NN Courier sheet</div>
      </div>
    </div>
  );
}

// ---- My week: what he is on besides Region 2, off the team's Transport Planners sheet (planner_week.py) ----
// His ask (01/11): "tell me the things that I will be doing throughout the week ... DHL road ... stone blowers or
// media sets, or whether I'm doing a rail plan ... I know I forget pretty often". Region 2 and Serviceable Materials
// are every day, so they are never listed. The days from today on, this week's sheet then next week's.
const sheetDay = (s) => {
  const [d, m, y] = String(s || '').split('/').map(Number);
  return y ? new Date(y, m - 1, d) : null;
};

function MyWeek({ week }) {
  const weeks = (week && week.weeks) || [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = weeks.flatMap((w) => (w.days || []).map((d) => ({ ...d, at: sheetDay(d.date), wk: w })))
    .filter((d) => d.at && d.at >= today).slice(0, 7);
  const from = [...new Set(days.map((d) => d.wk))]          // only the sheets the days shown come from
    .map((w) => `${(w.file || 'wc ' + w.wc).replace(/\.xlsx$/i, '')}`
      + (w.sender ? ` - ${w.sender.replace(/\s*\(.*\)\s*$/, '')}, ${w.received}` : '')).join(' · ');
  return (
    <div className="card myweek">
      <div className="myweek-head">
        <h3>My week</h3>
        <span className="myweek-from">{days.length ? 'From ' + from : 'No Transport Planners sheet for this week or next found in the mailbox yet.'}</span>
      </div>
      {days.length > 0 && (
        <div className="myweek-days">
          {days.map((d) => (
            <div key={d.date} className={'myweek-day' + (d.at.getTime() === today.getTime() ? ' today' : '')}>
              <div className="myweek-date">{d.day.slice(0, 3)} {d.date.slice(0, 5)}{d.at.getTime() === today.getTime() ? ' · today' : ''}</div>
              {d.duties.length ? d.duties.map((x, i) => (
                <div key={i} className="myweek-duty" title={x.section || ''}>
                  {x.what}{x.note ? ` ${x.note}` : ''}{x.with && x.with.length ? ` (with ${x.with.join(', ')})` : ''}
                </div>
              )) : <div className="myweek-duty none">Nothing extra</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Rail plan card ----
// The Monday of the week the card's select means, as dd/mm - what the export will ask CTMS for.
function railMonday(week) {
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + (week === 'next' ? 7 : 0));
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' });
}

function RailPlanCard({ onUpload, onCommand }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [week, setWeek] = useState('next');
  // Export from CTMS: the run the dashboard started, followed until the home PC says how it ended
  const [railRun, setRailRun] = useState(null);
  const following = useRef(0);
  const follow = async (id) => {
    following.current = id;
    const until = Date.now() + 16 * 60 * 1000;
    while (following.current === id && Date.now() < until) {
      let st;
      try { st = await ctmsStatus(false); } catch { st = null; }
      const r = st && st.rail_run;
      if (r && r.id === id) {
        setRailRun(r);
        if (r.state !== 'running') return;
      }
      await new Promise((ok) => setTimeout(ok, 4000));
    }
  };
  useEffect(() => {
    // a run started before this page opened is followed too
    ctmsStatus(false).then((st) => {
      const r = st && st.rail_run;
      if (r) { setRailRun(r); if (r.state === 'running') follow(r.id); }
    }).catch(() => {});
    return () => { following.current = 0; };
  }, []);
  const exportCtms = async () => {
    if (!window.confirm(`Export the Short Rail Report for the week of ${railMonday(week)} from CTMS on the work PC, `
      + 'and preview its plan into Files? It drives CTMS for about 3 minutes - leave the work PC alone meanwhile. '
      + 'Nothing is sent.')) return;
    let run;
    try {
      ({ run } = await ctmsRail(week));
    } catch (e) {
      setRailRun({ state: 'refused', said: e.message });
      return;
    }
    setRailRun({ id: run, state: 'running', said: '' });
    follow(run);
  };
  const run = async (mode) => {
    if (!file) {
      // no file picked: Build & send sends the plan last previewed - the one a CTMS export the work PC took
      // builds by itself, or the last CSV previewed here
      if (mode !== 'send') { window.alert('Pick the CTMS rail-plan CSV first.'); return; }
      if (!window.confirm('No CSV picked — SEND the rail plan last previewed (from the CTMS export, or the CSV you last previewed) to all suppliers, hauliers and your DHL colleagues?')) return;
      onCommand({ action: 'rail_plan', mode, week, source: 'last' });
      return;
    }
    if (mode === 'send' && !window.confirm('Build and SEND the rail plan to all suppliers, hauliers and your DHL colleagues?')) return;
    // no command unless the file actually landed - see onUpload in App.jsx
    if (!await onUpload(file)) return;
    onCommand({ action: 'rail_plan', mode, week });
  };
  return (
    <div className="cmd">
      <div className="top"><div className="ci">{I.rail}</div><h3>Rail plan</h3></div>
      <div className="desc">Build the weekly plan from a CTMS CSV, or Export from CTMS for the week picked: the work PC exports it and the plan is previewed by itself. Build &amp; send with no file sends that.</div>
      <input ref={fileRef} type="file" accept=".csv" style={{ marginBottom: 7 }} onChange={(e) => setFile(e.target.files[0])} />
      <select value={week} onChange={(e) => setWeek(e.target.value)} style={{ marginBottom: 7 }}>
        <option value="next">Next week — new plan</option>
        <option value="current">Current week — update</option>
      </select>
      <div className="col" style={{ flexDirection: 'row' }}>
        <button className="btn block" onClick={() => run('preview')}>Preview</button>
        <button className="btn red block" onClick={() => run('send')}>Build &amp; send</button>
      </div>
      <button className="btn block" style={{ marginTop: 7 }} onClick={exportCtms}
        disabled={!!railRun && railRun.state === 'running'}
        title="CTMS on the work PC exports the week's Short Rail Report; its plan is previewed into Files. Nothing is sent.">
        {railRun && railRun.state === 'running' ? 'Exporting from CTMS…' : `Export from CTMS (wc ${railMonday(week)})`}
      </button>
      {railRun && (
        <div className="s" style={{ marginTop: 6 }}>
          {railRun.state === 'running'
            ? 'The work PC is exporting from CTMS - about 3 minutes. Its plan then lands in Files as a preview.'
            : railRun.said}
        </div>
      )}
    </div>
  );
}

// ---- Ad hoc form card (file -> /api/upload -> form_upload command) ----
function AdhocFormCard({ onUpload, busy }) {
  const fileRef = useRef(null);
  const [name, setName] = useState('');
  const [drag, setDrag] = useState(false);
  const pick = (file) => { if (file) { setName(file.name); onUpload(file); } };
  return (
    <div className="cmd"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
      <div className="top"><div className="ci">{I.form}</div><h3>Ad hoc form</h3></div>
      <div className="desc">Drop a filled haulage request form (.xlsx) to build the CSV.</div>
      <input ref={fileRef} type="file" accept=".xlsx,.xlsm" style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])} />
      <div className={'dropzone' + (drag ? ' drag' : '')} style={{ margin: '6px 0 0' }} onClick={() => fileRef.current && fileRef.current.click()}>
        <div className="di">{I.file}</div>
        <div className="d1">{busy ? 'Uploading…' : name ? name : 'Drop .xlsx here, or click'}</div>
        <div className="d2">Filled haulage request form</div>
      </div>
    </div>
  );
}

// ---- DTS: by reference OR by dropping the file ----
// process_dts.py already takes either an NN reference (which it hunts through
// the whole mailbox for) or a direct path to the DTS itself, so both halves sit
// in one card rather than two. Dropping wins when the DTS came to you some
// other way - forwarded on, saved off, or never in this mailbox at all.
function DtsCard({ onUpload, onCommand, busy }) {
  const fileRef = useRef(null);
  const [ref, setRef] = useState('');
  const [name, setName] = useState('');
  const [drag, setDrag] = useState(false);
  const pick = (file) => { if (file) { setName(file.name); onUpload(file); } };
  return (
    <div className="cmd"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
      <div className="top"><div className="ci">{I.doc}</div><h3>Process DTS</h3></div>
      <div className="desc">Type the NN reference, or drop the DTS itself.</div>
      <div className="col" style={{ flexDirection: 'row', gap: 7 }}>
        <input value={ref} placeholder="NN reference" onChange={(e) => setRef(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && ref.trim()) { onCommand({ action: 'dts', order: ref.trim() }); setRef(''); }
          }} />
        <button className="btn red" disabled={!ref.trim()}
          onClick={() => { onCommand({ action: 'dts', order: ref.trim() }); setRef(''); }}>Process</button>
      </div>
      <input ref={fileRef} type="file" accept=".pdf,.xls,.xlsx" style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])} />
      <div className={'dropzone' + (drag ? ' drag' : '')} style={{ margin: '7px 0 0' }}
        onClick={() => fileRef.current && fileRef.current.click()}>
        <div className="di">{I.file}</div>
        <div className="d1">{busy ? 'Uploading…' : name ? name : 'Drop the DTS here, or click'}</div>
        <div className="d2">.pdf, .xls or .xlsx</div>
      </div>
    </div>
  );
}

// ---- input-driven command card (send order / DTS) ----
// ---- Generated files (upload CSVs, rail plans, Synergy sheets) ----
// The agent pushes everything it writes to the outbox; this is where you
// download it. This card was the missing half of every "process" action - the
// CSV was generated on the home PC and there was nowhere on the dashboard to
// get it from.
// The cloud keeps this list in MEMORY only, so a restart or redeploy empties it
// even though the files are still sitting in the outbox on the home PC. The
// agent re-sends everything every 30 minutes, which is a long wait when you are
// looking for one CSV - hence Re-send.
function FilesCard({ onCommand }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState('');
  const [resent, setResent] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () => getFiles().then((d) => { if (live) setFiles(d.files || []); }).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const grab = async (name) => {
    setBusy(name);
    try { await downloadFile(name); } catch { /* gone after a redeploy - list refreshes */ }
    setBusy('');
  };
  return (
    <div className="card statuscard">
      <div className="statushd" style={{ marginBottom: 8 }}>
        <span className="sdot" style={{ background: 'var(--yellow)' }} />
        <b>Files</b>
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 6 }}>
          · what the desk has generated
        </span>
        <button className="btn mini" style={{ marginLeft: 'auto' }} disabled={resent}
          title="Ask the home PC to send everything in its outbox again"
          onClick={() => { setResent(true); onCommand && onCommand({ action: 'resend_files' }); }}>
          {resent ? 'Re-sending…' : 'Re-send'}
        </button>
      </div>
      {files.length ? files.map((f) => (
        <div className="filerow" key={f.name}>
          <div className="fn mono">{f.name}</div>
          <div className="fm">{f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB'
            : Math.max(1, Math.round(f.size / 1024)) + ' KB'} · {f.at}</div>
          <button className="btn mini" disabled={busy === f.name} onClick={() => grab(f.name)}>
            {busy === f.name ? '…' : 'Download'}
          </button>
        </div>
      )) : (
        <div style={{ color: 'var(--muted)', fontSize: 12.5 }}>
          Nothing here — processed CSVs, rail plans and Synergy sheets appear as they
          are made. If you were expecting something, the cloud may have restarted and
          emptied this list: press Re-send.
        </div>
      )}
    </div>
  );
}

function InputCard({ ic, title, desc, placeholder, buttonLabel, kind, onSubmit }) {
  const [val, setVal] = useState('');
  return (
    <div className="cmd">
      <div className="top"><div className="ci">{ic}</div><h3>{title}</h3></div>
      <div className="desc">{desc}</div>
      <input placeholder={placeholder} value={val} style={{ marginBottom: 8 }}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') onSubmit(val); }} />
      <button className={'btn block ' + (kind || '')} onClick={() => onSubmit(val)}>{buttonLabel}</button>
    </div>
  );
}

// ---- orders no email can go to ----
// The sheet's address is mistyped or missing, so the wait list can't send them. They stay here until the right address
// is given, or he has seen to it himself.
const AN_ADDRESS = /^[^@\s;,]+@[^@\s;,.]+(\.[^@\s;,.]+)+$/;

function daysLeft(n) {
  if (n === null || n === undefined) return '';
  if (n < 0) return 'date passed';
  return n === 0 ? 'today' : n === 1 ? 'tomorrow' : 'in ' + n + ' days';
}

function NoAddress({ rows, onCommand }) {
  const [typed, setTyped] = useState({});
  if (!rows || !rows.length) return null;
  const save = (e) => {
    const to = String(typed[e.id] || '').trim();
    if (AN_ADDRESS.test(to)) onCommand({ action: 'waitlist_address', data: { id: e.id, to } });
  };
  const dealtWith = (e) => {
    if (window.confirm('Take ' + (e.orders || []).join(' / ') + ' off? The desk won\'t email or chase it.')) {
      onCommand({ action: 'waitlist_dealt_with', data: { id: e.id } });
    }
  };
  return (
    <div className="card noaddress">
      <div className="noaddress-head">
        <h3>{rows.length === 1 ? '1 order' : rows.length + ' orders'} we can&rsquo;t email</h3>
        <span className="noaddress-why">The sheet has no working address. Type the right one, or press Dealt with if you&rsquo;ve emailed them yourself.</span>
      </div>
      {rows.map((e) => {
        const to = String(typed[e.id] || '').trim();
        return (
          <div className="noaddress-row" key={e.id}>
            <div className="noaddress-what">
              <div className="noaddress-order">{(e.orders || []).join(' / ')}<span className={'noaddress-when' + (e.days !== null && e.days <= 3 ? ' soon' : '')}>{e.date}{e.days !== null && e.days !== undefined ? ' · ' + daysLeft(e.days) : ''}</span></div>
              <div className="noaddress-site">{[e.site, e.postcode].filter(Boolean).join(' ')}</div>
              <div className="noaddress-said">The sheet says: &ldquo;{e.contact_said || 'nothing we can read'}&rdquo;</div>
            </div>
            <div className="noaddress-fix">
              <input type="email" placeholder="The right email address" aria-label={'The right email address for ' + (e.orders || []).join(' / ')}
                value={typed[e.id] || ''} onChange={(ev) => setTyped((t) => ({ ...t, [e.id]: ev.target.value }))}
                onKeyDown={(ev) => { if (ev.key === 'Enter') save(e); }} />
              <button className="btn mini go" disabled={!AN_ADDRESS.test(to)} onClick={() => save(e)}>Use it</button>
              <button className="btn mini" onClick={() => dealtWith(e)}>Dealt with</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Dashboard({
  records, status, panel, setPage, onCommand, onUpload, currentOrder, setCurrentOrder,
  agentOnline, ttlText, onClearDropped, uploadBusy,
}) {
  const tracked = records.length;
  const urgent = records.filter(isUrgent).length;
  const awaiting = records.filter((r) => r.emailed_at && !r.reply_at).length;
  const ready = records.filter(isReady).length;
  const waiters = [...records].filter((r) => !isReady(r))
    .sort((a, b) => (within3(b.delivery_date) - within3(a.delivery_date)))
    .slice(0, 4);

  const st = status || { state: 'idle', detail: 'Waiting for a command.', at: '' };
  const stateColor = {
    idle: 'var(--faint)', queued: 'var(--yellow-d)', running: 'var(--yellow-d)',
    done: 'var(--go)', error: 'var(--red)', preview_ready: 'var(--red)',
    batch_ready: 'var(--yellow-d)', sites_needed: 'var(--red)',
    // wants something from you (a copy-paste), so it reads like the other
    // waiting states rather than a finished-and-forget green
    teams_ready: 'var(--red)',
  }[st.state] || 'var(--faint)';

  const findOrder = (raw) => {
    const o = String(raw || '').trim().split(/[\s,;/+&]+/).filter(Boolean).join(' ');
    if (!o) return;
    setCurrentOrder(o);
    onCommand({ action: 'order_preview', order: o });
  };

  return (
    <div className="scroll"><div className="container page-anim">
      <div className="pagehead">
        <div>
          <div className="kicker">Region 2 · {new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</div>
          <h1 className="h1">Haulage Desk</h1>
        </div>
        <button className="btn red" onClick={() => onCommand({ action: 'extract_preview', week: '' })}>{I.scan} Scan today&rsquo;s extract</button>
      </div>

      <MailApprovals hint={!!(status && status.mail_pending)} />
      <BookingsCard rows={panel && panel.bookings} onCommand={onCommand} />
      <NoAddress rows={panel && panel.no_address} onCommand={onCommand} />

      <MyWeek week={panel && panel.planner_week} />

      <div className="metrics">
        <div className="metric ink"><span className="bar" /><div className="n">{tracked}</div><div className="k">Orders tracked</div></div>
        <div className="metric red"><span className="bar" /><div className="n">{urgent}</div><div className="k">Urgent · ≤3 days</div></div>
        <div className="metric yellow"><span className="bar" /><div className="n">{awaiting}</div><div className="k">Awaiting reply</div></div>
        <div className="metric faint"><span className="bar" /><div className="n">{ready}</div><div className="k">Ready to book</div></div>
      </div>

      {/* Transient review steps the agent drives (batch / edit / sites / decisions) */}
      <FlowPanels status={st} panel={panel} currentOrder={currentOrder} onCommand={onCommand} agentOnline={agentOnline} ttlText={ttlText} />

      <div className="dashgrid">
        <div className="cardgrid">
          <div className="cmd">
            <div className="top"><div className="ci">{I.scan}</div><h3>Today&rsquo;s extract</h3></div>
            <div className="desc">Scan Synergy, preview &amp; send the day&rsquo;s batch.</div>
            <div className="col">
              <button className="btn red block" onClick={() => onCommand({ action: 'extract_preview', week: '' })}>Scan, preview &amp; send</button>
              <button className="btn block" onClick={() => onCommand({ action: 'commit' })}>Save as drafts</button>
            </div>
          </div>

          <MediaSetsCard busy={uploadBusy} onUpload={async (file) => { if (await onUpload(file)) onCommand({ action: 'media_sets' }); }} />

          <SeasonalCard busy={uploadBusy} onUpload={async (file) => { if (await onUpload(file)) onCommand({ action: 'seasonal' }); }} />

          <InputCard ic={I.send} title="Send order(s)" desc="Find specific order numbers and send."
            placeholder="Order no(s), space-separate to group" buttonLabel="Find &amp; preview" onSubmit={findOrder} />

          <DtsCard busy={uploadBusy} onCommand={onCommand}
            onUpload={async (file) => { if (await onUpload(file)) onCommand({ action: 'dts_upload' }); }} />

          <AdhocFormCard busy={uploadBusy} onUpload={async (file) => { if (await onUpload(file)) onCommand({ action: 'form_upload' }); }} />

          <RailPlanCard onUpload={onUpload} onCommand={onCommand} />

          <UploadCard busy={uploadBusy} onUpload={async (file) => { if (await onUpload(file)) onCommand({ action: 'order_upload' }); }} />

          <div className="cmd">
            <div className="top"><div className="ci">{I.cal}</div><h3>Upcoming weeks</h3></div>
            <div className="desc">Pull orders for the weeks ahead.</div>
            <div className="col" style={{ flexDirection: 'row' }}>
              <button className="btn block" onClick={() => onCommand({ action: 'extract_preview', week: 'next' })}>Next week</button>
              <button className="btn block" onClick={() => onCommand({ action: 'extract_preview', week: 'after' })}>Week after</button>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card statuscard">
            <div className="statushd">
              <span className="sdot" style={{ background: stateColor }} />
              <span className="sstate" style={{ color: stateColor }}>{(st.state || 'idle').replace('_', ' ')}</span>
              <span className="stime mono">{st.at}</span>
            </div>
            <div className="statusdetail">
              {st.detail}
              {st.queued > 0 && !agentOnline ? ' (' + st.queued + ' waiting for home PC)' : ''}
            </div>
            {st.dropped && st.dropped.length > 0 && (
              <div className="dropwarn">
                {st.dropped.map((d, i) => (
                  <div key={i}>⚠ NOT sent/run: {d.action}{d.order ? ' (' + d.order + ')' : ''} — expired {d.at} before the home PC picked it up</div>
                ))}
                <button className="btn mini" style={{ marginTop: 8 }} onClick={onClearDropped}>Dismiss</button>
              </div>
            )}
            {st.output && <pre className="statusoutput">{st.output}</pre>}
          </div>

          <div className="card statuscard">
            <div className="statushd">
              <span className="lbl">Next out the door</span>
              <span className="stime" style={{ cursor: 'pointer' }} onClick={() => setPage('tracker')}>View tracker →</span>
            </div>
            <div className="miniwait">
              {!waiters.length && <div className="statusdetail" style={{ fontSize: 12.5, color: 'var(--muted)', paddingTop: 8 }}>Nothing outstanding.</div>}
              {waiters.map((o) => (
                <div className="waitrow" key={o.id}>
                  <span className="o mono">{ordLabel(o)}</span>
                  <span className="s">{o.worksite || o.site}</span>
                  <span className="d" style={isUrgent(o) ? { color: 'var(--red)' } : null}>{dateShort(o.delivery_date)}</span>
                </div>
              ))}
            </div>
          </div>

          <FilesCard onCommand={onCommand} />

          <HolidayCard panel={panel} onCommand={onCommand} />
        </div>
      </div>
    </div></div>
  );
}
