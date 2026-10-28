import { I } from '../icons.jsx';
import { useClock } from '../hooks.js';

// Red/yellow DHL top nav: brand, page links, home-PC status pill, clock, bell.
// The CTMS link carries its own small dot for the work PC's bridge - a second
// machine, so it does not share the home PC's pill.
export default function TopNav({ page, setPage, unread, agentOnline, agentText, ctmsOnline, onBell, bellOpen }) {
  const clock = useClock();
  const nav = [
    ['dash', 'Dashboard', I.dash],
    ['map', 'Map', I.map],
    ['tracker', 'Tracker', I.track],
  ];
  return (
    <div className="topbar">
      <div className="brand">
        <div className="brandmark">DHL</div>
        <div className="brandtext"><b>Haulage Desk</b><span>Region 2 · Transport planning</span></div>
      </div>
      <nav className="nav">
        {nav.map(([k, label, ic]) => (
          <button key={k} className={'navlink' + (page === k ? ' active' : '')} onClick={() => setPage(k)}>
            {ic}<span>{label}</span>
          </button>
        ))}
        <button className={'navlink' + (page === 'ctms' ? ' active' : '')} onClick={() => setPage('ctms')}
          title={'CTMS bridge on the work PC: ' + (ctmsOnline ? 'online' : 'offline')}>
          {I.ctms}<span>CTMS</span>
          <span className={'navdot' + (ctmsOnline ? ' on' : '')} />
        </button>
        <button className={'navlink' + (page === 'notifications' ? ' active' : '')} onClick={() => setPage('notifications')}>
          {I.bellNav}<span>Notifications</span>
          {unread > 0 && <span className="navbadge">{unread}</span>}
        </button>
      </nav>
      <div className="topright">
        <div className={'statuspill' + (agentOnline ? '' : ' off')} title={agentText}>
          <span className="pdot" /><span className="ptext">{agentText}</span>
        </div>
        <div className="clock mono">{clock}</div>
        <button className={'bell' + (bellOpen ? ' active' : '')} onClick={onBell} title="Notifications">
          {I.bell}{unread > 0 && <span className="badge">{unread}</span>}
        </button>
      </div>
    </div>
  );
}
