// The Network Rail card (cloud/web/src/lib/orders.js, nr_date.py since 25/11): what needs him - held with a reason, a
// "no" the site hasn't heard, a send that failed, an ask close to its day - what's still going, and what went by
// itself lately. Made-up orders only.
//
//     node tests/nr_card.test.mjs
import assert from 'node:assert/strict';
import { nrNeedsYou, nrRecent, nrOpen, workdaysTo } from '../cloud/web/src/lib/orders.js';

const ddmmyyyy = (days) => {
  const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + days);
  return [d.getDate(), d.getMonth() + 1].map((x) => String(x).padStart(2, '0')).join('/') + '/' + d.getFullYear();
};
const stampAgo = (hours) => {
  const d = new Date(Date.now() - hours * 3600000);
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const rec = (nd) => ({ id: '9100601|' + ddmmyyyy(20), orders: ['9100601'], nr_date: { kind: 'earlier', offered: ddmmyyyy(20),
  asked: ddmmyyyy(10), state: 'sent', ...nd } });
const LIVE = { mode: 'live', why: '' };
const OFF = { mode: 'off', why: 'Auto follow-ups are off' };

let n = 0;
const t = (name, fn) => { fn(); n += 1; };

t('working days to a day: today 0, a week on 5, gone below 0', () => {
  assert.equal(workdaysTo(ddmmyyyy(0)), 0);
  assert.equal(workdaysTo(ddmmyyyy(7)), 5);
  assert.ok(workdaysTo(ddmmyyyy(-3)) < 0);
  assert.equal(workdaysTo('not a day'), null);
});

t('held, a no for the site, a failed send and a near day with no answer need him', () => {
  assert.ok(nrNeedsYou(rec({ held: { why: 'Not a clear yes or no' } }), LIVE));
  assert.ok(nrNeedsYou(rec({ state: 'not_allowed', tell_site: true }), LIVE));
  assert.ok(nrNeedsYou(rec({ state: 'to_send', send_failed: { said: 'no' } }), LIVE));
  assert.ok(nrNeedsYou(rec({ asked: ddmmyyyy(1) }), LIVE));
  assert.ok(!nrNeedsYou(rec({}), LIVE));                                   // asked, waiting, days to go: not his yet
});

t('one still to send is his only while it is not going by itself', () => {
  assert.ok(!nrNeedsYou(rec({ state: 'to_send' }), LIVE));
  assert.ok(nrNeedsYou(rec({ state: 'to_send' }), OFF));
  assert.ok(!nrNeedsYou(rec({ state: 'to_send' }), null));                 // an older home PC says nothing: as before
});

t('what went by itself shows for a couple of days, then the card lets it go', () => {
  assert.ok(nrRecent(rec({ state: 'allowed', answered_at: stampAgo(3) })));
  assert.ok(!nrRecent(rec({ state: 'allowed', answered_at: stampAgo(60) })));
  assert.ok(nrRecent(rec({ kind: 'later', sent_at: stampAgo(1) })));
  assert.ok(!nrRecent(rec({ state: 'to_send' })));
  assert.ok(!nrOpen(rec({ state: 'allowed' })) && nrOpen(rec({ state: 'to_send' })));
});

console.log(`\n${n}/${n} passed`);
