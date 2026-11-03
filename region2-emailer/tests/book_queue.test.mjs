// Book approved (cloud/web/src/lib/bookQueue.js, 03/11): only strictly ready orders are offered, the haulier already
// asked is proposed before the first who fits, a tier 2 can't go without its price. Made-up orders and hauliers only.
//
//     node tests/book_queue.test.mjs
import assert from 'node:assert/strict';
import { notReady, propose, proposalGaps, jobFor, queueOf } from '../cloud/web/src/lib/bookQueue.js';

const ddmmyyyy = (days) => {
  const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + days);
  return [d.getDate(), d.getMonth() + 1].map((n) => String(n).padStart(2, '0')).join('/') + '/' + d.getFullYear();
};
const weekday = (() => { for (let k = 14; ; k += 1) { const d = new Date(); d.setDate(d.getDate() + k); if (d.getDay() % 6) return k; } })();
const DAY = ddmmyyyy(weekday);
const rec = (extra = {}) => ({ id: '9000001|' + DAY, orders: ['9000001'], delivery_date: DAY, reply_at: 'x', missing: [],
  materials: 'Bags of ballast', postcode: 'LE10 1AA', details: { time: { confidence: 'high' } }, ...extra });
const H = (name, tier, extra = {}) => ({ name, tier, caps: [], pc: '', no_go: [], ctms: name.toUpperCase().replace(/\W/g, '') + '_DH', ...extra });

let n = 0;
const t = (name, fn) => { fn(); n += 1; };

t('a replied order with nothing missing or amber is ready', () => {
  assert.deepEqual(notReady(rec(), { fits: [H('A', 'tier1')] }), []);
});
t('amber, missing, no reply and the CTMS to-do each keep it off', () => {
  assert.match(notReady(rec({ details: { time: { confidence: 'amber' } } }))[0], /not confirmed yet: time/);
  assert.match(notReady(rec({ missing: ['pts'] }))[0], /still missing: pts/);
  assert.match(notReady(rec({ reply_at: '' }))[0], /hasn't replied/);
  assert.match(notReady(rec(), { todo: [{ kind: 'update', orders: ['9000001'], what: 'Update 9000001' }] })[0], /CTMS to-do/);
  assert.deepEqual(notReady(rec(), { todo: [{ kind: 'note', orders: ['9000001'] }] }), []);   // a note can follow
});
t('a booking already being finished, or nobody who fits, keeps it off', () => {
  assert.match(notReady(rec(), { bookings: [{ key: '9000001@' + DAY }] })[0], /being finished/);
  assert.match(notReady(rec(), { fits: [] })[0], /nobody on the list fits/);
});
t('an ad hoc comes ready on its form; a pin never is', () => {
  assert.deepEqual(notReady({ id: 'a', kind: 'adhoc', orders: ['AH1-2-3'], delivery_date: DAY }), []);
  assert.ok(notReady({ id: 'p', kind: 'pinned', orders: ['1'] }).length);
});
t('the haulier already asked is proposed ahead of the first who fits', () => {
  const fits = [H('Fleet', '', { fleet: true, rank: 0 }), H('Asked Co', 'tier2', { rank: 2 })];
  assert.equal(propose(rec(), fits, {}).name, 'Fleet');
  const p = propose(rec(), fits, { 9000001: [{ name: 'Asked Co', at: '2026-11-02' }] });
  assert.equal(p.name, 'Asked Co');
  assert.equal(p.why, 'asked already');
  assert.equal(p.price, '');                      // never guessed
});
t('a tier 2 needs its price, our fleet and tier 1 do not', () => {
  assert.deepEqual(proposalGaps({ name: 'X', code: 'X_DH', trailer: 'NR_ARTIC_FL', rank: 2, price: '' }), ['the price']);
  assert.deepEqual(proposalGaps({ name: 'X', code: 'X_DH', trailer: 'NR_ARTIC_FL', rank: 2, price: '450' }), []);
  assert.deepEqual(proposalGaps({ name: 'X', code: 'X_DH', trailer: 'NR_ARTIC_FL', rank: 1, price: '' }), []);
  assert.deepEqual(proposalGaps({ name: 'X', code: '', trailer: '', rank: 0 }), ['their CTMS code', 'the trailer']);
});
t('the job sent carries the price only when one was typed', () => {
  const j = jobFor(rec(), { name: 'X', code: ' X_DH ', trailer: 'NR_ARTIC_FL', vehicles: 2, price: '' });
  assert.deepEqual(j, { record: rec().id, orders: ['9000001'], date: DAY, carrier: 'X_DH', haulier: 'X', trailer: 'NR_ARTIC_FL', vehicles: 2 });
  assert.equal(jobFor(rec(), { name: 'X', code: 'X', trailer: 'T', vehicles: 1, price: '450' }).haulage, 450);
});
t('the queue puts the soonest first and leaves pins out', () => {
  const soon = rec({ id: 's', orders: ['9000002'], delivery_date: ddmmyyyy(weekday - 7 > 0 ? weekday - 7 : 1) });
  const q = queueOf([rec(), soon, { id: 'p', kind: 'pinned', orders: ['1'] }], { hauliers: [H('Any', 'tier1', { caps: ['Rigid Hiab'] })] });
  assert.deepEqual(q.ready.map((x) => x.r.id), ['s', rec().id]);
  assert.equal(q.held.length, 0);
});
console.log(`${n} passed`);
