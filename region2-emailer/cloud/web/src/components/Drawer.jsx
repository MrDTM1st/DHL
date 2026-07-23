import { useState, useEffect } from 'react';
import { I } from '../icons.jsx';
import {
  ordLabel, statusLabel, dueText, isUrgent, within3, needsFor, recommendFor,
  milesBetween, detVal, RANK_TAG, RANK_LABEL, pcNorm,
  fmtDur, metersToMiles, journeyFor,
} from '../lib/orders.js';
import { geocode, geoCache, routeBetween } from '../lib/geo.js';

// Full order brief: the job, the run distance, delivery details, and who to
// ring — hauliers ranked by fit + distance from the collection end, exactly as
// the original dashboard did, over the real agent-pushed haulier list.
export default function Drawer({ record: r, hauliers, onClose, onCall, onBookedCall,
  pickedHaulier, onPickHaulier }) {
  const [, setTick] = useState(0);
  const [leg, setLeg] = useState(null);     // collection -> delivery
  const [repo, setRepo] = useState(null);   // picked haulier's base -> collection
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
  // The FULL list of hauliers that fit this job - fleet -> tier 1 -> tier 2,
  // closest to furthest within each band (Delali: "give me everyone that fits",
  // not a top few). The drawer body scrolls, so a long list costs nothing.
  const recs = list;
  // The top pick is timed straight away rather than waiting for a tap - the
  // first thing you want on opening a brief is "who, and how long".
  const auto = recs[0] || null;
  const activeHaulier = pickedHaulier || auto;
  const cg = geo[pcNorm(r.collection_pc || '')], dg = geo[pcNorm(r.postcode || '')];
  const run = milesBetween(cg, dg);

  // Time the job as the ACTIVE haulier would drive it: their base to the
  // collection (running empty), then the delivery leg. Runs for the auto-picked
  // haulier too, so the ETA is on screen before you touch anything.
  // Depend on stable PRIMITIVES, never on the geo objects themselves: geoCache()
  // hands back a fresh object every render, so an object dep re-fires this
  // effect forever, and each run resets repo to null before the fetch lands -
  // the timing never settles and the row reads "timing their run…" for ever.
  const cKey = pcNorm(r.collection_pc || '');
  const dKey = pcNorm(r.postcode || '');
  const hKey = activeHaulier ? pcNorm(activeHaulier.pc || '') : '';
  const cReady = !!geo[cKey];
  const dReady = !!geo[dKey];
  const hReady = !!geo[hKey];

  // The delivery leg's real drive time, routed on roads. Re-fetched per order.
  useEffect(() => {
    let live = true;
    setLeg(null);
    const cg = geo[cKey], dg = geo[dKey];
    if (cg && dg) routeBetween(cg, dg).then((x) => { if (live) setLeg(x); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r.id, cKey, dKey, cReady, dReady]);

  useEffect(() => {
    let live = true;
    setRepo(null);
    const cgeo = geo[cKey], hg = geo[hKey];
    if (cgeo && hg) routeBetween(hg, cgeo).then((x) => { if (live) setRepo(x); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r.id, cKey, hKey, cReady, hReady]);

  const journey = journeyFor(repo, leg);

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
      {/* No scrim: the brief sits BESIDE the map, not over a dimmed one - the
          whole point is reading the job while looking at where it is. */}
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
            <div className="runeta">
              <div className="runline">
                <b>{r.collection_site || 'collection'}</b> → <b>{r.worksite || r.site || 'site'}</b>
              </div>
              <div className="runstat">
                <span>{journey.legMiles != null ? journey.legMiles : run} mi</span>
                <span className="dot">·</span>
                <span className="drive">{leg ? (fmtDur(journey.legSeconds) || '—') : 'timing…'} drive</span>
                {leg && leg.road === false && <span className="approx">straight-line estimate</span>}
              </div>
            </div>
          )}

          <div className="lbl" style={{ margin: '6px 0 8px' }}>This job needs</div>
          <div className="needchips">
            {need.length ? need.map((n, i) => <span className="needchip" key={i}>{n}</span>)
              : <span className="needchip" style={{ background: 'var(--seg)', color: 'var(--muted)', borderColor: 'var(--line2)' }}>general haulage</span>}
          </div>

          <div className="lbl" style={{ margin: '6px 0 10px' }}>
            Who to contact — {recs.length} fit this job <span style={{ color: 'var(--faint)', fontWeight: 600 }}>
              · timed from the top pick — tap another to compare</span>
          </div>
          {recs.length ? recs.map((h, i) => {
            const picked = activeHaulier && activeHaulier.name === h.name;
            return (
            <div className={'hrec' + (i === 0 ? ' best' : '') + (picked ? ' picked' : '')} key={h.name}
              onClick={() => onPickHaulier && onPickHaulier(picked ? null : h)}
              role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' && onPickHaulier) onPickHaulier(picked ? null : h); }}>
              <div className="hm mono">
                {h.miles !== null ? h.miles + ' mi' : '—'}
                {h.nearEnd && <span className="hend">from {h.nearEnd}</span>}
              </div>
              <div className="hn">
                <b>{h.name}</b>
                <span className={'htag ' + RANK_TAG[h.rank]}>{RANK_LABEL[h.rank]}</span>
                {h.closerThanAbove && <span className="htag near">CLOSER</span>}
                <div>{[h.loc, (h.caps || []).join(', ')].filter(Boolean).join(' · ')}</div>
                {picked && (
                  <div className="hjourney">
                    {repo === null ? 'timing their run…' : (
                      <>
                        <span>base → collection <b>{fmtDur(journey.repoSeconds) || '—'}</b>
                          {journey.repoMiles != null && ` (${journey.repoMiles} mi)`}</span>
                        <span>then delivery <b>{fmtDur(journey.legSeconds) || '—'}</b></span>
                        <span className="tot">total driving <b>{fmtDur(journey.totalSeconds) || '—'}</b>
                          {journey.totalMiles != null && ` · ${journey.totalMiles} mi`}</span>
                        {journey.estimated && <span className="approx">includes a straight-line estimate</span>}
                      </>
                    )}
                  </div>
                )}
              </div>
              <button className="callbtn" onClick={(e) => { e.stopPropagation(); onCall(h); }}>{I.phone} Call</button>
            </div>
            );
          }) : (
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
