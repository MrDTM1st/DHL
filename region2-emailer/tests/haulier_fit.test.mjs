// Who the map lists for a job (cloud/web/src/lib/orders.js): only hauliers who
// can carry the material, matched on the contact sheet's exact capability
// names, our fleet left off what it cannot take, and the orders in date order.
// Made-up hauliers and orders only.
//
//     node tests/haulier_fit.test.mjs
import assert from 'node:assert/strict';
import { recommendFor, needsFor, byDeliveryDate } from '../cloud/web/src/lib/orders.js';

const H = (name, tier, caps, extra = {}) => ({ name, tier, caps, pc: '', no_go: [], ...extra });
const HAULIERS = [
  H('Our Fleet', '', ['Rail / S&C', 'PTS', 'Rigid Hiab', 'Artic Hiab', 'Artic Flat', '60ft Flat'],
    { fleet: true, avoid_nw: true }),
  H('Tipper Only Ltd', 'tier1', ['Rigid Tipper', 'Artic Tipper']),
  H('Rigid Hiab Co', 'tier2', ['Rigid Hiab', 'Short Flat', 'Bags']),
  H('Artic Hiab Co', 'tier1', ['Artic Hiab', 'Artic Flat', 'Bags', 'Rear Steer', 'PTS']),
  H('Curtain Co', 'tier2', ['Artic Curtain']),
  H('Log Grab Co', 'tier2', ['Recycling', 'Log Grab', 'Bulker']),
  H('Rail Co', 'tier1', ['Rail / S&C', 'Artic Hiab', '60ft Flat', 'Trombone (80ft +)', 'Rear Steer']),
  H('Van Co', 'tier2', ['Vans', '7.5T']),
  H('Wheelset Co', 'tier2', ['Wheelsets', 'Artic Hiab', 'Artic Flat']),
  { name: 'Parcel Service', parcel: true, caps: [], pc: '' },
];

const ddmmyyyy = (days) => {
  const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + days);
  return [d.getDate(), d.getMonth() + 1].map((n) => String(n).padStart(2, '0')).join('/') + '/' + d.getFullYear();
};
// a weekday a fortnight or so out, so no test lands on a weekend by accident
const weekday = (() => { for (let k = 14; ; k += 1) { const d = new Date(); d.setDate(d.getDate() + k); if (d.getDay() % 6) return k; } })();
const job = (materials, details = {}, extra = {}) => ({
  id: materials, orders: ['9000001'], materials, product_codes: [], delivery_date: ddmmyyyy(weekday),
  postcode: '', collections: [], details, ...extra,
});
const names = (r) => recommendFor(r, HAULIERS, {}).list.map((h) => h.name);
const labels = (r) => needsFor(r).map((n) => n.label);
let n = 0;
const test = (name, fn) => { fn(); n += 1; console.log('ok    ' + name); };

test('bagged ballast never goes to a tipper-only or log-grab firm', () => {
  const got = names(job('72x ballast'));
  assert.ok(!got.includes('Tipper Only Ltd') && !got.includes('Log Grab Co') && !got.includes('Curtain Co'), got.join());
});

test('over 20 bags is artic hiabs - 20 or fewer, either size', () => {
  assert.deepEqual(labels(job('72x ballast')), ['artic hiab']);
  assert.ok(!names(job('72x ballast')).includes('Rigid Hiab Co'));
  assert.deepEqual(labels(job('12x ballast')), ['rigid or artic hiab']);
  assert.ok(names(job('12x ballast')).includes('Rigid Hiab Co'));
  assert.deepEqual(labels(job('15x ballast, 7x aggregate')), ['artic hiab']);   // 22 bags
});

test('loose ballast and stoneblower stone are tipped', () => {
  assert.deepEqual(names(job('loose ballast')), ['Tipper Only Ltd']);
  assert.deepEqual(names(job('21x stoneblower')), ['Tipper Only Ltd']);
  assert.deepEqual(labels(job('21x stoneblower', { vehicle: { value: 'NR_R_TIP26_8' } })), ['rigid tipper']);
});

test('sleepers want a hiab - or any flatbed when the site offloads them', () => {
  assert.deepEqual(labels(job('27x sleepers')), ['rigid or artic hiab']);
  const site = names(job('27x sleepers', { offloading: { value: 'SITE/NONE' } }));
  assert.ok(site.includes('Rigid Hiab Co') && !site.includes('Tipper Only Ltd') && !site.includes('Curtain Co'));
});

test('a sleeper line naming the rail it is for is not a rail job', () => {
  const r = job('20x sleepers', {}, { product_codes: ['SLEEPER COMPOSITE, BASEPLATE FOR INCLINED CEN56 RAIL', 'GUARD RAIL SLEEPER'] });
  assert.ok(!labels(r).includes('rail / S&C'), labels(r).join());
});

test('rails: a 60ft rail keeps our fleet, a longer one needs a trombone and leaves it off', () => {
  const short = job('1x rails', {}, { product_codes: ['RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED'] });
  assert.deepEqual(labels(short), ['rail / S&C', '60ft flat']);
  assert.deepEqual(names(short), ['Our Fleet', 'Rail Co']);
  const long = job('1x rails', {}, { product_codes: ['RAIL LONG, 60E2, 36M'] });
  assert.deepEqual(labels(long), ['rail / S&C', 'trombone (80ft+)']);
  assert.deepEqual(names(long), ['Rail Co']);
});

test('our fleet is left off night and weekend work, and says why', () => {
  const night = job('12x sleepers', { time: { earliest: '22:00', latest: '00:00' } });
  const res = recommendFor(night, HAULIERS, {});
  assert.ok(!res.list.some((h) => h.fleet));
  assert.deepEqual(res.leftOff, [{ name: 'Our Fleet', why: 'night work' }]);
});

test('a rigid never gets rear steer; ballast never gets PTS', () => {
  assert.ok(!labels(job('12x sleepers', { rear_steer: { value: 'yes' }, artic_access: { value: 'no' } })).includes('rear steer'));
  assert.ok(labels(job('12x sleepers', { rear_steer: { value: 'yes' } })).includes('rear steer'));
  assert.ok(!labels(job('12x ballast', { pts: { value: 'yes' } })).includes('PTS'));
});

test('vehicle codes name the sheet\'s own vehicles', () => {
  assert.deepEqual(names(job('1x pallet', { vehicle: { value: 'NR_TRANSIT' } })), ['Van Co']);
  assert.deepEqual(names(job('5x pallet', { vehicle: { value: 'NR_7.5T_TAIL' } })), ['Van Co']);
  assert.deepEqual(labels(job('2x half set switches', { vehicle: { value: 'NR_TROM_80ft' } })), ['rail / S&C', 'trombone (80ft+)']);
  assert.deepEqual(labels(job('2x wheelsets', { offloading: { value: 'HIAB' }, vehicle: { value: 'NR_ARTIC_FL' } })),
    ['wheelsets', 'artic hiab']);
  assert.deepEqual(labels(job('1x pallet', {}, { weight: '800kg - 7.5 tonne luton with tail lift required' })), ['van or 7.5t']);
});

test('a job with nothing to go on still never lists a tipper-only firm', () => {
  const got = names(job('1x modules'));
  assert.ok(!got.includes('Tipper Only Ltd') && !got.includes('Log Grab Co') && got.includes('Curtain Co'), got.join());
});

test('a haulier who works one patch is listed only for drops inside it', () => {
  const pool = [...HAULIERS,
    H('Patch Co', 'tier1', ['Artic Hiab', 'Bags'], { only: ['SE', 'CB', 'PE15'], only_scope: 'delivery' }),
    H('Scot Co', 'tier1', ['Artic Hiab', 'Bags'], { only: ['G', 'ML', 'EH'], only_scope: 'delivery' }),
    H('Both Ends Co', 'tier1', ['Artic Hiab', 'Bags'], { only: ['SE', 'DN'] })];
  const at = (pc, extra = {}) => recommendFor(job('72x ballast', {}, { postcode: pc, ...extra }), pool, {}).list.map((h) => h.name);
  assert.ok(at('SE18 6AA').includes('Patch Co'));
  assert.ok(at('CB7 4AA').includes('Patch Co'));     // a whole area
  assert.ok(at('PE15 8AA').includes('Patch Co'));    // one district of a big area...
  assert.ok(!at('PE25 1AA').includes('Patch Co'));   // ...and not the rest of it
  assert.ok(!at('NG10 5AA').includes('Patch Co') && !at('NG10 5AA').includes('Scot Co'));
  assert.ok(at('ML11 8AA').includes('Scot Co') && !at('ML11 8AA').includes('Patch Co'));
  // the delivery end decides: a pick-up up north for a drop in the patch is fine...
  assert.ok(at('SE18 6AA', { collections: [{ pc: 'DN16 1AA' }] }).includes('Patch Co'));
  // ...unless the patch covers both ends
  assert.ok(at('SE18 6AA', { collections: [{ pc: 'DN16 1AA' }] }).includes('Both Ends Co'));
  assert.ok(!at('SE18 6AA', { collections: [{ pc: 'NG10 1AA' }] }).includes('Both Ends Co'));
  // a job with no delivery postcode yet rules nobody out
  assert.ok(at('').includes('Patch Co') && at('').includes('Scot Co'));
});

test('a firm one capability short but nearer than everyone who fits is named, with what it lacks', () => {
  const pool = [
    H('Far Fit Co', 'tier1', ['Artic Hiab', 'Rear Steer'], { pc: 'AA1 1AA' }),
    H('Near Short Co', 'tier1', ['Artic Hiab'], { pc: 'BB1 1BB' }),        // no rear steer
    H('Near Two Short Co', 'tier2', ['Vans'], { pc: 'BB1 1BC' }),          // no hiab, no rear steer
    H('Far Short Co', 'tier2', ['Artic Hiab'], { pc: 'CC1 1CC' }),         // short, and further than the fit
  ];
  const geo = { 'AA1 1AA': { la: 54.0, lo: -2.0 }, 'BB1 1BB': { la: 52.61, lo: -1.0 },
    'BB1 1BC': { la: 52.61, lo: -1.0 }, 'CC1 1CC': { la: 55.5, lo: -2.0 }, 'DD1 1DD': { la: 52.6, lo: -1.0 } };
  const r = job('60x sleepers', { offloading: { value: 'HIAB' }, rear_steer: { value: 'yes' } }, { postcode: 'DD1 1DD' });
  const res = recommendFor(r, pool, geo);
  assert.deepEqual(res.list.map((h) => h.name), ['Far Fit Co']);
  assert.deepEqual(res.nearMiss.map((x) => [x.name, x.missing, x.rank, x.nearEnd]),
    [['Near Short Co', 'rear steer', 1, 'delivery']]);
  // nobody fits: the nearest firms one short are still named
  const none = recommendFor(r, pool.slice(1), geo);
  assert.deepEqual(none.list, []);
  assert.deepEqual(none.nearMiss.map((x) => x.name), ['Near Short Co', 'Far Short Co']);
  // no distances yet: nothing is "near"
  assert.deepEqual(recommendFor(r, pool, {}).nearMiss, []);
  // a one-need job: lacking its only need is no fit at all, not a near miss
  const oneNeed = job('60x sleepers', { offloading: { value: 'HIAB' } }, { postcode: 'DD1 1DD' });
  assert.deepEqual(recommendFor(oneNeed, pool.slice(2), geo).nearMiss, []);
});

test('orders run soonest first, then no date, then past ones most recent first', () => {
  const rs = [10, -3, 2, null, -30, 0].map((d, i) => ({ id: String(i), orders: ['900000' + i],
    delivery_date: d === null ? '' : ddmmyyyy(d) }));
  assert.deepEqual(byDeliveryDate(rs).map((r) => r.id), ['5', '2', '0', '3', '1', '4']);
});

console.log(`\n${n}/${n} passed`);
