"use client";

import { TASK_ACTION, dueInfo, type Task } from "@/lib/data";
import { cardAction, needsReview } from "@/lib/portal";

export default function DeliverPanel({ tasks, onAdvance }: { tasks: Task[]; onAdvance: (id: string) => void }) {
  const ready = tasks.filter((t) => t.status === "todo" || t.status === "in_progress");
  const delivered = tasks.filter((t) => t.status === "done");

  return (
    <div className="panel-in dl-grid">
      <div className="dl-col">
        <div className="panel-h">
          <div className="panel-hint">
            <span className="material-symbols-rounded">play_circle</span>
            Run &amp; deliver — {ready.length} job{ready.length === 1 ? "" : "s"} to work
          </div>
        </div>

        {ready.length === 0 ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">done_all</span>
            <div className="pt-empty-t">Nothing to run</div>
            <div className="pt-empty-s">Everything is delivered or awaiting review.</div>
          </div>
        ) : (
          <div className="dl-list">
            {ready.map((t) => {
              const a = TASK_ACTION[t.type];
              const action = cardAction(t)!;
              const due = dueInfo(t.due);
              const running = t.status === "in_progress";
              return (
                <div className="dl-job" key={t.id}>
                  <span className={`dl-ic ${running ? "on" : ""}`}>
                    <span className="material-symbols-rounded">{a.icon}</span>
                  </span>
                  <div className="dl-main">
                    <div className="dl-title">{t.title}</div>
                    <div className="dl-meta">
                      <span className="task-id">{t.id}</span>
                      <span className="dot-sep">·</span>
                      <span>{t.client}</span>
                      <span className="task-type">{t.type}</span>
                      <span className={`pq-due ${due.tone}`}>{due.label}</span>
                    </div>
                    {running && needsReview(t) && (
                      <div className="dl-hint">
                        <span className="material-symbols-rounded">info</span>
                        Content is sent to the review gate before it publishes.
                      </div>
                    )}
                  </div>
                  <button className={`pq-action ${running ? "solid" : ""}`} onClick={() => onAdvance(t.id)}>
                    <span className="material-symbols-rounded">{action.icon}</span>{action.label}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="dl-col">
        <div className="panel-h">
          <div className="panel-hint">
            <span className="material-symbols-rounded">outbox</span>
            Recent deliveries — pushed to clients
          </div>
        </div>

        {delivered.length === 0 ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">local_shipping</span>
            <div className="pt-empty-t">No deliveries yet</div>
            <div className="pt-empty-s">Delivered jobs show up here with the client they went to.</div>
          </div>
        ) : (
          <div className="dl-delivered">
            {delivered.map((t) => (
              <div className="dl-done" key={t.id}>
                <span className="dl-done-ic"><span className="material-symbols-rounded">check</span></span>
                <div className="dl-main">
                  <div className="dl-title">{t.title}</div>
                  <div className="dl-meta">
                    <span className="task-id">{t.id}</span>
                    <span className="dot-sep">·</span>
                    <span>{t.client}</span>
                    <span className="task-type">{t.type}</span>
                  </div>
                </div>
                <span className="dl-done-badge">
                  <span className="material-symbols-rounded">check_circle</span>Delivered
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
