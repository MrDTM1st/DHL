import { nrRegion } from '../lib/regions.js';

// The NR region of a DELIVERY postcode, as a small badge.
//
// PLAIN INFORMATION, not a verdict. The first version rendered anything other
// than R2 in red, on the assumption that an out-of-region delivery meant
// something had gone wrong. It doesn't - two paths put out-of-region work on
// this desk deliberately:
//
//   * send_order.py, whose own docstring says a pasted order "is a deliberate
//     pick, so the region + supplier-rails filters are NOT applied here"
//   * ad hocs, which never go through a region check at all and land on the
//     map from a Haulage Request Form wherever the job happens to be
//
// So red would have fired constantly on perfectly normal work, and a warning
// that cries wolf is worse than no warning - it trains you to stop reading it.
// One neutral style for every region; the R1/R2/R3/R4 text is the information.
//
// An unrecognised or missing postcode renders NOTHING at all. A "?" badge on
// every order with a blank postcode would be noise, and inventing a region for
// one is worse than saying nothing - same rule as the rest of the toolkit.
export function RegionBadge({ pc, title }) {
  const r = nrRegion(pc);
  if (!r) return null;
  return (
    <span className="rgbadge" title={title || `Network Rail region ${r} (by delivery postcode)`}>
      {r}
    </span>
  );
}
