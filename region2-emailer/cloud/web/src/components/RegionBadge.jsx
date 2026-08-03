import { nrRegion, HOME_REGION } from '../lib/regions.js';

// The NR region of a DELIVERY postcode, as a small badge.
//
// Deliberately not decorative. Every order on this desk should be R2, so a
// badge showing anything else is the interesting case - either an order got in
// that is not ours, or the region scope needs widening. It renders in red so
// that stands out rather than blending into the address line.
//
// An unrecognised or missing postcode renders NOTHING at all. A "?" badge on
// every order with a blank postcode would be noise, and inventing a region for
// one is worse than saying nothing - same rule as the rest of the toolkit.
export function RegionBadge({ pc, title }) {
  const r = nrRegion(pc);
  if (!r) return null;
  const home = r === HOME_REGION;
  return (
    <span
      className={'rgbadge' + (home ? '' : ' away')}
      title={title || (home
        ? `Network Rail ${r} - this desk's region`
        : `Network Rail ${r} - OUTSIDE ${HOME_REGION}, this delivery is not normally ours`)}
    >
      {r}
    </span>
  );
}
