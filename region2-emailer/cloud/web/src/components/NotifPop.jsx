import { I } from '../icons.jsx';

// Bell dropdown — the six most recent notifications, derived from urgent orders.
export default function NotifPop({ notes, onOpen, markAll, seeAll }) {
  const show = notes.slice(0, 6);
  return (
    <div className="notif-pop" onClick={(e) => e.stopPropagation()}>
      <div className="ph"><b>Notifications</b><button onClick={markAll}>Mark all read</button></div>
      <div className="pl">
        {!show.length && (
          <div style={{ padding: '26px 16px', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
            Nothing new right now.
          </div>
        )}
        {show.map((n) => (
          <div className={'popitem' + (n.read ? '' : ' unread')} key={n.id} onClick={() => onOpen(n)}>
            <div className={'noticon ' + n.kind}>{n.kind === 'urgent' ? I.bell : I.check}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="nt">{n.title}</div>
              <div className="nm">{n.msg}</div>
            </div>
            <span className="nottime">{n.time}</span>
          </div>
        ))}
      </div>
      <div className="pf"><button onClick={seeAll}>See all notifications</button></div>
    </div>
  );
}
