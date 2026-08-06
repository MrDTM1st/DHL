import { useState } from 'react';
import { I } from '../icons.jsx';
import { ordLabel, isUrgent, within3, dateShort, recommendFor, parcelPassFor } from '../lib/orders.js';
import { geoCache } from '../lib/geo.js';
import { command } from '../api.js';

/* Search an order and put it on the map.
   For orders emailed BY HAND: the toolkit never saw the email, so the order is
   in neither the tracker nor the ad hocs and the map does not know about it.
   Find looks it up and sends nothing; the pin buttons appear only once
   something has actually been found.

   This lives INSIDE the orders card rather than floating over the map. Both
   were absolutely positioned near the top-left, so the card - which has the
   higher z-index - simply sat on top of the search box. In the card it is in
   normal flow, so they cannot collide however tall the result grows. */
function OrderSearch({ status }) {
  const [order, setOrder] = useState('');
  const [asked, setAsked] = useState('');       // what we last searched for
  const [busy, setBusy] = useState(false);
  const state = (status && status.state) || '';
  const found = asked && state === 'found';
  const missing = asked && state === 'error' && (status.detail || '').indexOf(asked) >= 0;

  async function find(e) {
    e.preventDefault();
    const o = order.trim();
    if (!o) return;
    setBusy(true); setAsked(o);
    try { await command({ action: 'order_find', order: o }); } finally { setBusy(false); }
  }
  async function pin(track) {
    setBusy(true);
    try { await command({ action: 'order_pin', order: asked, track }); } finally { setBusy(false); }
  }

  return (
    <div className="mapsearch">
      <form onSubmit={find}>
        <input value={order} onChange={(e) => setOrder(e.target.value)}
          placeholder="Order number…" aria-label="Search an order to pin on the map" />
        <button type="submit" disabled={busy || !order.trim()}>Find</button>
      </form>
      {asked && state === 'running' && <div className="mapsearch-msg">Looking up {asked}…</div>}
      {missing && <div className="mapsearch-msg">{status.detail}</div>}
      {found && (
        <div className="mapsearch-res">
          <pre>{(status.output || '').slice(0, 1200)}</pre>
          <div className="mapsearch-btns">
            <button onClick={() => pin(false)} disabled={busy}>Pin only</button>
            <button onClick={() => pin(true)} disabled={busy}>Pin + track</button>
          </div>
        </div>
      )}
      {asked && state === 'done' && (status.detail || '').indexOf('pinned') >= 0 && (
        <div className="mapsearch-msg">{status.detail}</div>
      )}
    </div>
  );
}

// Left-hand panel on the map: every tracked order with its recommended haulier.
// Tap a row to open the full brief. Recommendations use the same real ranking
// as the drawer.
export default function OrdersPanel({ records, hauliers, onSelect, selectedId, status }) {
  const geo = geoCache();
  const list = [...records].sort((a, b) => (isUrgent(b) - isUrgent(a)) || 0);
  const urgent = records.filter(isUrgent).length;
  return (
    <div className="uploadpanel" style={{ left: 16, right: 'auto' }}>
      <div className="up-head">
        <div className="t">{I.track}Orders &amp; hauliers</div>
        <div className="s">{records.length} tracked · {urgent} urgent. Tap an order for the full brief.</div>
      </div>
      <OrderSearch status={status} />
      <div className="parsed" style={{ maxHeight: '62vh', padding: '6px 8px 8px' }}>
        {!list.length && (
          <div style={{ padding: '22px 12px', textAlign: 'center', color: 'var(--muted)', fontSize: 12.5 }}>
            Nothing tracked yet.
          </div>
        )}
        {list.map((o) => {
          const { list: recs } = recommendFor(o, hauliers, geo);
          const best = recs[0];
          const pp = parcelPassFor(o);
          return (
            <div className={'orow' + (selectedId === o.id ? ' sel' : '')} key={o.id} onClick={() => onSelect(o)}>
              <span className="pdot2" style={isUrgent(o)
                ? { background: 'var(--red)', boxShadow: '0 0 0 3px var(--red-t)' }
                : { background: 'var(--faint)' }} />
              <div className="pm">
                <div className="o mono">
                  {ordLabel(o)} <span style={{ color: 'var(--faint)', fontWeight: 600 }}>· {o.worksite || o.site || ''}</span>
                  {o.kind === 'adhoc' && <span className="ubadge" style={{ marginLeft: 6, background: 'var(--ink2)' }}>AD HOC</span>}
                  {o.kind === 'pinned' && <span className="ubadge" style={{ marginLeft: 6, background: 'var(--ink2)' }}>BY HAND</span>}
                </div>
                <div className="s">
                  {pp && pp.ok ? <>Rec: <b style={{ color: 'var(--goink, #18804a)' }}>Parcel Pass</b> · small load</>
                    : best ? <>Rec: <b style={{ color: 'var(--ink2)' }}>{best.name}</b>{best.miles !== null ? ' · ' + best.miles + ' mi' : ''}</>
                    : 'No matching haulier yet'}
                </div>
              </div>
              <div className="pd" style={isUrgent(o) ? { color: 'var(--red)' } : null}>
                {within3(o.delivery_date) ? '≤3d' : dateShort(o.delivery_date)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
