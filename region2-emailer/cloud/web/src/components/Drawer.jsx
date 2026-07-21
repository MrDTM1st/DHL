import { useState, useEffect } from 'react';
import { I } from '../icons.jsx';
import {
  ordLabel, statusLabel, dueText, isUrgent, within3, needsFor, recommendFor,
  milesBetween, detVal, RANK_TAG, RANK_LABEL, pcNorm,
} from '../lib/orders.js';
import { geocode, geoCache } from '../lib/geo.js';

// Full order brief: the job, the run distance, delivery details, and who to
// ring — hauliers ranked by fit + distance from the collection end, exactly as
// the original dashboard did, over the real agent-pushed haulier list.
export default function Drawer({ record: r, hauliers, onClose, onCall, onBookedCall }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    const pcs = [r.collection_pc, r.postcode].concat((hauliers || []).map((h) => h.pc)).filter(Boolean);
    geocode(pcs).then(() => { if (live) setTick((n) => n + 1); });
    return () => { live = false; };
  }, [r.id, hauliers]);

  const geo = geoCache();
  const d = r.details || {};
  const v = (k) => detVal(k, d[k]);
  const { need, list } = recommendFor(r, hauliers, geo);
  const recs = list.slice(0, 4);
  const cg = geo[pcNorm(r.collection_pc || '')], dg = geo[pcNorm(r.postcode || '')];
  const run = milesBetween(cg, dg);

  const rows = [
    ['Status', statusLabel(r)],
    ['Delivery', dueText(r)],
    ['Material', r.materials],
    ['Time', v('time')],
    ['Collection', [r.collection_site, r.collection_pc].filter(Boolean).join(' ')],
    ['Delivery to', [r.worksite || r.site, r.postcode].filter(Boolean).join(' · ')],
    ['Site contact', v('contact')],
    ['Assigned to', r.to],
    ['Offloading', v('offloading')],
    ['Artic access', v('artic_access')],
    ['Rear steer', v('rear_steer')],
    ['PTS', v('pts')],
    ['What3Words', v('what3words')],
    ['Chases', r.chases ? String(r.chases) : ''],
  ].filter((x) => x[1]);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-h">
          <button className="x" onClick={onClose}>×</button>
          <h2>{ordLabel(r)}</h2>
          <div className="ds">
            {[r.worksite || r.site, r.postcode].filter(Boolean).join(' · ')}
            {r.loose_ballast && <span className="lbadge" style={{ marginLeft: 8 }}>LOOSE BALLAST</span>}
            {within3(r.delivery_date) && <span className="ubadge" style={{ marginLeft: 6 }}>≤3 DAYS</span>}
          </div>
        </div>
        <div className="drawer-b">
          <dl className="kv">
            {rows.map((x, i) => (
              <div key={i} style={{ display: 'contents' }}>
                <dt>{x[0]}</dt>
                <dd style={x[0] === 'Delivery' && isUrgent(r) ? { color: 'var(--red)' } : null}>{x[1]}</dd>
              </div>
            ))}
          </dl>
          {run !== null && (
            <div className="statusdetail" style={{ fontSize: 12.5, marginBottom: 14 }}>
              Run: <b>{r.collection_site || 'collection'}</b> → <b>{r.worksite || r.site || 'site'}</b> · <b>{run} mi</b>
            </div>
          )}

          <div className="lbl" style={{ margin: '6px 0 8px' }}>This job needs</div>
          <div className="needchips">
            {need.length ? need.map((n, i) => <span className="needchip" key={i}>{n}</span>)
              : <span className="needchip" style={{ background: 'var(--seg)', color: 'var(--muted)', borderColor: 'var(--line2)' }}>general haulage</span>}
          </div>

          <div className="lbl" style={{ margin: '6px 0 10px' }}>
            Who to contact <span style={{ color: 'var(--faint)', fontWeight: 600 }}>· ranked by fit & distance</span>
          </div>
          {recs.length ? recs.map((h, i) => (
            <div className={'hrec' + (i === 0 ? ' best' : '')} key={h.name}>
              <div className="hm mono">{h.miles !== null ? h.miles + ' mi' : '—'}</div>
              <div className="hn">
                <b>{h.name}</b>
                <span className={'htag ' + RANK_TAG[h.rank]}>{RANK_LABEL[h.rank]}</span>
                <div>{[h.loc, (h.caps || []).join(', ')].filter(Boolean).join(' · ')}</div>
              </div>
              <button className="callbtn" onClick={() => onCall(h)}>{I.phone} Call</button>
            </div>
          )) : (
            <div className="statusdetail" style={{ fontSize: 12.5, color: 'var(--muted)' }}>
              No haulier in the list matches {need.join(', ') || 'this job'}.
            </div>
          )}

          {onBookedCall && (
            <button className="btn block" style={{ marginTop: 16 }} onClick={() => onBookedCall(r)}>
              Mark booked over the phone
            </button>
          )}
        </div>
      </div>
    </>
  );
}
