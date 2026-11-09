// The email a DTS's "Ask Order Management" button writes (cloud/web/src/lib/orders.js omAltContact).
// Made-up DTS, site and people only.
//
//     node tests/om_contact.test.mjs
import assert from 'node:assert/strict';
import { omAltContact } from '../cloud/web/src/lib/orders.js';

const R = {
  kind: 'dts', orders: ['NN0000001-1'], worksite: 'NWR - EXAMPLE MDU', postcode: 'AA1 1AA',
  delivery_date: '12/11/2026', collection_date: '11/11/2026',
  collections: [{ site: 'EXAMPLE SUPPLIER LTD', pc: 'BB2 2BB' }],
  details: { time: { earliest: '09:00', latest: '14:00' }, contact: { name: 'JANE SAMPLE', phone: '07000 000000' } },
};

{
  const o = omAltContact(R, { team: { name: 'Order Management', email: 'om@example.net' }, dts: {
    'NN0000001-1': { tried: [{ to: 'site@example.net', name: 'Site Person', at: '09/11/2026 10:15' },
                             { to: 'site@example.net', name: 'Site Person', at: '09/11/2026 10:15' }], asked: '' } } });
  assert.equal(o.to, 'om@example.net');
  assert.equal(o.subject, 'NN0000001-1 NWR - EXAMPLE MDU AA1 1AA - alternative contact needed');
  assert.match(o.message, /DTS NN0000001-1/);
  assert.match(o.message, /Delivery site: NWR - EXAMPLE MDU, AA1 1AA/);
  assert.match(o.message, /Delivery date: 12\/11\/2026 \(09:00 - 14:00\)/);
  assert.match(o.message, /Collection: EXAMPLE SUPPLIER LTD, BB2 2BB on 11\/11\/2026/);
  assert.match(o.message, /- Jane Sample, 07000 000000 \(the contact on the DTS\): called, no answer/);
  assert.match(o.message, /- Site Person <site@example.net>: emailed 09\/11\/2026 10:15, no reply/);
  assert.equal(o.message.split('emailed 09/11').length, 2, 'the same email is listed once');
  assert.match(o.message, /alternative contact for the delivery site/);
  assert.ok(!o.message.includes('—'), 'no em dashes');
}

{
  // no panel data yet: the address still known, nobody named says so plainly
  const o = omAltContact({ ...R, details: {} }, undefined);
  assert.equal(o.to, 'ordermanagement@networkrail.co.uk');
  assert.match(o.message, /\(nobody named on the DTS\)/);
  assert.match(o.message, /Delivery date: 12\/11\/2026\n/);
}

console.log('om_contact: all passed');
