import { I } from '../icons.jsx';

// Alerts derived from urgent orders. The redesign's chosen trigger is an order
// dropping inside 3 days of delivery, the window where a haulier still needs
// booking; loose-ballast jobs count too. See deriveNotes() in App.jsx.
function NotifRow({ n, onOpen, onDismiss }) {
  return (
    <div className={'notif' + (n.read ? '' : ' unread')}>
      <div className={'noticon ' + n.kind}>{n.kind === 'urgent' ? I.bell : I.check}</div>
      <div className="notbody">
        <div className="nt">{!n.read && <span className="unreaddot" />}{n.title}</div>
        <div className="nm">{n.msg}</div>
        {n.orderId && <div className="nlink" onClick={() => onOpen(n)}>View in tracker {I.arrow}</div>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
        <span className="nottime">{n.time}</span>
        <button className="notx" onClick={() => onDismiss(n.id)}>×</button>
      </div>
    </div>
  );
}

export default function Notifications({ notes, onOpen, onDismiss, markAll, clearAll }) {
  const unread = notes.filter((n) => !n.read).length;
  const today = notes.filter((n) => !n.older);
  const earlier = notes.filter((n) => n.older);
  return (
    <div className="scroll"><div className="container page-anim" style={{ maxWidth: 760 }}>
      <div className="pagehead">
        <div>
          <div className="kicker">Alerts</div>
          <h1 className="h1">Notifications</h1>
          <p>You get an alert the moment an order drops inside 3 days of delivery, the window where a haulier still needs booking.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={markAll} disabled={!unread}>Mark all read</button>
          <button className="btn" onClick={clearAll} disabled={!notes.length}>Clear all</button>
        </div>
      </div>
      {!notes.length && (
        <div className="emptybox">{I.bell}<div className="big">You&rsquo;re all caught up</div><div>Urgent orders show up here as soon as they hit the ≤3-day window.</div></div>
      )}
      {today.length > 0 && <><div className="notgroup">Today</div>{today.map((n) => <NotifRow key={n.id} n={n} onOpen={onOpen} onDismiss={onDismiss} />)}</>}
      {earlier.length > 0 && <><div className="notgroup">Earlier</div>{earlier.map((n) => <NotifRow key={n.id} n={n} onOpen={onOpen} onDismiss={onDismiss} />)}</>}
    </div></div>
  );
}
