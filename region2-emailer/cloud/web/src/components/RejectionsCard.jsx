import { useState } from 'react';
import { ctmsRejection } from '../api.js';

// The Haulier Rejection Form (his 11/11: "auto filled", "the least buttons as possible"): every no from NOC or a Tier 1
// on the form - read by the home PC from the hauliers' replies, or put in here when it came by phone or Teams. Send fills
// the form in and submits it on the work PC; Auto sends the complete ones by themselves. NOT CERTAIN marks what was worked
// out rather than read: pressing Send is his word on it (rejections.py).

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
const STATE = { ready: 'Ready', held: 'Needs a look', sending: 'Sending…', failed: 'Not sent' };
const FROM = { reply: 'from their reply', added: 'put in here' };

const ukDate = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? `${m[3]}/${m[2]}/${m[1]}` : ''; };

function Editor({ rec, adding, onSave, onCancel }) {
  const [f, setF] = useState(() => ({
    orders: (rec.orders || []).join(' / '), hauliers: rec.hauliers || ['DHL NOC'], reason: rec.reason || '',
    other: rec.other || '', date: rec.date || '', collection: rec.collection || '', postcode: rec.postcode || '',
    consolidated: rec.consolidated || 'No', product: rec.product || '', quantity: rec.quantity || '',
    vehicle: rec.vehicle || '', vehicle_other: rec.vehicle_other || '', rear_steer: rec.rear_steer || 'No',
  }));
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const tick = (h) => setF((x) => ({ ...x, hauliers: x.hauliers.includes(h) ? x.hauliers.filter((y) => y !== h) : [...x.hauliers, h] }));
  const sel = (k, label, opts, blank) => (
    <label className="pf-row"><span>{label}</span>
      <select value={f[k]} onChange={set(k)}>
        {blank && <option value="">{blank}</option>}
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
  const ok = f.orders.trim() && f.hauliers.length && f.reason && (f.reason !== 'Other' || f.other.trim());
  const save = () => {
    // only what he set or changed goes back: the home PC fills the rest from the order (and marks what it works out)
    const out = {};
    Object.keys(f).forEach((k) => {
      const was = k === 'orders' ? (rec.orders || []).join(' / ') : rec[k];
      if (JSON.stringify(f[k]) !== JSON.stringify(was === undefined ? (k === 'hauliers' ? ['DHL NOC'] : '') : was)
          && f[k] !== '') out[k] = f[k];
    });
    if (adding) Object.assign(out, { orders: f.orders, hauliers: f.hauliers, reason: f.reason });
    onSave(out);
  };
  return (
    <div className="phoneform">
      <div className="pf-head">{adding ? 'A no by phone or Teams' : 'Change it before it goes'}</div>
      {adding && <div className="pf-note">The order number is enough: the date, product and vehicle come from the order where the desk knows it.</div>}
      <label className="pf-row"><span>Order(s)</span><input value={f.orders} onChange={set('orders')} placeholder="e.g. 1234567 / 1234568" /></label>
      <div className="pf-row"><span>Who said no</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {HAULIERS.map((h) => (
            <button type="button" key={h} className={'chip' + (f.hauliers.includes(h) ? ' active' : '')} onClick={() => tick(h)}>{h}</button>
          ))}
        </div>
      </div>
      {sel('reason', 'Why', REASONS, 'Pick…')}
      {f.reason === 'Other' && <label className="pf-row"><span>Their words</span><input value={f.other} onChange={set('other')} /></label>}
      <label className="pf-row"><span>Date of job</span><input type="date" value={f.date} onChange={set('date')} /></label>
      {sel('product', 'Product', PRODUCTS, adding ? 'From the order' : 'Pick…')}
      {sel('vehicle', 'Vehicle', VEHICLES, adding ? 'From the order' : 'Pick…')}
      {f.vehicle === 'Other' && <label className="pf-row"><span>Which vehicle</span><input value={f.vehicle_other} onChange={set('vehicle_other')} /></label>}
      <label className="pf-row"><span>Quantity</span><input value={f.quantity} onChange={set('quantity')} placeholder={adding ? 'From the order' : ''} /></label>
      <label className="pf-row"><span>Collection</span><input value={f.collection} onChange={set('collection')} placeholder={adding ? 'From the order' : ''} /></label>
      <label className="pf-row"><span>Delivery postcode</span><input value={f.postcode} onChange={set('postcode')} placeholder={adding ? 'From the order' : ''} /></label>
      {sel('consolidated', 'Consolidated', ['No', 'Yes'])}
      {sel('rear_steer', 'Rear-steer', ['No', 'Yes'])}
      <div className="pf-foot">
        <button className="btn go" disabled={!ok} onClick={save}>{adding ? 'Put it on the card' : 'Save'}</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function Detail({ r }) {
  const unsure = new Set(r.unsure || []);
  const bit = (k, text) => text ? (
    <span key={k} className={unsure.has(k) ? 'rj-unsure' : ''} title={unsure.has(k) ? 'NOT CERTAIN - worked out, not read' : undefined}>
      {text}{unsure.has(k) ? ' (NOT CERTAIN)' : ''}
    </span>
  ) : null;
  const parts = [
    bit('date', r.date ? 'Job ' + ukDate(r.date) : ''), bit('product', r.product), bit('quantity', r.quantity),
    bit('vehicle', r.vehicle === 'Other' ? r.vehicle_other : r.vehicle), bit('rear_steer', r.rear_steer ? 'Rear-steer ' + r.rear_steer : ''),
    bit('consolidated', r.consolidated === 'Yes' ? 'Consolidated' : ''),
    bit('collection', r.collection ? r.collection + (r.postcode ? ' → ' + r.postcode : '') : (r.postcode ? 'To ' + r.postcode : '')),
  ].filter(Boolean);
  return <div className="noaddress-site">{parts.reduce((acc, p, i) => (i ? [...acc, ' · ', p] : [p]), [])}</div>;
}

export default function RejectionsCard({ data, onCommand }) {
  const [said, setSaid] = useState({});
  const [editing, setEditing] = useState(null);           // a response's id, or 'new'
  const rows = (data && data.open) || [];
  const sent = (data && data.sent) || [];
  const auto = !!(data && data.auto);
  const note = (id, text) => setSaid((s) => ({ ...s, [id]: text }));

  const send = async (r) => {
    note(r.id, 'Filling it in on the work PC…');
    try {
      await ctmsRejection(r.id, {});
      note(r.id, 'Being filled in and submitted on the work PC - this card updates when it ends.');
    } catch (e) {
      note(r.id, e.message);
    }
  };
  const drop = (r) => {
    if (!window.confirm(`Take the ${r.hauliers.join(', ')} no on ${r.orders.join(' / ')} off? It won't go on the form.`)) return;
    onCommand({ action: 'rejection', data: { do: 'drop', id: r.id } });
    note(r.id, 'Taken off.');
  };
  const flipAuto = () => {
    if (!auto && !window.confirm('Send the complete ones by themselves? Anything NOT CERTAIN or missing still waits for you, '
      + 'and one only goes while the work PC has been left alone for a minute.')) return;
    onCommand({ action: 'rejection', data: { do: 'auto', on: !auto } });
  };

  return (
    <div className="card noaddress rj-card">
      <div className="noaddress-head">
        <h3>Haulier rejection form{rows.length ? ` · ${rows.length} to go` : ''}</h3>
        <span className="noaddress-why">NOC and Tier 1 no&rsquo;s, filled in for you. Send submits it on the work PC.</span>
        <button className={'switch' + (auto ? ' on' : '')} role="switch" aria-checked={auto} style={{ marginLeft: 'auto' }}
          title={auto ? 'Complete ones go by themselves. Click to make each one wait for Send.' : 'Each one waits for your Send. Click to let the complete ones go by themselves.'}
          onClick={flipAuto}><span className="knob" />Auto</button>
        <button className="btn mini" onClick={() => setEditing(editing === 'new' ? null : 'new')}>+ A no by phone or Teams</button>
      </div>
      {editing === 'new' && (
        <Editor rec={{}} adding onCancel={() => setEditing(null)}
          onSave={(rec) => { onCommand({ action: 'rejection', data: { do: 'add', rec } }); setEditing(null); }} />
      )}
      {!rows.length && editing !== 'new' && (
        <div className="noaddress-said">Nothing waiting.{sent.length ? ` Last sent: ${sent[sent.length - 1].hauliers.join(', ')} on ${sent[sent.length - 1].orders.join(' / ')} (${sent[sent.length - 1].sent_at}).` : ''}</div>
      )}
      {rows.map((r) => (
        <div className="noaddress-row" key={r.id}>
          {editing === r.id ? (
            <div style={{ flex: '1 1 100%' }}>
              <Editor rec={r} onCancel={() => setEditing(null)}
                onSave={(rec) => { onCommand({ action: 'rejection', data: { do: 'edit', id: r.id, rec } }); setEditing(null); note(r.id, 'Saving…'); }} />
            </div>
          ) : (
            <>
              <div className="noaddress-what">
                <div className="noaddress-order">
                  {r.orders.join(' / ')}
                  <span className={'noaddress-when' + (r.status === 'ready' ? '' : ' soon')}>{STATE[r.status] || r.status}</span>
                </div>
                <div className="noaddress-site"><b>{r.hauliers.join(', ')}</b> · <span className={(r.unsure || []).includes('reason') ? 'rj-unsure' : ''}>{r.reason === 'Other' ? r.other : r.reason}{(r.unsure || []).includes('reason') ? ' (NOT CERTAIN)' : ''}</span></div>
                <Detail r={r} />
                {r.said && <div className="noaddress-said">&ldquo;{r.said}&rdquo; {FROM[r.source] ? `(${FROM[r.source]})` : ''}</div>}
                {(r.gaps || []).length > 0 && (
                  <div className="noaddress-said">
                    {r.gaps.some((g) => !g.includes('NOT CERTAIN'))
                      ? `Missing before it can go: ${r.gaps.filter((g) => !g.includes('NOT CERTAIN')).join(', ')} - Change puts it in.`
                      : 'Check the NOT CERTAIN parts: Send is your word on them.'}
                  </div>
                )}
                {r.status === 'failed' && r.note && <div className="noaddress-said">Last try: {r.note}</div>}
                {said[r.id] && <div className="noaddress-said">{said[r.id]}</div>}
              </div>
              <div className="noaddress-fix">
                <button className="btn mini go" disabled={r.status === 'sending' || (r.gaps || []).some((g) => !g.includes('NOT CERTAIN'))}
                  title={(r.gaps || []).length ? 'Send is your word on anything NOT CERTAIN' : undefined}
                  onClick={() => send(r)}>Send</button>
                <button className="btn mini" disabled={r.status === 'sending'} onClick={() => setEditing(r.id)}>Change</button>
                <button className="btn mini" disabled={r.status === 'sending'} onClick={() => drop(r)}>Not needed</button>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
