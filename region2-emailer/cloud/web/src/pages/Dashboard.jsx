import { useState, useRef } from 'react';
import { I } from '../icons.jsx';
import { isUrgent, ordLabel, within3, dateShort } from '../lib/orders.js';
import { fileToB64 } from '../api.js';
import FlowPanels from '../components/FlowPanels.jsx';

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

// ---- Rail plan card ----
function RailPlanCard({ onUpload, onCommand }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [week, setWeek] = useState('next');
  const run = async (mode) => {
    if (!file) { window.alert('Pick the CTMS rail-plan CSV first.'); return; }
    if (mode === 'send' && !window.confirm('Build and SEND the rail plan to all suppliers, hauliers and your DHL colleagues?')) return;
    await onUpload(file);
    onCommand({ action: 'rail_plan', mode, week });
  };
  return (
    <div className="cmd">
      <div className="top"><div className="ci">{I.rail}</div><h3>Rail plan</h3></div>
      <div className="desc">Build the weekly plan from a CTMS CSV.</div>
      <input ref={fileRef} type="file" accept=".csv" style={{ marginBottom: 7 }} onChange={(e) => setFile(e.target.files[0])} />
      <select value={week} onChange={(e) => setWeek(e.target.value)} style={{ marginBottom: 7 }}>
        <option value="next">Next week — new plan</option>
        <option value="current">Current week — update</option>
      </select>
      <div className="col" style={{ flexDirection: 'row' }}>
        <button className="btn block" onClick={() => run('preview')}>Preview</button>
        <button className="btn red block" onClick={() => run('send')}>Build &amp; send</button>
      </div>
    </div>
  );
}

// ---- input-driven command card (send order / DTS / ad-hoc form) ----
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

export default function Dashboard({
  records, status, panel, setPage, onCommand, onUpload, currentOrder, setCurrentOrder,
  agentOnline, ttlText, onClearDropped, uploadBusy,
}) {
  const tracked = records.length;
  const urgent = records.filter(isUrgent).length;
  const awaiting = records.filter((r) => r.emailed_at && !r.reply_at).length;
  const ready = records.filter((r) => r.sendoff_ready).length;
  const waiters = [...records].filter((r) => !r.sendoff_ready)
    .sort((a, b) => (within3(b.delivery_date) - within3(a.delivery_date)))
    .slice(0, 4);

  const st = status || { state: 'idle', detail: 'Waiting for a command.', at: '' };
  const stateColor = {
    idle: 'var(--faint)', queued: 'var(--yellow-d)', running: 'var(--yellow-d)',
    done: 'var(--go)', error: 'var(--red)', preview_ready: 'var(--red)',
    batch_ready: 'var(--yellow-d)', sites_needed: 'var(--red)',
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

      <div className="metrics">
        <div className="metric ink"><span className="bar" /><div className="n">{tracked}</div><div className="k">Orders tracked</div></div>
        <div className="metric red"><span className="bar" /><div className="n">{urgent}</div><div className="k">Urgent · ≤3 days</div></div>
        <div className="metric yellow"><span className="bar" /><div className="n">{awaiting}</div><div className="k">Awaiting reply</div></div>
        <div className="metric faint"><span className="bar" /><div className="n">{ready}</div><div className="k">Ready to send off</div></div>
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

          <div className="cmd">
            <div className="top"><div className="ci">{I.cal}</div><h3>Upcoming weeks</h3></div>
            <div className="desc">Pull orders for the weeks ahead.</div>
            <div className="col" style={{ flexDirection: 'row' }}>
              <button className="btn block" onClick={() => onCommand({ action: 'extract_preview', week: 'next' })}>Next week</button>
              <button className="btn block" onClick={() => onCommand({ action: 'extract_preview', week: 'after' })}>Week after</button>
            </div>
          </div>

          <InputCard ic={I.send} title="Send order(s)" desc="Find specific order numbers and send."
            placeholder="Order no(s), space-separate to group" buttonLabel="Find &amp; preview" onSubmit={findOrder} />

          <InputCard ic={I.doc} title="Process DTS" desc="Convert a DTS reference into a run."
            placeholder="NN reference" kind="red" buttonLabel="Process"
            onSubmit={(v) => { if (v.trim()) onCommand({ action: 'dts', order: v.trim() }); }} />

          <InputCard ic={I.form} title="Ad hoc form" desc="Build a CSV from a delivery form."
            placeholder="Blank = latest" kind="red" buttonLabel="Build CSV"
            onSubmit={(v) => onCommand({ action: 'form', order: v.trim() || 'latest' })} />

          <RailPlanCard onUpload={onUpload} onCommand={onCommand} />

          <UploadCard busy={uploadBusy} onUpload={async (file) => { await onUpload(file); onCommand({ action: 'order_upload' }); }} />
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

          <HolidayCard panel={panel} onCommand={onCommand} />
        </div>
      </div>
    </div></div>
  );
}
