import { useState } from 'react';
import { ctmsBook } from '../api.js';

// Bookings still being finished, or waiting on him (book_journal.py, 03/11). A booking made in CTMS is never made again
// from here: Retry is a press of Book, which finishes only what's left (the DigiHaul row, the site's email...). Clear and
// Done by hand are his word that he has looked in CTMS or done the step himself.

const STATE = { asking: 'Waiting for the work PC', booked: 'Booked, finishing', half: 'Left short in CTMS', unknown: 'Not known' };

export default function BookingsCard({ rows, onCommand }) {
  const [said, setSaid] = useState({});
  if (!rows || !rows.length) return null;
  const note = (key, text) => setSaid((s) => ({ ...s, [key]: text }));

  const retry = async (b) => {
    note(b.key, 'Retrying on the work PC…');
    try {
      await ctmsBook(b.job);
      note(b.key, 'Sent: what is left is being done. This card updates when it ends.');
    } catch (e) {
      note(b.key, e.message);
    }
  };
  const clear = (b, step) => {
    const what = step ? `Mark the ${(b.todo.find((t) => t.step === step) || {}).label || step} as done by hand?`
      : b.state === 'booked' ? `Mark everything left on ${b.orders.join(' / ')} as done by hand?`
        : `Have you looked in CTMS for ${b.orders.join(' / ')}? Clear means the next press of Book books it if CTMS has nothing.`;
    if (!window.confirm(what)) return;
    onCommand({ action: 'book_clear', data: { key: b.key, ...(step ? { step } : {}) } });
    note(b.key, 'Noted.');
  };

  return (
    <div className="card noaddress">
      <div className="noaddress-head">
        <h3>{rows.length === 1 ? '1 booking' : rows.length + ' bookings'} not finished</h3>
        <span className="noaddress-why">Nothing here is booked twice. Retry finishes what&rsquo;s left; the home PC also
          tries a failed email again by itself a few minutes on.</span>
      </div>
      {rows.map((b) => {
        const mine = b.todo.filter((t) => !t.auto);
        const canRetry = b.state === 'booked' && b.todo.length > 0;
        return (
          <div className="noaddress-row" key={b.key}>
            <div className="noaddress-what">
              <div className="noaddress-order">
                {b.orders.join(' / ')}
                <span className={'noaddress-when' + (b.state === 'booked' ? '' : ' soon')}>
                  {b.date} · {STATE[b.state] || b.state}
                </span>
              </div>
              <div className="noaddress-site">
                {[b.haulier || b.carrier, b.manifests.join(', ')].filter(Boolean).join(' · ')}
              </div>
              <div className="noaddress-said">{b.need}</div>
              {b.todo.length > 0 && (
                <div className="noaddress-said">
                  Left: {b.todo.map((t) => t.label + (t.said ? ` (${t.said})` : '') + (t.auto ? ', trying again' : '')).join('; ')}
                </div>
              )}
              {said[b.key] && <div className="noaddress-said">{said[b.key]}</div>}
            </div>
            <div className="noaddress-fix">
              {canRetry && <button className="btn mini go" onClick={() => retry(b)}>Retry</button>}
              {b.state === 'booked' && mine.map((t) => (
                <button key={t.step} className="btn mini" onClick={() => clear(b, t.step)}>{t.label}: done by hand</button>
              ))}
              {b.state !== 'booked' && <button className="btn mini" onClick={() => clear(b)}>Clear</button>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
