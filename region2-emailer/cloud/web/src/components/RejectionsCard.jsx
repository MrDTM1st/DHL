import { useState } from 'react';

// The Haulier Rejection Form, on the CTMS page beside its to-do (his 11/11: "make it act and look like the CTMS to do
// list"): every no from NOC or a Tier 1 on the form - read by the home PC from the hauliers' replies, or put in here when
// it came by phone or Teams - with what will go on the form. Anything missing, or worked out rather than read, waits for
// his pick in the row, as the to-do's held items do; the button sends the ready ones on the work PC one after another,
// each counted only when the form says it took it (rejections.py). Auto sends the ready ones by themselves.

const MODE = 'Look mum, no hands';
const HAULIERS = ["DE O'Reilly", 'Hargreaves Services', 'Hotspur Hire (HHL)', 'JG Vesty', 'Lawsons Haulage',
  'Tennant Transport', 'V Festa & Sons', 'Wm Hamilton & Sons', 'DHL NOC'];
const PRODUCTS = ['Rail', 'Adhoc - Rail / S&C', 'Bagged Ballast', 'Loose Ballast', 'Sleepers', 'Timbers / Bearers',
  'Wheelsets', 'Train Bogies', 'Container', 'Pallets', 'Shift Work', 'Electrification - Piles / Masts etc.'];
const VEHICLES = ['Artic Flat', 'Artic Hiab', '60ft Flat', '60ft Hiab', 'Trombone', 'Trombone Hiab', 'Artic Moffett',
  'Rigid Flat / Hiab', 'Rigid Tipper', 'Artic Tipper', 'Curtainsider', 'Other'];
const REASONS = ['No Availability - General', 'No Availability - Night/Weekend', 'No Availability - Vehicle Type',
  'No Availability - Date of Job/Notice', 'No Reply', 'No Availability - Area', 'Priced Off-Matrix - booked in as cheapest',
  'Priced Off-Matrix', 'No Availability - Rate', 'Partial Rejection', 'No Availability - PTS',
  'Rejected - Product/Site Access', 'Other'];
const STATUS = { ready: 'Ready', held: 'Needs you', sending: 'Sending', failed: 'Not sent' };
const FROM = { reply: 'their reply', added: 'put in here' };
// each of the form's answers as the list names it, and how it is picked
const FIELD = {
  date: { label: 'Date of job', text: 'DD/MM/YYYY' },
  collection: { label: 'Collection site', text: 'Site and postcode' },
  postcode: { label: 'Delivery postcode', text: 'e.g. AB1 2CD' },
  quantity: { label: 'Quantity', text: 'e.g. 15 rails' },
  consolidated: { label: 'Consolidated', options: ['No', 'Yes'] },
  product: { label: 'Product', options: PRODUCTS },
  vehicle: { label: 'Vehicle', options: VEHICLES, other: 'vehicle_other' },
  rear_steer: { label: 'Rear-steer', options: ['No', 'Yes'] },
  reason: { label: 'Reason', options: REASONS, other: 'other' },
  hauliers: { label: 'Who said no' },
};

const ukDate = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? `${m[3]}/${m[2]}/${m[1]}` : ''; };
const ddmm = (iso) => ukDate(iso).slice(0, 5);

// what will go on the form, as the to-do's plan line says what will be typed
function formText(r) {
  return [r.date && 'job ' + ddmm(r.date), r.product, r.quantity, r.vehicle === 'Other' ? r.vehicle_other : r.vehicle,
    r.rear_steer && 'rear-steer ' + r.rear_steer.toLowerCase(), r.consolidated === 'Yes' && 'consolidated',
    r.collection && (r.collection + (r.postcode ? ' → ' + r.postcode : '')),
    !r.collection && r.postcode && 'to ' + r.postcode].filter(Boolean).join(' · ');
}

// One answer the form can't have yet - missing, or worked out and NOT CERTAIN - and his pick, as a held to-do item asks
function RejectCheck({ r, n, onSave }) {
  const spec = FIELD[n.f] || { label: n.f };
  const now = n.f === 'date' ? ukDate(r.date) : String(r[n.f] || '');
  const [val, setVal] = useState(n.unsure ? now : '');
  const [extra, setExtra] = useState(spec.other ? String(r[spec.other] || '') : '');
  if (n.f === 'hauliers') {
    return <div className="ctms-held"><b>{spec.label}</b><div className="ctms-muted">Not one the form lists - Not needed takes it off.</div></div>;
  }
  const needsExtra = !!spec.other && val === 'Other';
  const ok = val.trim() && (!needsExtra || extra.trim());
  const save = () => onSave(r, { [n.f]: val.trim(), ...(needsExtra ? { [spec.other]: extra.trim() } : {}) });
  return (
    <div className="ctms-held">
      <b>{spec.label}</b>{n.f === 'reason' && r.said ? <> - they said: <q>{r.said}</q></> : null}
      <div className="ctms-muted">{n.unsure
        ? (n.f === 'reason' ? 'Read from their words, NOT CERTAIN - is it right?' : 'Worked out from the order, NOT CERTAIN - is it right?')
        : 'Not known yet - the form needs it.'}</div>
      <div className="ctms-held-pick">
        {spec.options ? (
          <select value={val} onChange={(e) => setVal(e.target.value)}>
            <option value="">Pick…</option>
            {spec.options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        ) : (
          <input value={val} onChange={(e) => setVal(e.target.value)} placeholder={spec.text} />
        )}
        {needsExtra && <input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="In their words" />}
        <button className="btn mini" disabled={!ok} onClick={save}>{n.unsure && val === now ? 'That’s right' : 'Save'}</button>
      </div>
    </div>
  );
}

// A no he was told by phone or Teams: the order number is enough - the home PC fills in the rest from the order where it
// knows it, and anything it can't, or can only work out, comes back to him in the row
function AddNo({ onSave, onCancel }) {
  const [f, setF] = useState({ orders: '', hauliers: ['DHL NOC'], reason: '', other: '', date: '' });
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const tick = (h) => setF((x) => ({ ...x, hauliers: x.hauliers.includes(h) ? x.hauliers.filter((y) => y !== h) : [...x.hauliers, h] }));
  const ok = f.orders.trim() && f.hauliers.length && f.reason && (f.reason !== 'Other' || f.other.trim());
  return (
    <div className="ctms-held rj-add">
      <b>A no by phone or Teams</b>
      <div className="ctms-muted">The order number is enough: the rest comes from the order where the desk knows it, and anything it can&rsquo;t fill in waits for you in the row.</div>
      <div className="ctms-held-pick"><input value={f.orders} onChange={set('orders')} placeholder="Order(s), e.g. 1234567 / 1234568" /></div>
      <div className="ctms-held-pick">
        {HAULIERS.map((h) => (
          <button type="button" key={h} className={'chip' + (f.hauliers.includes(h) ? ' active' : '')} onClick={() => tick(h)}>{h}</button>
        ))}
      </div>
      <div className="ctms-held-pick">
        <select value={f.reason} onChange={set('reason')}>
          <option value="">Why…</option>
          {REASONS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {f.reason === 'Other' && <input value={f.other} onChange={set('other')} placeholder="In their words" />}
        <input value={f.date} onChange={set('date')} placeholder="Date of job (from the order if blank)" />
      </div>
      <div className="ctms-held-pick">
        <button className="btn mini go" disabled={!ok} onClick={() => onSave(Object.fromEntries(Object.entries(f).filter(([, v]) => (Array.isArray(v) ? v.length : String(v).trim()))))}>Put it on the list</button>
        <button className="btn mini" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

export default function RejectionList({ data, run, busy, onRun, onCommand, pushToast }) {
  const [adding, setAdding] = useState(false);
  const rows = (data && data.open) || [];
  const sent = (data && data.sent) || [];
  const auto = !!(data && data.auto);
  const running = !!(run && run.state === 'running');
  const ready = rows.filter((r) => r.status === 'ready' && !(r.needs || []).length);
  const last = sent.length ? sent[sent.length - 1] : null;

  const save = (r, change) => {
    onCommand({ action: 'rejection', data: { do: 'edit', id: r.id, rec: change } });
    if (pushToast) pushToast('Noted', `${r.orders.join(' / ')}: ${Object.values(change).join(', ')} - the list updates in a moment.`, 'go');
  };
  const drop = (r) => {
    if (!window.confirm(`Take ${r.hauliers.join(', ')}'s no on ${r.orders.join(' / ')} off the list? It won't go on the form.`)) return;
    onCommand({ action: 'rejection', data: { do: 'drop', id: r.id } });
  };
  const flipAuto = () => {
    if (!auto && !window.confirm('Send the ready ones by themselves? Anything NOT CERTAIN or missing still waits for '
      + 'your pick, and one only goes while the work PC has been left alone for a minute.')) return;
    onCommand({ action: 'rejection', data: { do: 'auto', on: !auto } });
  };

  return (
    <div className="card statuscard">
      <div className="statushd">
        <span className="lbl">Haulier rejection form</span>
        <span className={'ctms-todo-n' + (rows.length ? ' some' : '')}>{rows.length}</span>
        <button className={'switch rj-auto' + (auto ? ' on' : '')} role="switch" aria-checked={auto}
          title={auto ? 'Ready ones go by themselves. Click to make each wait for Send.' : 'Each waits for Send. Click to let the ready ones go by themselves.'}
          onClick={flipAuto}><span className="knob" />Auto</button>
      </div>
      {rows.map((r) => {
        const needs = r.needs || [];
        return (
          <div className="ctms-act ctms-todo" key={r.id}>
            <span className={'ctms-todo-kind ' + (r.hauliers.includes('DHL NOC') ? 'noc' : 'tier1')}>
              {r.hauliers.includes('DHL NOC') ? 'NOC' : 'Tier 1'}</span>
            <span className="d"><b className="mono">{r.orders.join(' / ')}</b> {r.hauliers.join(', ')} said no
              {r.reason && !needs.some((n) => n.f === 'reason') ? ': ' + (r.reason === 'Other' ? r.other : r.reason) : ''}
              <div className="ctms-plan">{formText(r) || 'Nothing known of the job yet.'}</div>
              {r.said && !needs.some((n) => n.f === 'reason') && (
                <div className="ctms-plan why">&ldquo;{r.said}&rdquo; - {FROM[r.source] || r.source}</div>)}
              {r.status === 'failed' && r.note && <div className="ctms-plan why">Last try: {r.note}</div>}
              {needs.map((n) => <RejectCheck key={n.f + ':' + (r[n.f] || '')} r={r} n={n} onSave={save} />)}
              <div className="rj-row-foot">
                <button className="btn mini" disabled={r.status === 'sending'} onClick={() => drop(r)}>Not needed</button>
              </div>
            </span>
            <span className={'ctms-plan-st ' + r.status}>{STATUS[r.status] || r.status}</span>
          </div>
        );
      })}
      {ready.length > 0 && (
        <div className="ctms-run">
          <button className="btn primary" disabled={running || busy} onClick={() => onRun(ready.map((r) => r.id))}>
            {running ? 'Sending on the form…' : `Send ${ready.length} on the form`}
          </button>
          <span className="ctms-muted">{MODE} switches on for the run and back as it was after. Each one counts as sent
            only when the form says it took it; one that doesn&rsquo;t stays on the list and the rest carry on.</span>
        </div>
      )}
      {running && (
        <div className="ctms-runlog">
          <b>Sending on the form: {(run.results || []).length} of {(run.ids || []).length} done.</b>
          {run.on ? ` Now on ${run.on}.` : ''} Leave the form on the work PC to it for now.
          {(run.results || []).map((x) => <div key={x.id} className={x.ok ? 'ok' : 'bad'}>{x.ok ? '✓' : '✗'} {x.said}</div>)}
        </div>
      )}
      {run && run.state === 'done' && (
        <div className="ctms-runlog">
          <b>Last run {run.ended || run.at}:</b> {run.said}
          {(run.results || []).map((x) => <div key={x.id} className={x.ok ? 'ok' : 'bad'}>{x.ok ? '✓' : '✗'} {x.said}</div>)}
        </div>
      )}
      <div className="ctms-muted" style={{ marginTop: rows.length ? 8 : 0 }}>
        {!rows.length ? 'Nothing waiting - every no is on the form.' + (last ? ` Last sent: ${last.hauliers.join(', ')} on ${last.orders.join(' / ')}, ${last.sent_at}.` : '')
          : rows.some((r) => (r.needs || []).length) ? 'Ones that need you want your pick above before the button sends them.' : ''}
      </div>
      {adding ? (
        <AddNo onCancel={() => setAdding(false)}
          onSave={(rec) => { onCommand({ action: 'rejection', data: { do: 'add', rec } }); setAdding(false); }} />
      ) : (
        <div className="ctms-run"><button className="btn mini" onClick={() => setAdding(true)}>+ A no by phone or Teams</button></div>
      )}
    </div>
  );
}
