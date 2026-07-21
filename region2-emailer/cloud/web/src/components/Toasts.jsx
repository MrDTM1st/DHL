import { I } from '../icons.jsx';

// Floating toast stack. Each toast: { id, title, msg, kind?('urgent'|'go'|'warn'), out? }.
export default function Toasts({ toasts, dismiss }) {
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div className={'toast' + (t.kind && t.kind !== 'urgent' ? ' ' + t.kind : '') + (t.out ? ' out' : '')} key={t.id}>
          <div className="ti">{t.kind === 'go' ? I.check : I.bell}</div>
          <div style={{ flex: 1 }}>
            <div className="tt">{t.title}</div>
            <div className="tm">{t.msg}</div>
          </div>
          <button className="tx" onClick={() => dismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
