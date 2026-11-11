import { useState } from 'react';

// Emails waiting for him (inbox_watch.py, 11/11 - his managers' "make sure emails are checked more regularly so urgent
// emails and queries are not missed"): every conversation from a person nobody has answered, read off the mailbox every
// few minutes by the home PC, the most pressing first. Past its time - 30 working minutes urgent, 60 high, 120 normal -
// it says so here and rings the bell. Dealt with: answered another way (a call), it stays off.

const PRI = { urgent: 'Urgent', high: 'High', normal: 'Normal' };

export default function InboxCard({ data, onCommand }) {
  const [gone, setGone] = useState({});
  const [open, setOpen] = useState(false);
  if (!data || !data.at) return null;
  const items = (data.items || []).filter((i) => !gone[i.id]);
  const late = items.filter((i) => i.alarm);
  const shown = open ? items : late.length ? late : items.slice(0, 3);

  const dealt = (i) => {
    onCommand({ action: 'inbox_dealt', data: { id: i.id } });
    setGone((g) => ({ ...g, [i.id]: true }));
  };

  if (!items.length) {
    return (
      <div className="card inbox-card quiet">
        <div className="noaddress-head">
          <h3>No emails waiting</h3>
          <span className="noaddress-why">Everyone who wrote has an answer. Checked {data.at}.</span>
        </div>
      </div>
    );
  }
  return (
    <div className={'card noaddress inbox-card' + (late.length ? '' : ' calm')}>
      <div className="noaddress-head">
        <h3>{late.length ? `${late.length} email${late.length === 1 ? '' : 's'} past their time`
          : `${items.length} email${items.length === 1 ? '' : 's'} waiting`}</h3>
        <span className="noaddress-why">Nobody has answered these yet. Checked {data.at}
          {data.low ? ` · ${data.low} copied-in or confirmations left off` : ''}.</span>
      </div>
      {shown.map((i) => (
        <div className="noaddress-row" key={i.id}>
          <div className="noaddress-what">
            <div className="noaddress-order">
              <span className={'inbox-pri ' + i.pri}>{PRI[i.pri] || i.pri}</span>
              {i.from}
              <span className={'noaddress-when' + (i.alarm ? ' soon' : '')}>waiting {i.waited}</span>
            </div>
            <div className="noaddress-site"><b>{i.subject}</b></div>
            <div className="noaddress-said">
              {[i.why, i.n > 1 ? `${i.n} emails in the thread` : '', 'last ' + i.received, i.folder].filter(Boolean).join(' · ')}
            </div>
            {i.said && <div className="noaddress-said">&ldquo;{i.said}&rdquo;</div>}
          </div>
          <div className="noaddress-fix">
            <button className="btn mini" onClick={() => dealt(i)}
              title="Answered another way (a call, Teams) - it stays off unless they write again">Dealt with</button>
          </div>
        </div>
      ))}
      {items.length > shown.length && (
        <div className="noaddress-row">
          <button className="btn mini" onClick={() => setOpen(true)}>Show all {items.length}</button>
        </div>
      )}
      {open && items.length > 3 && (
        <div className="noaddress-row">
          <button className="btn mini" onClick={() => setOpen(false)}>Show fewer</button>
        </div>
      )}
    </div>
  );
}
