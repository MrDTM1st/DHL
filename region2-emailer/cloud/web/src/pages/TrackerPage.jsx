import { useState } from 'react';
import { I } from '../icons.jsx';
import {
  isUrgent, within3, ordLabel, statusLabel, isAmberStatus, dueText, dateShort,
  stageOf, DFIELDS, detVal,
} from '../lib/orders.js';

// Pipeline: Drafted -> Emailed -> Reply -> Sent off, coloured from the real
// timestamp fields (emailed_at / chases / reply_at / ooo_at / sendoff_ready).
function Pipeline({ r }) {
  const emailed = !!r.emailed_at;
  const chased = (r.chases || 0) > 0;
  const reply = !!r.reply_at;
  const ooo = !!r.ooo_at;
  const sendoff = !!r.sendoff_ready;
  const seg = (cls) => <span className={'seg ' + cls} />;
  const b2 = chased ? 'chased' : (emailed ? 'done' : '');
  const b3 = ooo ? 'chased' : (reply ? 'done' : '');
  const b4 = sendoff ? 'done' : '';
  const cap = r.emailed_at ? '1st emailed ' + dateShort(r.emailed_at) : 'Drafted';
  return (
    <div>
      <div className="pipe">{seg('done')}{seg(b2)}{seg(b3)}{seg(b4)}</div>
      <div className="pipecap">{cap}{chased && !sendoff ? ' · ' + r.chases + ' chase' + (r.chases > 1 ? 's' : '') : ''}</div>
    </div>
  );
}

// Parsed delivery-detail chips; amber ones carry a one-click confirm/fix that
// teaches the home tool (learn_detail command).
function DetailChips({ r, onLearn }) {
  const d = r.details || {};
  const chips = DFIELDS.map(([k, label]) => {
    const v = d[k], val = detVal(k, v);
    if (!val) return null;
    const amber = v && v.confidence === 'amber';
    return (
      <span className={'dchip' + (amber ? ' amber' : '')} key={k}>
        {label}: <b>{val}</b>
        {amber && (
          <>
            <span className="fix" title="Correct" onClick={(e) => { e.stopPropagation(); onLearn(r.id, k, val); }}>✓</span>
            <span className="fix" title="Fix" onClick={(e) => { e.stopPropagation(); const nv = window.prompt('Correct value for ' + k + ':', val); if (nv && nv.trim()) onLearn(r.id, k, nv.trim()); }}>✎</span>
          </>
        )}
      </span>
    );
  }).filter(Boolean);
  const miss = r.missing || [];
  if (!chips.length && !miss.length) return null;
  return (
    <div className="tkchips">
      {chips}
      {miss.length > 0 && <span className="dmiss">still needed: {miss.join(', ')}</span>}
    </div>
  );
}

export default function TrackerPage({ records, onSelect, onCommand, onLearn, onBookedCall }) {
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');

  const counts = {
    all: records.length,
    urgent: records.filter(isUrgent).length,
    awaiting: records.filter((r) => r.emailed_at && !r.reply_at).length,
    ready: records.filter((r) => r.sendoff_ready).length,
  };
  const list = records.filter((r) => {
    if (filter === 'urgent' && !isUrgent(r)) return false;
    if (filter === 'awaiting' && !(r.emailed_at && !r.reply_at)) return false;
    if (filter === 'ready' && !r.sendoff_ready) return false;
    if (q) {
      const s = (ordLabel(r) + ' ' + (r.site || '') + ' ' + (r.worksite || '') + ' ' + (r.to || '') + ' ' + (r.materials || '')).toLowerCase();
      if (!s.includes(q.toLowerCase())) return false;
    }
    return true;
  }).sort((a, b) => (isUrgent(b) - isUrgent(a)));

  const chips = [['all', 'All'], ['urgent', 'Urgent'], ['awaiting', 'Awaiting reply'], ['ready', 'Send-off ready']];

  return (
    <div className="scroll"><div className="container page-anim">
      <div className="pagehead">
        <div>
          <div className="kicker">Pipeline</div>
          <h1 className="h1">Order tracker</h1>
          <p>Every order the desk has emailed, from first draft to send-off brief. Drafted → Emailed → Reply → Sent off.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={() => onCommand({ action: 'tracker_refresh' })}>{I.check} Check replies</button>
          <button className="btn red" onClick={() => { if (window.confirm('Send follow-up chasers to every order that is 2+ business days overdue a reply?')) onCommand({ action: 'run_chasers' }); }}>Run chasers</button>
        </div>
      </div>

      <div className="toolbar">
        <div className="filters">
          {chips.map(([k, label]) => (
            <button key={k} className={'chip' + (filter === k ? ' active' : '')} onClick={() => setFilter(k)}>
              {label}<span className="c">{counts[k]}</span>
            </button>
          ))}
        </div>
        <div className="search">{I.search}<input placeholder="Search orders, sites, hauliers…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>

      {list.length === 0 && (
        <div className="emptybox">{I.search}<div className="big">Nothing matches</div><div>Try a different filter or search.</div></div>
      )}

      {list.map((r) => (
        <div className={'tkitem' + (isUrgent(r) ? ' urgent' : '')} key={r.id} onClick={() => onSelect(r)}>
          <div className="tkmeta">
            <div className="ord">
              {ordLabel(r)}
              {r.materials && <span className="mat">· {r.materials}</span>}
              {r.loose_ballast && <span className="lbadge">LOOSE BALLAST</span>}
              {within3(r.delivery_date) && <span className="ubadge">≤3 DAYS</span>}
              {(r.chases || 0) > 0 && <span className="chases">{r.chases} chase{r.chases > 1 ? 's' : ''}</span>}
            </div>
            <div className="sub">{[r.worksite || r.site, r.postcode].filter(Boolean).join(', ')}{r.to ? ' · ' + r.to : ''}</div>
          </div>
          <div className="tkright">
            <div className={'tkstatus' + (isAmberStatus(r) ? ' amber' : '')}>{statusLabel(r)}</div>
            <div className={'tkdue' + (isUrgent(r) ? ' red' : '')}>{dueText(r)}{r.delivery_date ? ' · ' + dateShort(r.delivery_date) : ''}</div>
          </div>
          <div className="pipewrap"><Pipeline r={r} /></div>
          <DetailChips r={r} onLearn={onLearn} />
          <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, marginTop: 4 }}>
            <button className="btn mini" onClick={(e) => { e.stopPropagation(); onSelect(r); }}>View brief</button>
            <button className="btn mini" onClick={(e) => { e.stopPropagation(); onBookedCall(r); }}>Booked via call</button>
          </div>
        </div>
      ))}
    </div></div>
  );
}
