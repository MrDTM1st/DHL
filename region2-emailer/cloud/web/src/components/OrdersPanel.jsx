import { useState, useEffect } from 'react';
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
  const [pending, setPending] = useState('');   // '' | 'find' | 'pin'
  const [since, setSince] = useState(0);
  const [, tick] = useState(0);
  const state = (status && status.state) || '';
  const online = !(status && status.agent_online === false);
  const found = asked && state === 'found';
  const missing = asked && state === 'error' && (status.detail || '').indexOf(asked) >= 0;

  // A second-by-second re-render while we wait, so the elapsed count moves and
  // it is obvious something IS happening.
  useEffect(() => {
    if (!pending) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [pending]);

  // Clear the wait when a result for THIS search lands. The command is only
  // queued by the POST - the home PC polls for it, runs it, then reports back -
  // so the honest end of "waiting" is the report arriving, not the POST
  // returning. Clearing on the POST is what made it look like nothing happened.
  useEffect(() => {
    if (!pending) return;
    const mine = (status && status.detail ? status.detail : '').indexOf(asked) >= 0;
    if (state === 'found' || ((state === 'error' || state === 'done') && mine)) setPending('');
  }, [state, status, pending, asked]);

  const waited = pending ? Math.round((Date.now() - since) / 1000) : 0;

  // What the wait actually says. The home PC relays a live line while it works
  // ("refreshing the index", "searching Inbox - 120 spreadsheets opened"), and
  // it runs one job at a time, so a search fired while another is still going
  // is genuinely queued rather than slow. Saying which is which is the
  // difference between waiting and pressing Find again.
  const queued = state === 'queued';
  const doing = pending === 'find' ? `Looking up ${asked}` : `Pinning ${asked}`;
  const waitLine = queued ? 'Waiting for the home PC to finish another job…'
    : (state === 'running' && status && status.detail) ? status.detail : `${doing}…`;

  async function run(kind, body) {
    setPending(kind);
    setSince(Date.now());
    try {
      await command(body);
    } catch (err) {
      setPending('');
      throw err;
    }
  }
  const find = (e) => {
    e.preventDefault();
    const o = order.trim();
    if (!o) return;
    setAsked(o);
    return run('find', { action: 'order_find', order: o });
  };
  const pin = (track) => run('pin', { action: 'order_pin', order: asked, track });

  return (
    <div className="mapsearch">
      <form onSubmit={find}>
        <input value={order} onChange={(e) => setOrder(e.target.value)} disabled={!!pending}
          placeholder="Order number…" aria-label="Search an order to pin on the map" />
        <button type="submit" disabled={!!pending || !order.trim()}>
          {pending === 'find' ? 'Finding…' : 'Find'}
        </button>
      </form>

      {pending && (
        <div className="mapsearch-wait" role="status" aria-live="polite">
          <span className="spin" />
          <div>
            <span>{waitLine}</span>
            {waited > 1 && <span className="el"> · {waited}s</span>}
            {!online && <div className="warn">Home PC is offline — this will run when it reconnects.</div>}
            {online && queued && waited > 6 && (
              <div className="warn">The home PC runs one job at a time, so this starts as soon as the one in front finishes.</div>
            )}
          </div>
        </div>
      )}

      {!pending && missing && <div className="mapsearch-msg">{status.detail}</div>}
      {!pending && found && (
        <div className="mapsearch-res">
          <pre>{(status.output || '').slice(0, 1200)}</pre>
          <div className="mapsearch-btns">
            <button onClick={() => pin(false)}>Pin only</button>
            <button onClick={() => pin(true)}>Pin + track</button>
          </div>
        </div>
      )}
      {!pending && asked && state === 'done' && (status.detail || '').indexOf('pinned') >= 0 && (
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
                  {o.kind === 'dts' && <span className="ubadge" style={{ marginLeft: 6, background: 'var(--ink2)' }}>DTS</span>}
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
