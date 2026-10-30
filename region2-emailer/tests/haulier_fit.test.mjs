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

test('orders run soonest first, then no date, then past ones most recent first', () => {
  const rs = [10, -3, 2, null, -30, 0].map((d, i) => ({ id: String(i), orders: ['900000' + i],
    delivery_date: d === null ? '' : ddmmyyyy(d) }));
  assert.deepEqual(byDeliveryDate(rs).map((r) => r.id), ['5', '2', '0', '3', '1', '4']);
});

console.log(`\n${n}/${n} passed`);
