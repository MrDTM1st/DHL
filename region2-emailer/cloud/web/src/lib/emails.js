// What needs him in his mail, in a line's worth (his 25/11: "it probably needs to have its own page because it doesn't
// really clutter the whole dashboard, especially not like the front page"). The Emails tab's badge and the front
// page's one line both come from here: the inbox assistant's Needs you while it's on, Emails waiting while it's off,
// and whether his reply to the day's Region 2 Updates is still to go (shown as UpdateReplyCard shows it).
export function emailSummary(panel) {
  const p = panel || {};
  const a = p.assist || {};
  const on = !!(a.mode && a.mode !== 'off');
  let n = 0;
  let now = 0;
  let hot = false;
  if (on) {
    const needs = a.needs || [];
    n = needs.length;
    now = needs.filter((i) => i.urgency === 'now').length;
    hot = needs.some((i) => i.urgency === 'now' || i.alarm);
  } else if (p.inbox && p.inbox.at) {
    const items = p.inbox.items || [];
    n = items.length;
    now = items.filter((i) => i.alarm).length;
    hot = now > 0;
  }
  const u = p.update_reply;
  const update = !!(u && !u.replied && (u.draft_at || u.arrived));
  return { n, now, hot, update, on };
}
