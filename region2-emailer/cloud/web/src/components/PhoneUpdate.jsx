import { useMemo, useState } from 'react';
import { jobOf, siteContactOf } from '../lib/orders.js';

// "Updated over the phone" (his ask, 01/11): what the site said on a call, picked from drop-downs wherever there is
// a choice ("instead of me typing it in, whenever you can just give me a quick drop down"), each filled in with what
// is known already - an emailed reply, the order's sheet. Saved, the home PC puts the answers on the order the way a
// reply lands and adds the order's update to the CTMS page's to-do list (phone_update.py) - it checks them again.

const pad = (n) => String(n).padStart(2, '0');
const dmy = (d) => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
const TIMES = Array.from({ length: 48 }, (_, i) => `${pad(Math.floor(i / 2))}:${i % 2 ? '30' : '00'}`);

// the next six weeks, the order's own day first when it is not among them
function dayOptions(current) {
  const out = [];
  const t = new Date();
  t.setHours(0, 0, 0, 0);
  for (let k = 0; k < 42; k += 1) {
    const d = new Date(t);
    d.setDate(t.getDate() + k);
    out.push([dmy(d), d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + dmy(d).slice(0, 5)]);
  }
  if (current && !out.some(([v]) => v === current)) out.unshift([current, current]);
  return out;
}

// "to": every time but the start, beginning just after it - a night job runs past midnight
function toOptions(from) {
  const i = TIMES.indexOf(from);
  return i < 0 ? TIMES : TIMES.slice(i + 1).concat(TIMES.slice(0, i));
}

// who we know of at the site: the reply's contact, the order sheet's - each with a number
function knownContacts(r) {
  const seen = new Set();
  const out = [];
  const add = (name, phone) => {
    const digits = String(phone || '').replace(/[^\d+]/g, '');
    if (!digits || seen.has(digits)) return;
    seen.add(digits);
    out.push({ name: name || '', phone: digits });
  };
  const c = (r.details && r.details.contact) || {};
  add(c.name, c.phone);
  siteContactOf(r).calls.forEach((x) => add(x.name, x.number));
  return out;
}

const fieldOf = (r, k) => ((r.details || {})[k] || {});
const pick = (v, allowed) => (allowed.includes(v) ? v : '');

export default function PhoneUpdate({ record: r, onSave, onCancel }) {
  const rails = useMemo(() => jobOf(r).rails, [r]);
  const contacts = useMemo(() => knownContacts(r), [r]);
  const said = fieldOf(r, 'vehicle').value || '';
  const t = fieldOf(r, 'time');
  const [f, setF] = useState(() => ({
    date: fieldOf(r, 'date').value || r.delivery_date || '',
    from: pick(t.earliest || '', TIMES),
    to: t.expanded ? '' : pick(t.latest || '', TIMES),
    offloading: pick(fieldOf(r, 'offloading').value || '', ['HIAB', 'MOFFETT', 'SITE/NONE']),
    artic_access: pick(fieldOf(r, 'artic_access').value || '', ['yes', 'no']),
    rear_steer: pick(fieldOf(r, 'rear_steer').value || '', ['yes', 'no']),
    pts: pick(fieldOf(r, 'pts').value || '', ['yes', 'no']),
    vehicle: /art/i.test(said) ? 'artic' : (/rig/i.test(said) ? 'rigid' : ''),
    who: contacts.length ? '0' : 'other',
    contact_name: '',
    contact_phone: '',
    what3words: fieldOf(r, 'what3words').value || '',
    notes: '',
  }));
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const who = f.who === 'other' ? { name: f.contact_name.trim(), phone: f.contact_phone.replace(/[^\d+]/g, '') }
    : contacts[+f.who] || { name: '', phone: '' };
  const missing = [
    !f.date && 'the date', !f.from && 'the time', !f.offloading && 'offloading', !f.artic_access && 'artic access',
    !f.rear_steer && 'rear steer', rails && !f.pts && 'PTS', !who.name && "the contact's name",
    !/^\+?\d{10,13}$/.test(who.phone) && "the contact's number",
  ].filter(Boolean);

  const save = () => onSave({
    date: f.date, from: f.from, to: f.to, offloading: f.offloading, artic_access: f.artic_access,
    rear_steer: f.rear_steer, pts: rails ? f.pts : '', vehicle: f.vehicle,
    contact_name: who.name, contact_phone: who.phone, what3words: f.what3words.trim(), notes: f.notes.trim(),
  });

  const sel = (k, label, opts, blank = 'Pick…') => (
    <label className="pf-row">
      <span>{label}</span>
      <select value={f[k]} onChange={set(k)}>
        {blank !== null && <option value="">{blank}</option>}
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );

  return (
    <div className="phoneform">
      <div className="pf-head">Updated over the phone — what did they say?</div>
      {sel('date', 'Delivery date', dayOptions(f.date))}
      {sel('from', 'Delivery time', TIMES.map((x) => [x, x]))}
      {sel('to', 'Until', toOptions(f.from).map((x) => [x, x]), '+2 hours (your rule)')}
      {sel('offloading', 'Offloading', [['HIAB', 'Our HIAB'], ['MOFFETT', 'Moffett'], ['SITE/NONE', 'Site offloads it']])}
      {sel('artic_access', 'Can artics get in?', [['yes', 'Yes'], ['no', 'No']])}
      {sel('rear_steer', 'Rear steer?', [['yes', 'Yes'], ['no', 'No']])}
      {rails && sel('pts', 'PTS?', [['yes', 'Yes'], ['no', 'No']])}
      {sel('vehicle', 'Vehicle', [['rigid', '40ft rigid'], ['artic', '40ft artic']], 'Go by the weight')}
      {sel('who', 'Site contact', contacts.map((c, i) => [String(i), `${c.name || 'No name'} · ${c.phone}`]).concat([['other', 'Someone else…']]), null)}
      {f.who === 'other' && (
        <>
          <label className="pf-row"><span>Their name</span><input value={f.contact_name} onChange={set('contact_name')} /></label>
          <label className="pf-row"><span>Their number</span><input value={f.contact_phone} onChange={set('contact_phone')} inputMode="tel" /></label>
        </>
      )}
      <label className="pf-row"><span>What3Words</span><input value={f.what3words} onChange={set('what3words')} placeholder="optional" /></label>
      <label className="pf-row"><span>Anything else</span><input value={f.notes} onChange={set('notes')} placeholder="optional" /></label>
      <div className="pf-foot">
        <span className="pf-miss">{missing.length ? 'Still to pick: ' + missing.join(', ') : 'Saving puts it on the order and the CTMS to-do list.'}</span>
        <button className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn red" disabled={missing.length > 0} onClick={save}>Save</button>
      </div>
    </div>
  );
}
