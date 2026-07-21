// Client-side board state for the ad-hoc job queue: which unbooked orders
// are waiting, and which haulier (if any) each has been dragged onto. There
// is no backend concept of "assignment" yet, so this lives in localStorage —
// purely a desk-side triage aid, not a booking.

const KEY = 'dhl_adhoc_board_v1';

export function loadBoard() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const b = JSON.parse(raw);
      if (b && Array.isArray(b.queue) && b.assigned && typeof b.assigned === 'object') return b;
    }
  } catch { /* ignore corrupt/blocked storage */ }
  return { queue: [], assigned: {} };
}

export function saveBoard(board) {
  try { localStorage.setItem(KEY, JSON.stringify(board)); } catch { /* private mode etc. */ }
}

// Keep the board's id lists in sync with the live job pool: newly-appeared
// jobs join the back of the unassigned queue, ids that no longer exist
// (booked, sent off, or dropped from the tracker) are dropped everywhere.
// Returns the same object (no-op) when nothing changed, so callers can use
// it directly as a setState updater without triggering extra renders.
export function syncBoard(board, jobs) {
  const live = new Set(jobs.map((j) => j.id));
  const placed = new Set();

  const queue = board.queue.filter((id) => live.has(id));
  queue.forEach((id) => placed.add(id));

  const assigned = {};
  Object.keys(board.assigned).forEach((h) => {
    const list = board.assigned[h].filter((id) => live.has(id) && !placed.has(id));
    list.forEach((id) => placed.add(id));
    if (list.length) assigned[h] = list;
  });

  jobs.forEach((j) => { if (!placed.has(j.id)) queue.push(j.id); });

  const sameArr = (a, b) => a.length === b.length && a.every((id, i) => id === b[i]);
  const aKeys = Object.keys(assigned), bKeys = Object.keys(board.assigned);
  const assignedSame = aKeys.length === bKeys.length
    && aKeys.every((h) => board.assigned[h] && sameArr(assigned[h], board.assigned[h]));
  if (sameArr(queue, board.queue) && assignedSame) return board;

  return { queue, assigned };
}

// Move job `id` from column `fromKey` to column `toKey` at `toIndex`.
// Column key 'queue' is the unassigned list; any other key is a haulier name.
export function moveJob(board, id, fromKey, toKey, toIndex) {
  if (id == null || fromKey == null || toKey == null) return board;
  const take = (key) => (key === 'queue' ? board.queue.slice() : (board.assigned[key] || []).slice());

  const fromList = take(fromKey);
  const idx = fromList.indexOf(id);
  if (idx === -1) return board;
  fromList.splice(idx, 1);

  const sameList = fromKey === toKey;
  const toList = sameList ? fromList : take(toKey);
  let insertAt = toIndex == null ? toList.length : toIndex;
  if (sameList && idx < insertAt) insertAt -= 1;
  insertAt = Math.max(0, Math.min(insertAt, toList.length));
  toList.splice(insertAt, 0, id);

  const queue = toKey === 'queue' ? toList : (fromKey === 'queue' ? fromList : board.queue.slice());
  const assigned = { ...board.assigned };
  if (fromKey !== 'queue') assigned[fromKey] = fromList;
  if (toKey !== 'queue') assigned[toKey] = toList;
  if (fromKey !== 'queue' && fromList.length === 0) delete assigned[fromKey];

  return { queue, assigned };
}
