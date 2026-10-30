import { I } from '../icons.jsx';
import { telHref, fmtPhone, canDial, copyText } from '../lib/phone.js';

/* One tap to ring someone - a haulier, or the site contact.
   It is a real tel: link, so on a phone the tap opens the dialler with the
   number already in and the phone asks you to press call. A computer has no
   dialler, and a bare tel: link there throws up a "pick an app" box, so on a
   computer the tap copies the number instead and says so. */
export default function CallButton({ number, who, onCall, label = 'Call', compact = false, big = false }) {
  if (!number) return null;
  const shown = fmtPhone(number);
  const press = (e) => {
    e.stopPropagation();   // the row underneath opens a brief / picks a haulier
    if (canDial()) {
      if (onCall) onCall({ who, number: shown, how: 'dial' });
      return;              // let the tel: link do the dialling
    }
    e.preventDefault();
    copyText(shown).then((ok) => onCall && onCall({ who, number: shown, how: ok ? 'copied' : 'shown' }));
  };
  return (
    <a className={'callbtn' + (compact ? ' icon' : '') + (big ? ' big' : '')} href={telHref(number)}
      onClick={press} title={'Call ' + (who ? who + ' — ' : '') + shown}
      aria-label={'Call ' + (who ? who + ', ' : '') + shown}>
      {I.phone}{!compact && <span>{label}</span>}
    </a>
  );
}
