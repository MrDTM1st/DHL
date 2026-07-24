import { I } from '../icons.jsx';
import { ordLabel, isUrgent, within3, dateShort, recommendFor, parcelPassFor } from '../lib/orders.js';
import { geoCache } from '../lib/geo.js';

// Left-hand panel on the map: every tracked order with its recommended haulier.
// Tap a row to open the full brief. Recommendations use the same real ranking
// as the drawer.
export default function OrdersPanel({ records, hauliers, onSelect, selectedId }) {
  const geo = geoCache();
  const list = [...records].sort((a, b) => (isUrgent(b) - isUrgent(a)) || 0);
  const urgent = records.filter(isUrgent).length;
  return (
    <div className="uploadpanel" style={{ left: 16, right: 'auto' }}>
      <div className="up-head">
        <div className="t">{I.track}Orders &amp; hauliers</div>
        <div className="s">{records.length} tracked · {urgent} urgent. Tap an order for the full brief.</div>
      </div>
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
