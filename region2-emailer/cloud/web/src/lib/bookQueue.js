// Book approved (his 03/11: "it proposes, I approve"; strictly ready only). Which orders are ready to book with
// nothing left to doubt, and what the desk proposes for each: who with, the trailer, how many vehicles, the price. The
// home PC checks readiness again before it books (book_run.not_ready): the tracker may have moved since this was drawn.
import { jobOf, isReady, recommendFor } from './orders.js';

export const TRAILERS = ['NR_ARTIC_FL', 'NR_60_ART_FL', 'NR_TROM_80FT', 'NR_FLAT_RIG', 'NR_R_TIP26_8', 'NR_ART_40_CT',
  'NR_CS_MOF', 'NR_TRANSIT', 'NR_7.5T', 'NR_7.5T_TAIL', 'NR_LOW_LOAD', 'NR_BULK_SKIP', 'NR_OTHER'];
// what a vehicle carries, as he has given them (31/10); no figure, no sum: he picks how many
const ARTIC_HIAB_KG = 20280;
const ARTIC_KG = 25500;
const RIGID_HIAB_KG = 10000;
const TIPPER_KG = 21000;    // NR_R_TIP26_8 (his 04/11)

export const rankOf = (h) => (h.rank !== undefined ? h.rank : (h.fleet ? 0 : (h.tier === 'tier1' ? 1 : 2)));

// The trailer the job goes on: the one on the order, else his rules - rails by their length, stoneblowers and loose ballast
// on the rigid tipper, the rest by weight. '' when none of that says.
export function defaultTrailer(r, job) {
  const said = String((((r.details || {}).vehicle) || {}).value || '').toUpperCase();
  if (TRAILERS.includes(said)) return said;
  const mats = `${r.materials || ''} ${(r.product_codes || []).join(' ')}`;
  if (/stone\s*-?\s*blower|\bloose\b|100500\/001/i.test(mats)) return 'NR_R_TIP26_8';
  if (job.metres !== null && job.metres > 18.3) return 'NR_TROM_80FT';
  if (job.metres !== null && job.metres > 13.6) return 'NR_60_ART_FL';
  if (job.byWeight === 'rigid') return 'NR_FLAT_RIG';
  if (job.byWeight === 'artic' || job.rails) return 'NR_ARTIC_FL';
  return '';
}

// How many vehicles the weight fills, each to its maximum - with what it went on, or 1 and no reason when a maximum
// isn't known.
export function defaultVehicles(r, job, trailer) {
  const hiab = ((r.details || {}).offloading || {}).value === 'HIAB';
  const max = trailer === 'NR_FLAT_RIG' ? (hiab ? RIGID_HIAB_KG : null)
    : trailer === 'NR_ARTIC_FL' ? (hiab ? ARTIC_HIAB_KG : ARTIC_KG)
    : trailer === 'NR_R_TIP26_8' ? TIPPER_KG : null;
  if (!job.kg || !max) return { n: 1, why: '' };
  const n = Math.max(1, Math.ceil(job.kg / max));
  return { n, why: `${Math.round(job.kg).toLocaleString('en-GB')} kg at ${max.toLocaleString('en-GB')} kg a vehicle` };
}

const baseOf = (o) => String(o || '').trim().toUpperCase().replace(/[-_/][A-Z0-9]{1,3}$/, '');
const journalKey = (orders, date) => [...new Set((orders || []).map((o) => String(o).replace(/\s+/g, '').toUpperCase())
  .filter(Boolean))].sort().join('|') + '@' + String(date || '').trim();

// Why this order isn't strictly ready - [] when it is: the site has answered with nothing missing (or the form / a phone
// call / CTMS's own Veh Type says it all), nothing amber, nothing the CTMS to-do must put on first, not a booking
// already being finished, and someone on the list who fits it.
export function notReady(r, { todo = [], bookings = [], fits = null } = {}) {
  const why = [];
  if (!r || !(r.orders || []).length) return ['no order number'];
  if (r.kind === 'pinned' || r.kind === 'collection') return ['not a delivery the desk books'];
  if (!r.delivery_date) why.push('no delivery date');
  if (!isReady(r)) {
    if (!r.reply_at) why.push('the site hasn\'t replied');
    else why.push('still missing: ' + (r.missing || []).join(', '));
  }
  const amber = Object.entries(r.details || {})
    .filter(([, v]) => v && typeof v === 'object' && v.confidence === 'amber').map(([k]) => k);
  if (amber.length) why.push('not confirmed yet: ' + amber.sort().join(', '));
  const mine = new Set((r.orders || []).map(baseOf));
  const owed = (todo || []).filter((i) => (i.kind === 'update' || i.kind === 'booking')
    && (i.orders || []).some((o) => mine.has(baseOf(o))));
  if (owed.length) why.push('on the CTMS to-do first: ' + (owed[0].what || owed[0].kind));
  const key = journalKey(r.orders, r.delivery_date);
  if ((bookings || []).some((b) => b.key === key)) why.push('a booking of it is being finished: see Bookings');
  if (fits && !fits.length) why.push('nobody on the list fits it');
  return why;
}

// What the desk proposes: the haulier already asked about this job if they fit it (most recently asked first: that's
// who he has lined up), else the first who fits - our fleet, tier 1, tier 2, nearest first. The price: our fleet 0,
// tier 1 off CTMS's matrix (blank), tier 2 left for him to type - never guessed.
export function propose(r, fits, asks = {}) {
  const job = jobOf(r);
  const asked = [];
  (r.orders || []).forEach((o) => ((asks || {})[String(o)] || []).forEach((a) => asked.push(a)));
  asked.sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')));
  const lined = asked.map((a) => fits.find((h) => h.name === a.name)).find(Boolean);
  const h = lined || fits[0] || null;
  const trailer = defaultTrailer(r, job);
  const veh = defaultVehicles(r, job, trailer);
  const rank = h ? rankOf(h) : null;
  return {
    name: h ? h.name : '', code: h ? (h.book || h.ctms || '') : '', rank, trailer,
    vehicles: veh.n, vehiclesWhy: veh.why, price: '',
    why: lined ? 'asked already' : h ? 'first who fits' : '',
  };
}

// What's still to settle before a proposal may go - [] when it may.
export function proposalGaps(p) {
  return [!p.name && 'who', p.name && !String(p.code || '').trim() && 'their CTMS code', !p.trailer && 'the trailer',
    p.rank === 2 && !(Number(p.price) > 0) && 'the price'].filter(Boolean);
}

// The job as /api/ctms/book_batch takes it.
export function jobFor(r, p) {
  return {
    record: r.id, orders: r.orders || [], date: r.delivery_date, carrier: String(p.code || '').trim(), haulier: p.name,
    trailer: p.trailer, vehicles: Number(p.vehicles) || 1,
    ...(Number(p.price) > 0 ? { haulage: Number(p.price) } : {}),
    ...(String(p.siteTo || '').trim() ? { site_to: String(p.siteTo).trim() } : {}),
  };
}

// The ready orders and the rest, each with its fits - soonest first.
export function queueOf(records, { hauliers = [], geo = {}, todo = [], bookings = [] } = {}) {
  const ready = [];
  const held = [];
  (records || []).forEach((r) => {
    if (r.kind === 'pinned' || r.kind === 'collection') return;
    const fits = recommendFor(r, hauliers, geo).list;
    const why = notReady(r, { todo, bookings, fits });
    (why.length ? held : ready).push({ r, fits, why });
  });
  const when = (x) => {
    const m = String(x.r.delivery_date || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    return m ? `${m[3]}${m[2]}${m[1]}` : '99999999';
  };
  ready.sort((a, b) => when(a).localeCompare(when(b)));
  return { ready, held };
}
