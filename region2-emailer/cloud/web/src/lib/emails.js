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
  const answered = on ? ((a.auto && a.auto.sent) || []).length : 0;
  return { n, now, hot, update, on, answered };
}

// Auto-answers (inbox_assist + auto_answer.py, 25/11): what became of Book's answer to an email whose only question
// is one Book has answered (booked? when? who? the ref?) - in a line under the email, the card's and the alert's.
export function autoLine(auto, mode) {
  if (!auto || !auto.state) return null;
  if (auto.state === 'ready') {
    return { cls: 'ready', text: (mode === 'live' ? 'Answering it myself in a moment' : "I'd answer this myself (shadow)")
      + (auto.said ? ' · ' + auto.said : '') };
  }
  if (auto.state === 'unchecked') {
    return { cls: 'unchecked', text: 'Book’s answer is below, not sent by itself: ' + (auto.why || 'CTMS couldn’t confirm it') };
  }
  if (auto.state === 'failed') return { cls: 'failed', text: 'I couldn’t send it myself: ' + (auto.why || 'no reason given') };
  if (auto.state === 'held') return { cls: 'held', text: 'Not one to answer by itself: ' + (auto.why || '') };
  return null;
}
