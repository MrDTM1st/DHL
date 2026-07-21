// Domain helpers, ported from the logic the original inline dashboard ran in
// the browser (region2-emailer/cloud/server.py) and kept faithful to the real
// tracker-record shape the home agent pushes:
//   { id, orders[], materials, product_codes[], to, delivery_date (dd/mm/yyyy),
//     emailed_at, chases, reply_at, ooo_at, sendoff_ready, site, worksite,
//     postcode, collection_site, collection_pc, details{}, missing[], loose_ballast }

// ONE postcode normaliser lives in geo.js (it owns the geocode cache these keys
// index). Re-exported here so existing importers don't have to change - two
// copies is exactly how cache keys drift apart and pins go missing.
import { pcNorm } from './geo.js';
export { pcNorm };

// Days from today to a dd/mm/yyyy string. null if unparseable.
export function wlDays(dd) {
  const m = String(dd || '').match(/(\d{2})\/(\d{2})\/(\d{4})/);
  if (!m) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dt = new Date(+m[3], +m[2] - 1, +m[1]);
  return Math.round((dt - today) / 86400000);
}

export function within3(dd) {
  const n = wlDays(dd);
  return n !== null && n >= 0 && n <= 3;
}

// The redesign's chosen urgency trigger: a delivery inside 3 days, or a loose
// ballast job (which always needs booking attention).
export function isUrgent(r) {
  return within3(r.delivery_date || r.date) || !!r.loose_ballast;
}

export function urgScore(r) {
  return (within3(r.delivery_date || r.date) ? 2 : 0) + (r.loose_ballast ? 1 : 0);
}

export function ordLabel(r) {
  return (r.orders || []).join(' / ');
}

// Pipeline stage 0..3 (Drafted -> Emailed -> Reply -> Sent off) from the real
// timestamp fields.
export function stageOf(r) {
  if (r.sendoff_ready) return 3;
  if (r.reply_at) return 2;
  if (r.emailed_at) return 1;
  return 0;
}

export const STAGES = ['Drafted', 'Emailed', 'Reply in', 'Sent off'];

export function statusLabel(r) {
  if (r.sendoff_ready) return 'Sent off';
  if (r.ooo_at) return 'Out of office';
  if ((r.chases || 0) > 0) return 'Chased ×' + r.chases;
  if (r.reply_at) return 'Replied';
  if (r.emailed_at) return 'Awaiting reply';
  return 'Drafted';
}

export function isAmberStatus(r) {
  return !!r.ooo_at || (r.chases || 0) > 0;
}

// Human due text from delivery_date.
export function dueText(r) {
  const n = wlDays(r.delivery_date || r.date);
  if (n === null) return r.delivery_date ? 'due ' + r.delivery_date : '';
  if (n < 0) return Math.abs(n) + 'd overdue';
  if (n === 0) return 'due today';
  if (n === 1) return 'due tomorrow';
  return 'due in ' + n + 'd';
}

// dd/mm short form for compact display.
export function dateShort(dd) {
  const m = String(dd || '').match(/(\d{2})\/(\d{2})\/(\d{4})/);
  return m ? m[1] + '/' + m[2] : String(dd || '');
}

// Detail-field helpers for the tracker's parsed delivery-detail chips.
export const DFIELDS = [
  ['date', 'Date'], ['time', 'Time'], ['offloading', 'Offload'], ['artic_access', 'Artic'],
  ['rear_steer', 'Rear steer'], ['vehicle', 'Vehicle'], ['pts', 'PTS'],
  ['what3words', 'W3W'], ['contact', 'Contact'],
];

export function detVal(k, v) {
  if (!v) return '';
  if (k === 'time') return v.earliest ? (v.latest ? v.earliest + '-' + v.latest : v.earliest) : '';
  if (k === 'contact') return [v.name, v.phone].filter(Boolean).join(' ');
  return v.value || '';
}

// What a job needs, from its materials + parsed customer details. Drives the
// haulier capability match. Ported verbatim from the original browser logic.
export function needsFor(r) {
  const need = [], d = r.details || {};
  const mats = ((r.materials || '') + ' ' + (r.product_codes || []).join(' ')).toLowerCase();
  if (/rail|sleeper|bearer|s&c|switch/.test(mats)) need.push('rail / s&c');
  if (/ballast|bag/.test(mats)) need.push('bags');
  const off = (d.offloading || {}).value || '';
  if (off === 'MOFFETT') need.push('moffett');
  else if (off === 'HIAB') need.push(((d.artic_access || {}).value === 'no') ? 'rigid hiab' : 'artic hiab');
  if (((d.rear_steer || {}).value) === 'yes') need.push('rear steer');
  if (((d.pts || {}).value) === 'yes') need.push('pts');
  return need;
}

export function milesBetween(a, b) {
  if (!a || !b) return null;
  const R = 3958.8, t = Math.PI / 180;
  const dla = (b.la - a.la) * t, dlo = (b.lo - a.lo) * t;
  const h = Math.sin(dla / 2) ** 2 + Math.cos(a.la * t) * Math.cos(b.la * t) * Math.sin(dlo / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(h)) * 10) / 10;
}

// Rank hauliers for a job. Order of approach is DHL's OWN fleet -> tier 1 ->
// tier 2; distance only breaks ties inside a band. `geo` is the postcode->
// {la,lo} cache; hauliers come from the agent-pushed panel.
//
// Distance is measured from WHICHEVER END IS NEARER - collection or delivery.
// A haulier based near the drop is just as workable as one near the pick-up
// (they can run empty to collect, or be coming back that way), so ranking only
// off the collection end hides good local options. `nearEnd` says which one it
// is, so the reason a haulier is near is never a mystery.
export function recommendFor(r, hauliers, geo) {
  const need = needsFor(r);
  const cg = geo[pcNorm(r.collection_pc || '')];
  const dg = geo[pcNorm(r.postcode || '')];
  const out = (hauliers || []).filter((h) => {
    const caps = (h.caps || []).map((c) => c.toLowerCase());
    return need.every((n) => caps.some((c) => c.includes(n)));
  }).map((h) => {
    const g = geo[pcNorm(h.pc || '')];
    const mc = g && cg ? milesBetween(cg, g) : null;
    const md = g && dg ? milesBetween(dg, g) : null;
    const both = [['collection', mc], ['delivery', md]].filter((x) => x[1] !== null);
    both.sort((a, b) => a[1] - b[1]);
    return Object.assign({}, h, {
      miles: both.length ? both[0][1] : null,
      nearEnd: both.length ? both[0][0] : null,
      milesCollection: mc, milesDelivery: md,
    });
  });
  out.forEach((h) => { h.rank = h.fleet ? 0 : (h.tier === 'tier1' ? 1 : 2); });
  out.sort((a, b) => a.rank - b.rank
    || (a.miles === null) - (b.miles === null)
    || (a.miles || 9e9) - (b.miles || 9e9));
  return { need, list: out };
}

export const RANK_TAG = ['fleet', 't1', 't2'];
export const RANK_LABEL = ['OUR FLEET', 'TIER 1', 'TIER 2'];

// ---- drive time / ETA formatting ----
export function fmtDur(seconds) {
  if (seconds == null) return null;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, '0')}m`;
}

export function metersToMiles(m) {
  return m == null ? null : Math.round((m / 1609.344) * 10) / 10;
}

// Clock time `seconds` from now, e.g. an arrival if you left this minute.
export function clockIn(seconds, from = new Date()) {
  if (seconds == null) return null;
  const t = new Date(from.getTime() + seconds * 1000);
  const same = t.toDateString() === from.toDateString();
  const hhmm = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
  return same ? hhmm : `${hhmm} +${Math.round((t - from) / 86400000) || 1}d`;
}

// The whole job as a haulier actually drives it: their base -> the collection
// (repositioning, running empty) -> the delivery. `repo` and `leg` are
// routeBetween results. Returns nulls rather than guessing when a leg is
// missing, so the UI can say "—" instead of inventing a time.
export function journeyFor(repo, leg) {
  const s = (x) => (x && x.seconds != null ? x.seconds : null);
  const m = (x) => (x && x.meters != null ? x.meters : null);
  const repoS = s(repo), legS = s(leg);
  return {
    repoSeconds: repoS, repoMiles: metersToMiles(m(repo)),
    legSeconds: legS, legMiles: metersToMiles(m(leg)),
    totalSeconds: repoS != null && legS != null ? repoS + legS : null,
    totalMiles: m(repo) != null && m(leg) != null ? metersToMiles(m(repo) + m(leg)) : null,
    estimated: !!((repo && repo.road === false) || (leg && leg.road === false)),
  };
}

