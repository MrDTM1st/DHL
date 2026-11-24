// The cover request's "Rails:" line (cloud/web/src/lib/orders.js railDetails) - his ask 24/11.
//
//     node tests/rail_details.test.mjs
import assert from 'node:assert/strict';
import { railDetails } from '../cloud/web/src/lib/orders.js';

assert.deepEqual(railDetails({ product_codes: ['RAIL SHORT, 56E1, 260 GRADE, 18.288M, UNDRILLED'] }),
  ['56E1, 260 grade, 18.288m, undrilled, not Zinoco']);
assert.deepEqual(railDetails({ product_codes: ['RAIL SHORT, 56E1, ZINOCO COATED, 18.288M, UNDRILLED'] }),
  ['56E1, 18.288m, undrilled, ZINOCO coated']);
assert.deepEqual(railDetails({ product_codes: ['RAIL RAIL SHORT, 56E1, HP, ZINOCO, 23.000M, UNDRILLED'] }),
  ['56E1, hp, 23.000m, undrilled, ZINOCO coated']);
assert.deepEqual(railDetails({ product_codes: ['RAIL SHORT, 95LB BULLHEAD, 18.288M, DRILLED BOTH ENDS'] }),
  ['95lb bullhead, 18.288m, drilled both ends, not Zinoco']);
assert.deepEqual(railDetails({ product_codes: ['RAIL SHORT, 60E2, 260 GRADE, 9.144M, UNDRILLED',
  'RAIL SHORT, 60E2, 260 GRADE, 9.144M, UNDRILLED', 'RAIL SHORT, 56E1, 260 GRADE, 13.716M, UNDRILLED'] }),
  ['60E2, 260 grade, 9.144m, undrilled, not Zinoco', '56E1, 260 grade, 13.716m, undrilled, not Zinoco']);
assert.deepEqual(railDetails({ product_codes: ['CONCRETE SLEEPERS'] }), []);
assert.deepEqual(railDetails({ product_codes: ['S&C RAIL HALF SET'] }), []);
assert.deepEqual(railDetails({}), []);
console.log('rail_details: ok');
