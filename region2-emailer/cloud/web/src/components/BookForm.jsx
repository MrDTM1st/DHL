import { useMemo, useState } from 'react';
import { jobOf, RANK_LABEL } from '../lib/orders.js';

// The brief's Book (his design 02/11): "book with who?", the price per vehicle if they're a tier 2, and the work PC books
// it in CTMS. His press of Book it is the go-ahead for this one order. What follows the booking - the DigiHaul row for a
// _DH carrier, the site's email, off the map - follows by itself (book_run.py).

const TRAILERS = ['NR_ARTIC_FL', 'NR_60_ART_FL', 'NR_TROM_80FT', 'NR_FLAT_RIG', 'NR_R_TIP26_8', 'NR_ART_40_CT', 'NR_CS_MOF',
  'NR_TRANSIT', 'NR_7.5T', 'NR_7.5T_TAIL', 'NR_LOW_LOAD', 'NR_BULK_SKIP', 'NR_OTHER'];
// what a vehicle carries, as he has given them (31/10); no figure, no sum: he picks how many
const ARTIC_HIAB_KG = 20280;
const ARTIC_KG = 25500;
const RIGID_HIAB_KG = 10000;

const rankOf = (h) => (h.rank !== undefined ? h.rank : (h.fleet ? 0 : (h.tier === 'tier1' ? 1 : 2)));

// The trailer the job goes on: the one on the order, else his rules - rails by their length, stoneblowers on the rigid
// tipper, the rest by weight. '' when none of that says.
function defaultTrailer(r, job) {
  const said = String((((r.details || {}).vehicle) || {}).value || '').toUpperCase();
  if (TRAILERS.includes(said)) return said;
  const mats = `${r.materials || ''} ${(r.product_codes || []).join(' ')}`;
  if (/stone\s*-?\s*blower/i.test(mats)) return 'NR_R_TIP26_8';
  if (job.metres !== null && job.metres > 18.3) return 'NR_TROM_80FT';
  if (job.metres !== null && job.metres > 13.6) return 'NR_60_ART_FL';
  if (job.byWeight === 'rigid') return 'NR_FLAT_RIG';
  if (job.byWeight === 'artic' || job.rails) return 'NR_ARTIC_FL';
  return '';
}

// How many vehicles the weight fills, each to its maximum - with what it went on, or 1 and no reason when a maximum isn't known.
function defaultVehicles(r, job, trailer) {
  const hiab = ((r.details || {}).offloading || {}).value === 'HIAB';
  const max = trailer === 'NR_FLAT_RIG' ? (hiab ? RIGID_HIAB_KG : null)
    : trailer === 'NR_ARTIC_FL' ? (hiab ? ARTIC_HIAB_KG : ARTIC_KG) : null;
  if (!job.kg || !max) return { n: 1, why: '' };
  const n = Math.max(1, Math.ceil(job.kg / max));
  return { n, why: `${Math.round(job.kg).toLocaleString('en-GB')} kg at ${max.toLocaleString('en-GB')} kg a vehicle` };
}

export default function BookForm({ record: r, hauliers, recs, run, onBook, onCancel }) {
  const job = useMemo(() => jobOf(r), [r]);
  const fits = recs || [];
  const others = useMemo(() => (hauliers || []).filter((h) => !fits.some((x) => x.name === h.name)), [hauliers, fits]);
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [trailer, setTrailer] = useState(() => defaultTrailer(r, job));
  const guess = defaultVehicles(r, job, trailer);
  const [vehicles, setVehicles] = useState(null);       // null: what the weight says
  const [price, setPrice] = useState('');
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
  const book = () => onBook(r, {
    orders: r.orders || [], date: r.delivery_date, carrier: code.trim(), haulier: h.name, trailer, vehicles: n,
    ...(Number(price) > 0 ? { haulage: Number(price) } : {}),
  });

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
      <div className="pf-foot">
        <span className="pf-miss">{missing.length ? 'Still to pick: ' + missing.join(', ')
          : 'Books it in CTMS, ' + (code.toUpperCase().endsWith('_DH') ? 'writes the DigiHaul row, ' : '') + 'emails the site and takes it off the map.'}</span>
        <button className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn red" disabled={missing.length > 0} onClick={book}>Book it</button>
      </div>
    </div>
  );
}
