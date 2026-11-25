import AssistCard from '../components/AssistCard.jsx';
import InboxCard from '../components/InboxCard.jsx';
import UpdateReplyCard from '../components/UpdateReplyCard.jsx';

// The Emails page (his 25/11: "it probably needs to have its own page because it doesn't really clutter the whole
// dashboard, especially not like the front page"). Everything about his mail, off the front page:
//   Needs you        the inbox assistant's list, all of it, grouped Now / Today / This week - each with its suggested
//                    reply, Dealt with and Deal with it - and what it filed (or would file) with Put back
//   Emails waiting   only while the assistant is off (the older word-rule watch)
//   his reply        to the day's Region 2 Updates, drafted at 15:30 for him to finish and send
// The front page keeps one line that counts what needs him and brings him here; the tab carries the same count.
export default function EmailsPage({ panel, onCommand, onAssistOpen }) {
  const p = panel || {};
  const assistOn = !!(p.assist && p.assist.mode && p.assist.mode !== 'off');
  return (
    <div className="scroll"><div className="container page-anim">
      <div className="pagehead">
        <div>
          <div className="kicker">Region 2 · Inbox</div>
          <h1 className="h1">Emails</h1>
          <p>What needs you, what was filed for you, and your reply to the day&rsquo;s Region 2 Updates.</p>
        </div>
      </div>
      <AssistCard data={p.assist} onCommand={onCommand} push={p.push} onOpen={onAssistOpen} full />
      {!assistOn && <InboxCard data={p.inbox} onCommand={onCommand} />}
      <UpdateReplyCard data={p.update_reply} onCommand={onCommand} />
    </div></div>
  );
}
