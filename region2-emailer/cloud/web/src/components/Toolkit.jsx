// The Toolkit switch (asked for 21/11: "a button that turns on and off the whole toolkit on the dashboard, just because
// we're now having issues with Outlook even opening on the home PC"). Off, the home PC leaves Outlook alone - no reply
// checks, chasers, wait-list emails, live monitor or work mail - and the buttons that start work say so. The home PC
// keeps the switch (toolkit.off, toolkit_switch.py) and says how it is on its panel: `toolkit` here is {on}, or while
// it is off {on: false, since, busy, outlook}. `asked` is {on, at} from a press until the panel says it is so.

const OFF_ASK = 'Turn the whole toolkit OFF?\n\n'
  + 'Nothing on the home PC will touch Outlook: no reply checks, chasers, wait-list emails, live monitor or work mail, '
  + 'and nothing runs by itself on the dashboard either. Buttons that start work (Book, Run, Export, sends) will say '
  + 'it is off.\n\n'
  + 'Anything already running finishes first. The dashboard stays connected, so you can turn it back on from here.';
const ON_ASK = 'Turn the toolkit back ON?\n\n'
  + 'The home PC starts working with Outlook again within a minute or so: replies, chasers, the wait list and the live '
  + 'monitor carry on where they left off.';

function press(on, onSet) {
  if (window.confirm(on ? ON_ASK : OFF_ASK)) onSet(on);
}

// on the Dashboard's head, beside Scan today's extract
export function ToolkitSwitch({ toolkit, asked, onSet }) {
  const known = !!toolkit;                     // a home PC on older code says nothing about it
  const on = !known || toolkit.on !== false;
  const turning = !!(asked && asked.on !== on);
  const label = turning ? (asked.on ? 'Turning on…' : 'Turning off…') : 'Toolkit ' + (on ? 'ON' : 'OFF');
  return (
    <button className={'switch toolkit' + (on ? ' on' : '')} role="switch" aria-checked={on}
      disabled={!known || turning}
      title={!known ? 'The home PC has not said how its Toolkit switch is yet.'
        : on ? 'The home PC is working with Outlook. Click to turn the whole toolkit off.'
          : 'The toolkit is off: nothing on the home PC uses Outlook. Click to turn it back on.'}
      onClick={() => press(!on, onSet)}>
      <span className="knob" />
      <span className="swlabel">{label}</span>
    </button>
  );
}

// under the top bar on every page while it is off - so it is never left off by mistake
export function ToolkitStrip({ toolkit, asked, onSet }) {
  if (!toolkit || toolkit.on !== false) return null;
  const busy = toolkit.busy || [];
  const turning = !!(asked && asked.on);
  return (
    <div className="tkoff" role="status">
      <div>
        <b>Toolkit off</b>{toolkit.since ? ' since ' + toolkit.since : ''}
        {busy.length ? ' - nothing new starts on Outlook. Still finishing: ' + busy.join(', ') + '.'
          : ' - nothing on the home PC is using Outlook.'}
        <span className="tkoff-more">
          {toolkit.outlook ? 'Outlook on the home PC: ' + toolkit.outlook + '. ' : ''}
          Buttons that start work wait until it is back on.
        </span>
      </div>
      <button className="btn go" disabled={turning} onClick={() => press(true, onSet)}>
        {turning ? 'Turning on…' : 'Turn it on'}
      </button>
    </div>
  );
}
