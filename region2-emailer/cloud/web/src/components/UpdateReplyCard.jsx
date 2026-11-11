import { useEffect, useState } from 'react';

// His reply to the day's Region 2 Updates (daily_update.py, 11/11): the home PC drafts it into Outlook at 15:30 -
// each order on their list with where it stands, from the desk's records and the mailbox - as a Reply All in Drafts.
// Nothing is sent from here: he reads it, adds what only he knows, and sends it. [check] marks what no record or email
// shows. Before the draft is made the card only shows once their email is in (the inbox watch saw it).

function Marked({ text }) {
  const parts = String(text || '').split(/(\[check\]|\[your update\])/);
  return parts.map((p, i) => (p === '[check]' || p === '[your update]'
    ? <mark key={i} className="upd-mark">{p}</mark> : <span key={i}>{p}</span>));
}

export default function UpdateReplyCard({ data, onCommand }) {
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState('');
  // the button comes back once the new draft is on the panel - or after a minute and a half if it never came
  useEffect(() => { setAsked(''); }, [data && data.draft_at, data && data.text]);
  useEffect(() => {
    if (!asked) return undefined;
    const t = setTimeout(() => setAsked(''), 90000);
    return () => clearTimeout(t);
  }, [asked]);
  if (!data) return null;
  const drafted = !!data.draft_at;
  if (!drafted && (data.replied || !data.arrived)) return null;     // replied already, or nothing in yet
  const s = data.summary || {};
  const draft = (again) => {
    onCommand(again ? { action: 'update_draft', data: { again: true } } : { action: 'update_draft' });
    setAsked(again ? 'again' : 'now');
  };

  if (!drafted) {
    return (
      <div className="card noaddress upd-card waiting">
        <div className="noaddress-head">
          <h3>Region 2 Updates reply</h3>
          <span className="noaddress-why">
            {(data.by ? data.by.replace(/\s*\(.*\)/, '') + "'s" : 'Their')} email came in at {data.arrived}. Your reply is drafted into Outlook
            at {data.due}, with where each order stands.
          </span>
        </div>
        <div className="noaddress-row">
          <button className="btn mini" disabled={!!asked} onClick={() => draft(false)}>
            {asked ? 'Drafting…' : 'Draft it now'}
          </button>
        </div>
      </div>
    );
  }
  const lines = String(data.text || '').split('\n');
  return (
    <div className="card noaddress upd-card">
      <div className="noaddress-head">
        <h3>Your Region 2 Updates reply is in Drafts</h3>
        <span className="noaddress-why">
          Drafted {data.draft_at} for {data.from ? data.from.replace(/\s*\(.*\)/, '') + "'s" : 'their'} email of{' '}
          {data.for}. {s.orders || 0} order{s.orders === 1 ? '' : 's'}
          {s.checks ? `, ${s.checks} marked [check]` : ''}{s.points ? `, ${s.points} point${s.points === 1 ? '' : 's'} for your own words` : ''}.
          Read it, add what only you know, then send it from Outlook.
        </span>
      </div>
      {open && (
        <div className="upd-text">
          {lines.map((ln, i) => <div key={i} className={/^\d{1,2}\/\d{1,2} – /.test(ln) ? 'upd-week' : ''}><Marked text={ln} /></div>)}
        </div>
      )}
      <div className="noaddress-row">
        <div className="upd-btns">
          <button className="btn mini" onClick={() => setOpen(!open)}>{open ? 'Hide it' : 'Show it'}</button>
          <button className="btn mini" disabled={asked === 'again'} onClick={() => draft(true)}
            title="Write it again from where things stand now - an untouched earlier draft goes to Deleted Items">
            {asked === 'again' ? 'Drafting…' : 'Draft it again'}
          </button>
        </div>
      </div>
    </div>
  );
}
