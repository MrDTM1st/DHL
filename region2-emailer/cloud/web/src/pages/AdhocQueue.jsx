import { useState, useEffect, useMemo, useCallback } from 'react';
import { I } from '../icons.jsx';
import { isUrgent, within3, ordLabel, dueText, dateShort, needsFor, RANK_TAG, RANK_LABEL } from '../lib/orders.js';
import { loadBoard, saveBoard, syncBoard, moveJob } from '../lib/board.js';

// Native HTML5 drag-and-drop board for ad-hoc (unbooked) orders: drag a job
// onto a haulier to assign it, or drag within/between lists to reorder the
// queue. No dnd-kit needed — the interaction is a single draggable list of
// cards plus a handful of drop targets, which the platform API covers with
// far less weight than pulling in a library for it.

function JobCard({ job, from, dragging, onDragStart, onDragEnd, onDragOver }) {
  const need = needsFor(job);
  return (
    <div
      className={'jobcard' + (dragging ? ' dragging' : '') + (isUrgent(job) ? ' urgent' : '')}
      draggable
      onDragStart={(e) => onDragStart(e, job.id, from)}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
    >
      <span className="jobcard-grip">{I.grip}</span>
      <div className="jobcard-body">
        <div className="jobcard-ord">
          {ordLabel(job)}
          {within3(job.delivery_date) && <span className="ubadge">≤3 DAYS</span>}
          {job.loose_ballast && <span className="lbadge">LOOSE BALLAST</span>}
        </div>
        <div className="jobcard-sub">{[job.worksite || job.site, job.postcode].filter(Boolean).join(', ')}</div>
        <div className="jobcard-meta">
          <span className={'jobcard-due' + (isUrgent(job) ? ' red' : '')}>{dueText(job)}{job.delivery_date ? ' · ' + dateShort(job.delivery_date) : ''}</span>
          {need.slice(0, 2).map((n, i) => <span className="needchip mini" key={i}>{n}</span>)}
        </div>
      </div>
    </div>
  );
}

function QueueColumn({ colKey, title, count, jobs, dragId, overCol, overIndex, onDragStartJob, onDragEndJob, onCardOver, onColOver, onDrop, empty }) {
  return (
    <div className={'queuecol' + (overCol === colKey ? ' over' : '')} onDragOver={(e) => onColOver(e, colKey, jobs.length)} onDrop={(e) => onDrop(e, colKey)}>
      <div className="queuecol-hd">
        <span className="lbl">{title}</span>
        <span className="queuecol-n">{count}</span>
      </div>
      <div className="queuecol-list">
        {jobs.length === 0 && (
          <div className="queuecol-empty">{empty}</div>
        )}
        {jobs.map((job, i) => (
          <div key={job.id}>
            {overCol === colKey && overIndex === i && <div className="dropline" />}
            <JobCard
              job={job}
              from={colKey}
              dragging={dragId === job.id}
              onDragStart={onDragStartJob}
              onDragEnd={onDragEndJob}
              onDragOver={(e) => onCardOver(e, colKey, i)}
            />
          </div>
        ))}
        {overCol === colKey && overIndex === jobs.length && jobs.length > 0 && <div className="dropline" />}
      </div>
    </div>
  );
}

function HaulierTarget({ h, jobs, dragId, overCol, overIndex, onDragStartJob, onDragEndJob, onCardOver, onColOver, onDrop, onUnassign }) {
  return (
    <div className={'hauliertgt' + (overCol === h.name ? ' over' : '')} onDragOver={(e) => onColOver(e, h.name, jobs.length)} onDrop={(e) => onDrop(e, h.name)}>
      <div className="hauliertgt-hd">
        <div className="hn"><b>{h.name}</b><span className={'htag ' + RANK_TAG[h.fleet ? 0 : (h.tier === 'tier1' ? 1 : 2)]}>{RANK_LABEL[h.fleet ? 0 : (h.tier === 'tier1' ? 1 : 2)]}</span></div>
        <div className="hs">{[h.loc, (h.caps || []).join(', ')].filter(Boolean).join(' · ') || h.phone}</div>
      </div>
      <div className="hauliertgt-list">
        {jobs.length === 0 && overCol !== h.name && <div className="hauliertgt-empty">Drop a job here to assign</div>}
        {jobs.map((job, i) => (
          <div key={job.id}>
            {overCol === h.name && overIndex === i && <div className="dropline" />}
            <div
              className={'jobchip' + (dragId === job.id ? ' dragging' : '')}
              draggable
              onDragStart={(e) => onDragStartJob(e, job.id, h.name)}
              onDragEnd={onDragEndJob}
              onDragOver={(e) => onCardOver(e, h.name, i)}
            >
              <span className="jobcard-grip">{I.grip}</span>
              <span className="jc-ord">{ordLabel(job)}</span>
              <span className="jc-sub">{job.worksite || job.site}</span>
              <button className="jc-x" title="Unassign" onClick={(e) => { e.stopPropagation(); onUnassign(job.id, h.name); }}>×</button>
            </div>
          </div>
        ))}
        {overCol === h.name && overIndex === jobs.length && <div className="dropline" />}
      </div>
    </div>
  );
}

export default function AdhocQueue({ records, hauliers }) {
  const [board, setBoard] = useState(loadBoard);
  const [dragId, setDragId] = useState(null);
  const [dragFrom, setDragFrom] = useState(null);
  const [overCol, setOverCol] = useState(null);
  const [overIndex, setOverIndex] = useState(null);

  // ad-hoc pool: anything the desk hasn't sent off yet
  const jobs = useMemo(() => records.filter((r) => !r.sendoff_ready), [records]);
  const jobsById = useMemo(() => Object.fromEntries(jobs.map((j) => [j.id, j])), [jobs]);

  useEffect(() => { setBoard((b) => syncBoard(b, jobs)); }, [jobs]);
  useEffect(() => { saveBoard(board); }, [board]);

  const resolve = (ids) => ids.map((id) => jobsById[id]).filter(Boolean);
  const queueJobs = resolve(board.queue);

  const resetDrag = useCallback(() => { setDragId(null); setDragFrom(null); setOverCol(null); setOverIndex(null); }, []);

  const onDragStartJob = useCallback((e, id, from) => {
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', String(id)); } catch { /* some browsers require this call to succeed for drag to start */ }
    setDragId(id); setDragFrom(from);
  }, []);

  const onCardOver = useCallback((e, colKey, index) => {
    e.preventDefault(); e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';
    const rect = e.currentTarget.getBoundingClientRect();
    const before = (e.clientY - rect.top) < rect.height / 2;
    setOverCol(colKey);
    setOverIndex(before ? index : index + 1);
  }, []);

  // Fires only when the pointer is over empty column space, not a card —
  // JobCard's onCardOver calls stopPropagation so it never reaches here when
  // hovering an actual card, which sets a precise before/after index instead.
  const onColOver = useCallback((e, colKey, len) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setOverCol(colKey);
    setOverIndex(len);
  }, []);

  const onDrop = useCallback((e, colKey) => {
    e.preventDefault(); e.stopPropagation();
    if (dragId == null || dragFrom == null) return;
    const idx = overCol === colKey ? overIndex : null;
    setBoard((b) => moveJob(b, dragId, dragFrom, colKey, idx));
    resetDrag();
  }, [dragId, dragFrom, overCol, overIndex, resetDrag]);

  const onUnassign = useCallback((id, from) => {
    setBoard((b) => moveJob(b, id, from, 'queue', null));
  }, []);

  const list = hauliers || [];

  return (
    <div className="scroll"><div className="container page-anim">
      <div className="pagehead">
        <div>
          <div className="kicker">Triage</div>
          <h1 className="h1">Ad hoc queue</h1>
          <p>Drag a job onto a haulier to assign it, or drag within the queue to reorder priority. Assignments live on this desk only — book the job as usual once it&rsquo;s settled.</p>
        </div>
      </div>

      <div className="queueboard">
        <QueueColumn
          colKey="queue" title="Unassigned queue" count={queueJobs.length} jobs={queueJobs}
          dragId={dragId} overCol={overCol} overIndex={overIndex}
          onDragStartJob={onDragStartJob} onDragEndJob={resetDrag}
          onCardOver={onCardOver} onColOver={onColOver} onDrop={onDrop}
          empty="Nothing waiting — every open job is assigned."
        />

        <div className="hauliergrid">
          {list.length === 0 && (
            <div className="emptybox" style={{ padding: '40px 20px' }}>
              {I.search}<div className="big">No hauliers yet</div><div>Waiting on the haulier list from the home PC.</div>
            </div>
          )}
          {list.map((h) => (
            <HaulierTarget
              key={h.name}
              h={h}
              jobs={resolve(board.assigned[h.name] || [])}
              dragId={dragId} overCol={overCol} overIndex={overIndex}
              onDragStartJob={onDragStartJob} onDragEndJob={resetDrag}
              onCardOver={onCardOver} onColOver={onColOver} onDrop={onDrop}
              onUnassign={onUnassign}
            />
          ))}
        </div>
      </div>
    </div></div>
  );
}
