import { useEffect, useMemo, useState } from 'react';
import { geoCache } from '../lib/geo.js';
import { RANK_LABEL, ordLabel } from '../lib/orders.js';
import { TRAILERS, rankOf, queueOf, propose, proposalGaps, jobFor } from '../lib/bookQueue.js';
import { ctmsBookBatch, ctmsStatus } from '../api.js';

// Book approved (his 03/11): every order strictly ready to book, what the desk proposes for each - who with, the
// trailer, how many vehicles, the price - and his tick. Only ticked orders go, one after another on the work PC, each
// through the booking journal so none is ever booked twice. His tick is also his word that the haulier has agreed:
// nothing on file says a haulier said yes, only who was asked.

const STATE_WORDS = { waiting: 'waiting', running: 'booking now', booked: 'booked', 'not booked': 'not booked', skipped: 'skipped' };

export default function BookQueue({ records, panel }) {
  const hauliers = (panel && panel.hauliers) || [];
  const geo = geoCache();
  const { ready, held } = useMemo(() => queueOf(records, {
    hauliers, geo, todo: (panel && panel.ctms_todo) || [], bookings: (panel && panel.bookings) || [],
  }), [records, hauliers, geo, panel]);
  const [edits, setEdits] = useState({});          // id -> what he changed from the proposal
  const [ticked, setTicked] = useState({});        // id -> true
  const [run, setRun] = useState(null);            // the batch as the dashboard reports it
  const [err, setErr] = useState('');
  const [showHeld, setShowHeld] = useState(false);

  const asks = (panel && panel.asks) || {};
  const rows = ready.map(({ r, fits }) => {
    const p = { ...propose(r, fits, asks), ...(edits[r.id] || {}) };
    const h = hauliers.find((x) => x.name === p.name) || fits.find((x) => x.name === p.name);
    p.rank = h ? rankOf(h) : null;
    return { r, fits, p, gaps: proposalGaps(p) };
  });
  const going = run && run.state === 'running';
  const chosen = rows.filter((x) => ticked[x.r.id] && !x.gaps.length);

  // follow the batch until the home PC says it ended
  useEffect(() => {
    if (!run || run.state !== 'running') return undefined;
    let live = true;
    const t = setInterval(async () => {
      try {
        const st = await ctmsStatus(false);
        const b = st.book_run;
        if (live && b && b.id === run.id) setRun(b);
      } catch { /* the next poll */ }
    }, 2500);
    return () => { live = false; clearInterval(t); };
  }, [run]);

  if (!rows.length && !held.length && !run) return null;

  const set = (id, change) => setEdits((e) => ({ ...e, [id]: { ...(e[id] || {}), ...change } }));
  const pickHaulier = (x, name) => {
    const h = x.fits.concat(hauliers).find((y) => y.name === name);
    set(x.r.id, { name, code: h ? (h.book || h.ctms || '') : '', price: '' });
  };
  const book = async () => {
    const list = chosen.map((x) => `${ordLabel(x.r)} ${x.r.delivery_date}: ${x.p.name} (${x.p.code}), ${x.p.trailer}`
      + (x.p.vehicles > 1 ? `, ${x.p.vehicles} vehicles` : '') + (Number(x.p.price) > 0 ? `, £${x.p.price}` : ''));
    if (!window.confirm(`Book ${chosen.length === 1 ? 'this one' : `these ${chosen.length}, one after another,`} in CTMS?\n\n${list.join('\n')}\n\n`
      + 'Each one is emailed to the site after. It stops at the first one CTMS needs you to look at.')) return;
    setErr('');
    try {
      const { run: id } = await ctmsBookBatch(chosen.map((x) => jobFor(x.r, x.p)));
      setRun({ id, state: 'running', jobs: chosen.map((x) => ({ orders: x.r.orders, carrier: x.p.code, state: 'waiting' })) });
      setTicked({});
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="card noaddress bookq">
      <div className="noaddress-head">
        <h3>{rows.length === 1 ? '1 order' : rows.length + ' orders'} ready to book</h3>
        <span className="noaddress-why">Nothing missing, nothing amber, nothing owed on the CTMS to-do. Check what&rsquo;s
          proposed, tick the ones the haulier has agreed to, and book them in one go.</span>
      </div>

      {run && (
        <div className="noaddress-row">
          <div className="noaddress-what">
            <div className="noaddress-order">{going ? 'Booking on the work PC…' : (run.ok ? 'Batch finished' : 'Batch stopped')}</div>
            {(run.jobs || []).map((j, i) => (
              <div className="noaddress-said" key={i}>
                <span className={'bookq-state ' + String(j.state).replace(' ', '-')}>{STATE_WORDS[j.state] || j.state}</span>
                {' '}{(j.orders || []).join(' / ')} with {j.carrier}
                {(j.manifests || []).length ? ': ' + j.manifests.join(', ') : ''}{j.said && j.state !== 'booked' ? ' · ' + j.said : ''}
              </div>
            ))}
            {!going && run.said && <div className="noaddress-said">{run.said}</div>}
          </div>
          {!going && <div className="noaddress-fix"><button className="btn mini" onClick={() => setRun(null)}>Close</button></div>}
        </div>
      )}

      {!going && rows.map((x) => {
        const { r, fits, p, gaps } = x;
        const others = hauliers.filter((h) => !h.parcel && !fits.some((f) => f.name === h.name));
        return (
          <div className="bookq-row" key={r.id}>
            <div className="noaddress-order">
              {ordLabel(r)}
              <span className="noaddress-when">{r.delivery_date}{r.kind === 'adhoc' ? ' · ad hoc' : r.kind === 'dts' ? ' · DTS' : ''}</span>
            </div>
            <div className="noaddress-site">{[r.site || r.worksite, r.postcode].filter(Boolean).join(' ')}
              {p.why ? <span className="noaddress-said"> · proposed: {p.why}</span> : null}</div>
            <div className="bookq-pick">
              <label>Haulier
                <select value={p.name} onChange={(e) => pickHaulier(x, e.target.value)}>
                  <option value="">Pick…</option>
                  <optgroup label="Fit this job">
                    {fits.map((h) => <option key={h.name} value={h.name}>{h.name} ({RANK_LABEL[rankOf(h)]})</option>)}
                  </optgroup>
                  <optgroup label="Everyone else">
                    {others.map((h) => <option key={h.name} value={h.name}>{h.name} ({RANK_LABEL[rankOf(h)]})</option>)}
                  </optgroup>
                </select>
              </label>
              <label>CTMS code
                <input className="mono" value={p.code} onChange={(e) => set(r.id, { code: e.target.value })} placeholder="not on the list" />
              </label>
              <label>Trailer
                <select value={p.trailer} onChange={(e) => set(r.id, { trailer: e.target.value })}>
                  <option value="">Pick…</option>
                  {TRAILERS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label>Vehicles
                <select value={p.vehicles} onChange={(e) => set(r.id, { vehicles: Number(e.target.value) })}>
                  {Array.from({ length: Math.max(12, p.vehicles) }, (_, i) => i + 1).map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </label>
              {p.rank === 0 ? (
                <label>Price a vehicle<input value="0, our fleet" disabled /></label>
              ) : (
                <label>Price a vehicle
                  <input inputMode="decimal" value={p.price} onChange={(e) => set(r.id, { price: e.target.value })}
                    placeholder={p.rank === 1 ? 'off the matrix' : 'ex VAT, the agreed quote'} />
                </label>
              )}
              {(r.kind === 'adhoc' || r.kind === 'dts') && (
                <label>Email the site at
                  <input type="email" value={p.siteTo || ''} onChange={(e) => set(r.id, { siteTo: e.target.value })}
                    placeholder="if it isn't on the request" />
                </label>
              )}
            </div>
            <label className="bookq-ok">
              <input type="checkbox" disabled={gaps.length > 0} checked={!!ticked[r.id] && !gaps.length}
                onChange={(e) => setTicked((t) => ({ ...t, [r.id]: e.target.checked }))} />
              {gaps.length ? 'Still to pick: ' + gaps.join(', ')
                : `Agreed with ${p.name}: book it` + (p.vehicles > 1 && p.vehiclesWhy ? ` (${p.vehiclesWhy})` : '')}
            </label>
          </div>
        );
      })}

      {!going && (
        <div className="bookq-foot">
          <span className="noaddress-why">
            {err || (held.length ? (
              <button className="btn mini" onClick={() => setShowHeld((v) => !v)}>
                {showHeld ? 'Hide' : 'Show'} {held.length} not ready
              </button>
            ) : null)}
          </span>
          {rows.length > 0 && (
            <button className="btn red" disabled={!chosen.length} onClick={book}>
              Book {chosen.length || ''} approved
            </button>
          )}
        </div>
      )}
      {showHeld && !going && held.slice(0, 40).map(({ r, why }) => (
        <div className="noaddress-row" key={r.id}>
          <div className="noaddress-what">
            <div className="noaddress-order">{ordLabel(r)}<span className="noaddress-when">{r.delivery_date}</span></div>
            <div className="noaddress-said">{why.join('; ')}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
