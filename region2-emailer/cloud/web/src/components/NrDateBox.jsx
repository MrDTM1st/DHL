import { useState, useEffect } from 'react';
import { dateShort, stamp, nrOpen, nrNeedsYou, nrRecent, workdaysTo } from '../lib/orders.js';

// The Network Rail team email when a site asks for another day than we offered (his rule 09/11, nr_date.py):
// an EARLIER day waits for the team's yes (is it allowed, will the stock be ready) - the order stays put till then;
// a day in a LATER week is moved, and the team is told so nobody chases the old day.
// Since 25/11 ("could you also make that automatic? I don't want to be manually doing that") the desk sends it by
// itself in working hours and reads their yes or no off their reply. What it can't be sure of is held for him here,
// with their words; the buttons are still there to send now, change the email, or answer for them.
// a home PC on older code says nothing (auto null): the card is the by-hand one it always was
const live = (auto) => !!auto && auto.mode === 'live';

function by(n) {
  if (n.sent_by === 'auto') return ' (by itself)';
  if (n.sent_by === 'by hand') return ' (you, outside the desk)';
  return '';
}

function quote(a) {
  if (!a || !a.said) return '';
  return `"${a.said}"`;
}

function headline(r, n, auto) {
  const team = n.team || 'Network Rail';
  const was = dateShort(n.offered), asked = dateShort(n.asked);
  // his 25/11 rule: the day it would be collected against the stock's availability (the extract's collection date)
  const col = n.collect ? dateShort(n.collect) : '', av = n.available ? dateShort(n.available) : '';
  const ans = n.answer || {};
  const who = ans.who || team;
  const read = n.answered_by === 'auto' ? ', read off their reply' : '';
  const goes = live(auto) && !n.held ? ' It goes by itself in working hours.' : '';
  if (n.superseded_by) {
    return `Not needed any more: the site's day changed to ${dateShort(n.superseded_by)}.`
      + (n.sent_at ? ` ${team} were emailed ${stamp(n.sent_at)} about ${asked}.` : '');
  }
  if (n.kind === 'earlier') {
    if (n.state === 'to_send' && col && av) return `The site asked for ${asked}: it would be collected ${col}, before the ${av} the stock is available from. ${team} are asked if that's allowed and the stock will be ready - ${was === asked ? 'nothing goes into CTMS' : 'the order stays on ' + was} until they say yes.${goes}`;
    if (n.state === 'to_send') return `The site asked for ${asked}, earlier than the ${was} we offered. ${team} are asked if it's allowed and the stock will be ready - the order stays on ${was} until they say yes.${goes}`;
    if (n.state === 'sent') return `Asked ${team} ${stamp(n.sent_at)}${by(n)} about ${col && av ? `collecting on ${col} (available ${av}) for ${asked}` : asked} - waiting for their answer${live(auto) ? ', which is read by itself' : ''}. The order stays on ${was}.`;
    if (n.state === 'allowed') return `${who} said yes ${stamp(n.answered_at)}${read}${ans.said ? ': ' + quote(ans) : ''} - moved to ${asked}. The CTMS to-do types the new day (your next Run, or Book does it first).`;
    if (n.state === 'not_allowed') return `${who} said no ${stamp(n.answered_at)}${read}${ans.said ? ': ' + quote(ans) : ''} - it stays on ${was}.`;
    if (n.state === 'dismissed') return `No Network Rail email (your call) - moved to ${asked}.`;
  } else {
    if (n.state === 'to_send' && col && av) return `Moved to ${asked}: collected ${col}, later than the ${av} it is available from. ${team} get a heads-up, so nobody chases a collection on ${av} that didn't happen.${goes}`;
    if (n.state === 'to_send') return `Moved to ${asked} from ${was} (a later week). ${team} are told so nobody chases the ${was} delivery.${goes}`;
    if (n.state === 'sent' && col && av) return `Told ${team} ${stamp(n.sent_at)}${by(n)} it will be collected ${col}, later than its ${av} availability.` + (ans.verdict === 'ack' ? ` ${who} said thanks.` : '');
    if (n.state === 'sent') return `Told ${team} ${stamp(n.sent_at)}${by(n)} it now delivers on ${asked}.` + (ans.verdict === 'ack' ? ` ${who} said thanks.` : '');
    if (n.state === 'dismissed') return 'No Network Rail email (your call).';
  }
  return '';
}

export default function NrDateBox({ r, onCommand, compact = false, auto = null }) {
  const n = r.nr_date || null;
  const [open, setOpen] = useState(false);
  const fresh = () => ({ to: (n && n.to) || '', cc: (n && n.cc) || '', subject: (n && n.subject) || '',
    message: (n && n.message) || '' });
  const [draft, setDraft] = useState(fresh);
  useEffect(() => { setDraft(fresh()); setOpen(false); }, [r.id, n && n.state, n && n.at]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!n || !headline(r, n, auto)) return null;
  if (compact && !nrOpen(r) && !nrNeedsYou(r) && !nrRecent(r)) return null;
  const say = (data) => onCommand && onCommand({ action: 'nr_date', data: { rid: r.id, ...data } });
  const edit = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const send = () => {
    if (!draft.to.trim() || !draft.message.trim()) return;
    say({ do: 'send', ...draft });
    setOpen(false);
  };
  const answer = (yes) => {
    const q = yes ? `Network Rail said YES: move ${(r.orders || []).join(' / ')} to ${n.asked}?`
      : `Network Rail said NO: keep ${(r.orders || []).join(' / ')} on ${n.offered}?`;
    if (window.confirm(q)) say({ do: yes ? 'yes' : 'no' });
  };
  const dismiss = () => {
    const q = n.kind === 'earlier'
      ? `No email to Network Rail? The order moves to ${n.asked} without their OK.`
      : 'No email to Network Rail about this move?';
    if (window.confirm(q)) say({ do: 'dismiss' });
  };
  const held = n.held || null;
  const waiting = nrOpen(r);
  const askOpen = n.state === 'sent' && n.kind === 'earlier';
  const days = askOpen ? workdaysTo(n.asked) : null;
  const late = askOpen && !held && days !== null && days <= 2;
  const need = nrNeedsYou(r, auto);
  return (
    <div className={'nrdate' + (waiting ? ' open' : '') + (need ? ' need' : '')}>
      <div className="nrdate-h">
        <span className="nrdate-tag">{n.kind === 'earlier' ? 'Earlier day asked' : 'Later week'}</span>
        <span className="nrdate-said">{headline(r, n, auto)}</span>
      </div>
      {n.state === 'to_send' && auto && !live(auto) && !held && (
        <div className="nrdate-auto">Not going by itself: {auto.why || 'automatic sending is off'} - press Email to send it.</div>
      )}
      {held && (
        <div className="nrdate-held">
          <div className="nrdate-why">Held for you: {held.why}</div>
          {held.said && (
            <div className="nrdate-quote">
              {(held.who || held.from || 'They')} {stamp(held.at)}: &ldquo;{held.said}&rdquo;
              {held.subject ? <span className="nrdate-subj"> ({held.subject})</span> : null}
            </div>
          )}
        </div>
      )}
      {n.send_failed && n.state === 'to_send' && (
        <div className="nrdate-why">Couldn't send {stamp(n.send_failed.at)}: {n.send_failed.said} - it tries again.</div>
      )}
      {late && (
        <div className="nrdate-why">{days <= 0 ? `${dateShort(n.asked)} is here` : `${dateShort(n.asked)} is ${days} working day${days === 1 ? '' : 's'} away`} and {n.team || 'Network Rail'} haven't answered - worth a call?</div>
      )}
      {n.tell_site && (
        <div className="nrdate-held">
          <div className="nrdate-why">Tell the site: it stays on {dateShort(n.offered)} - they asked for {dateShort(n.asked)}.</div>
          <div className="nrdate-acts">
            <button className="btn mini go" onClick={() => say({ do: 'told' })}>Told them</button>
          </div>
        </div>
      )}
      {n.state === 'to_send' && (
        <div className="nrdate-acts">
          <button className={'btn mini' + (open ? ' red' : ' go')} onClick={() => setOpen((v) => !v)}>
            {open ? 'Close' : (live(auto) && !held ? 'Send now / change it' : 'Email ' + (n.team || 'Network Rail'))}
          </button>
          <button className="btn mini" onClick={dismiss}>No email needed</button>
        </div>
      )}
      {askOpen && (
        <div className="nrdate-acts">
          <button className={'btn mini' + (held || late ? ' go' : '')} onClick={() => answer(true)}>They said yes - move to {dateShort(n.asked)}</button>
          <button className="btn mini" onClick={() => answer(false)}>They said no - keep {dateShort(n.offered)}</button>
          {held && held.eid && <button className="btn mini" onClick={() => say({ do: 'seen' })}>Keep waiting</button>}
        </div>
      )}
      {held && !askOpen && n.state !== 'to_send' && (
        <div className="nrdate-acts">
          <button className="btn mini go" onClick={() => say({ do: 'seen' })}>Seen</button>
        </div>
      )}
      {open && (
        <div className="hcompose">
          {!n.to && (
            <div className="nrdate-who">No Network Rail team is known for this material. Who does it go to? Type their address below.</div>
          )}
          <label>To<input value={draft.to} onChange={edit('to')} placeholder="The Network Rail team's address" /></label>
          <label>Cc<input value={draft.cc} onChange={edit('cc')} /></label>
          <label>Subject<input value={draft.subject} onChange={edit('subject')} /></label>
          <label>Message<textarea rows={10} value={draft.message} onChange={edit('message')} /></label>
          <div className="hcompose-foot">
            <span className="hint-sig">
              {n.reply_eid ? "the site's email (the whole trail) goes underneath; signature & QR are added"
                : 'signature & QR are added automatically'}
            </span>
            <button className="btn mini" onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn mini red" disabled={!draft.to.trim() || !draft.message.trim()} onClick={send}>Send</button>
          </div>
        </div>
      )}
    </div>
  );
}

// The Dashboard's card: every order whose Network Rail date change needs him (held, or the site to tell), is still
// going (to send, or waiting on their answer), or went by itself in the last couple of days - so he sees what
// happened without pressing anything, and what's held for him and why.
export function NrDateCard({ records, onCommand, auto = null }) {
  const rows = (records || []).filter((r) => r.nr_date && (nrOpen(r) || nrNeedsYou(r, auto) || nrRecent(r)));
  if (!rows.length) return null;
  const need = rows.filter((r) => nrNeedsYou(r, auto));
  const order = (r) => (nrNeedsYou(r, auto) ? 0 : nrOpen(r) ? 1 : 2);
  const sorted = rows.slice().sort((a, b) => order(a) - order(b));
  const said = !auto
    ? 'A site asked for another day than we offered. Earlier days wait for Network Rail’s yes; later weeks they are told about.'
    : auto.mode === 'live'
    ? 'Collected before the stock’s availability date: Network Rail are asked; in a later week than it: they get a heads-up - by itself in working hours, and their yes or no is read off their reply. Anything it isn’t sure of is held here for you.'
    : auto.mode === 'shadow'
      ? `Shadow mode (${auto.why || 'Auto follow-ups'}): it only says what it would do. Send and answer them here.`
      : `Not by itself just now: ${auto.why || 'automatic sending is off'}. Send and answer them here.`;
  return (
    <div className={'card noaddress nrcard' + (need.length ? ' need' : '')}>
      <div className="noaddress-head">
        <h3>Network Rail: {rows.length === 1 ? '1 date change' : rows.length + ' date changes'}
          {need.length ? <span className="nrcard-need"> &middot; {need.length} for you</span> : null}</h3>
        <span className="noaddress-why">{said}</span>
      </div>
      {sorted.map((r) => (
        <div className="noaddress-row" key={r.id}>
          <div className="noaddress-what">
            <div className="noaddress-order">
              {(r.orders || []).join(' / ')}
              <span className="noaddress-when">{[r.worksite || r.site, r.postcode].filter(Boolean).join(' ')}</span>
            </div>
            <NrDateBox r={r} onCommand={onCommand} compact auto={auto} />
          </div>
        </div>
      ))}
    </div>
  );
}
