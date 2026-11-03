import { useMemo, useState } from 'react';
import { jobOf, RANK_LABEL } from '../lib/orders.js';
import { TRAILERS, rankOf, defaultTrailer, defaultVehicles, propose, notReady } from '../lib/bookQueue.js';

// The brief's Book (his design 02/11): "book with who?", the price per vehicle if they're a tier 2, and the work PC books
// it in CTMS. His press of Book it is the go-ahead for this one order. What follows the booking - the DigiHaul row for a
// _DH carrier, the site's email, off the map - follows by itself (book_run.py).

// Book approved lives here too now (his 03/11: "integrate it into the map's original booking thing ... it kind of just
// looks cluttered"): the form opens on what the desk proposes - the haulier already asked about the job, else the first
// who fits - and Add to approved puts it on the order list's Book approved bar, for several to go one after another.
// Only a strictly ready order can be approved; Book it, his own press, still goes on any.
export default function BookForm({ record: r, hauliers, recs, run, onBook, onCancel, asks, todo, bookings, approved,
  onApprove, onUnapprove }) {
  const job = useMemo(() => jobOf(r), [r]);
  const fits = recs || [];
  const others = useMemo(() => (hauliers || []).filter((h) => !fits.some((x) => x.name === h.name)), [hauliers, fits]);
  const proposal = useMemo(() => propose(r, fits, asks || {}), [r, fits, asks]);
  const why = useMemo(() => notReady(r, { todo: todo || [], bookings: bookings || [], fits }), [r, todo, bookings, fits]);
  const [name, setName] = useState(proposal.name);
  const [code, setCode] = useState(proposal.code);
  const [trailer, setTrailer] = useState(() => proposal.trailer || defaultTrailer(r, job));
  const guess = defaultVehicles(r, job, trailer);
  const [vehicles, setVehicles] = useState(null);       // null: what the weight says
  const [price, setPrice] = useState('');
  const [siteTo, setSiteTo] = useState('');
  const oneOff = r.kind === 'adhoc' || r.kind === 'dts';
  const contactName = (((r.details || {}).contact) || {}).name;
  const h = fits.concat(others).find((x) => x.name === name);
  const rank = h ? rankOf(h) : null;
  const n = vehicles === null ? guess.n : vehicles;
  const going = run && run.state === 'running';

  const pick = (e) => {
    const v = e.target.value;
    const next = fits.concat(others).find((x) => x.name === v);
    setName(v);
    setCode(next ? (next.book || next.ctms || '') : '');
    setPrice('');
  };
  const needPrice = rank === 2;
  const missing = [!h && 'who', h && !code.trim() && 'their CTMS code', !trailer && 'the trailer',
    needPrice && !(Number(price) > 0) && 'the price'].filter(Boolean);
  const jobNow = () => ({
    orders: r.orders || [], date: r.delivery_date, carrier: code.trim(), haulier: h.name, trailer, vehicles: n,
    ...(Number(price) > 0 ? { haulage: Number(price) } : {}),
    ...(siteTo.trim() ? { site_to: siteTo.trim() } : {}),
  });
  const book = () => onBook(r, jobNow());
  const approve = () => onApprove && onApprove(r, { ...jobNow(), record: r.id });

  if (going || (run && run.state === 'done')) {
    return (
      <div className="phoneform">
        <div className="pf-head">{going ? 'Booking on the work PC…' : (run.ok ? 'Booked' : 'Not booked')}</div>
        <div className="pf-said">{going ? `With ${run.carrier || code}. Leave CTMS to it: this takes about a minute.` : run.said}</div>
        {!going && (
          <div className="pf-foot"><button className="btn" onClick={onCancel}>Close</button></div>
        )}
      </div>
    );
  }
  return (
    <div className="phoneform">
      <div className="pf-head">Book {(r.orders || []).join(' / ')} with who?</div>
      {proposal.name && name === proposal.name && (
        <div className="pf-note">Proposed: {proposal.name} ({proposal.why}). Change anything below.</div>
      )}
      {why.length > 0 && (
        <div className="pf-note">Not strictly ready, so it can&rsquo;t go on the approved list: {why.join('; ')}.
          Book it still books it.</div>
      )}
      <label className="pf-row">
        <span>Haulier</span>
        <select value={name} onChange={pick}>
          <option value="">Pick…</option>
          {fits.length > 0 && (
            <optgroup label="Fit this job">
              {fits.map((x) => <option key={x.name} value={x.name}>{x.name} ({RANK_LABEL[rankOf(x)]})</option>)}
            </optgroup>
          )}
          <optgroup label="Everyone else">
            {others.map((x) => <option key={x.name} value={x.name}>{x.name}{x.parcel ? '' : ` (${RANK_LABEL[rankOf(x)]})`}</option>)}
          </optgroup>
        </select>
      </label>
      {h && (
        <label className="pf-row">
          <span>CTMS code</span>
          <input className="mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="not on the contact list" />
        </label>
      )}
      <label className="pf-row">
        <span>Trailer</span>
        <select value={trailer} onChange={(e) => setTrailer(e.target.value)}>
          <option value="">Pick…</option>
          {TRAILERS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>
      <label className="pf-row">
        <span>Vehicles</span>
        <select value={n} onChange={(e) => setVehicles(Number(e.target.value))}>
          {Array.from({ length: Math.max(12, n) }, (_, i) => i + 1).map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
      {n > 1 && (
        <div className="pf-note">
          {guess.why && vehicles === null ? `${guess.why}. ` : ''}One line gets split equally, and CTMS shares the weight out.
          Unequal loads aren't built in yet: split those by hand first and I'll book each part.
        </div>
      )}
      {h && (rank === 0 ? (
        <div className="pf-note">Our own fleet: the haulage stays 0.</div>
      ) : (
        <label className="pf-row">
          <span>Price a vehicle</span>
          <input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)}
            placeholder={rank === 1 ? 'off the matrix (leave blank)' : 'ex VAT, the agreed quote'} />
        </label>
      ))}
      {oneOff && (
        <label className="pf-row">
          <span>Email the site at</span>
          <input type="email" value={siteTo} onChange={(e) => setSiteTo(e.target.value)}
            placeholder={`${contactName || 'the contact'}'s address, if it isn't on the request`} />
        </label>
      )}
      <div className="pf-foot">
        <span className="pf-miss">{missing.length ? 'Still to pick: ' + missing.join(', ')
          : 'Books it in CTMS, ' + (code.toUpperCase().endsWith('_DH') ? 'writes the DigiHaul row, ' : '') + 'emails the site and takes it off the map.'}</span>
        <button className="btn" onClick={onCancel}>Cancel</button>
        {onApprove && (approved ? (
          <button className="btn" onClick={() => onUnapprove(r.id)} title="It's on the order list's Book approved bar">
            Approved · take it off
          </button>
        ) : (
          <button className="btn" disabled={missing.length > 0 || why.length > 0} onClick={approve}
            title="Onto the order list's Book approved bar: booked with the others, one after another">
            Add to approved
          </button>
        ))}
        <button className="btn red" disabled={missing.length > 0} onClick={book}>Book it</button>
      </div>
    </div>
  );
}
