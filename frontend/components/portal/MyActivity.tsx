"use client";

import {
  ACTIVITY_META, TASK_STATUS_META, SERIES,
  type Task, type TeamMemberRecord,
} from "@/lib/data";
import { useStore } from "@/lib/store";

// Verb + icon for each task state, from the member's point of view.
const STATE_FEED: Record<Task["status"], { verb: string; icon: string; c: string }> = {
  todo: { verb: "was assigned to you", icon: "assignment_add", c: SERIES.c4 },
  in_progress: { verb: "you're working on", icon: "bolt", c: SERIES.c1 },
  review: { verb: "you submitted for review", icon: "how_to_reg", c: SERIES.c3 },
  done: { verb: "you delivered", icon: "task_alt", c: "var(--ok)" },
};

export default function MyActivity({ me, myTasks }: { me: TeamMemberRecord; myTasks: Task[] }) {
  const { activity } = useStore();
  const myEvents = activity.filter((a) => a.actorInit === me.init);

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">history</span>
          Your recent activity &amp; the state of every job on your desk
        </div>
      </div>

      <div className="timeline">
        {myEvents.map((a) => {
          const meta = ACTIVITY_META[a.kind];
          return (
            <div className="tl-row" key={a.id}>
              <div className="tl-rail">
                <span className="tl-ic" style={{ background: `${meta.c}22`, color: meta.c }}>
                  <span className="material-symbols-rounded">{meta.icon}</span>
                </span>
              </div>
              <div className="tl-body">
                <div className="tl-line">
                  <span className="av xs" style={{ background: a.actorColor }}>{a.actorInit}</span>
                  <span className="tl-actor">You</span>
                  <span className="tl-action">{a.action}</span>
                  <span className="tl-target">{a.target}</span>
                </div>
                {a.meta && <div className="tl-meta">{a.meta}</div>}
              </div>
              <div className="tl-ago">{a.ago}</div>
            </div>
          );
        })}

        {myTasks.map((t) => {
          const f = STATE_FEED[t.status];
          const sm = TASK_STATUS_META[t.status];
          return (
            <div className="tl-row" key={t.id}>
              <div className="tl-rail">
                <span className="tl-ic" style={{ background: `${f.c}22`, color: f.c }}>
                  <span className="material-symbols-rounded">{f.icon}</span>
                </span>
              </div>
              <div className="tl-body">
                <div className="tl-line">
                  <span className="tl-action">{f.verb}</span>
                  <span className="tl-target">{t.id}</span>
                  <span className="tl-action">— {t.title}</span>
                </div>
                <div className="tl-meta">{t.client} · {t.type}</div>
              </div>
              <div className="tl-ago">{sm.label}</div>
            </div>
          );
        })}

        {myEvents.length === 0 && myTasks.length === 0 && (
          <div className="tl-empty">No activity yet — your work will show up here.</div>
        )}
      </div>
    </div>
  );
}
