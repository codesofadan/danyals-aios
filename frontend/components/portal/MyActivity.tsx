"use client";

import { ACTIVITY_META, type TeamMemberRecord } from "@/lib/data";
import { useActivity } from "@/lib/hooks/portal";

// The member's own recent activity, sourced live from GET /activity (filtered to
// events this member performed). The previous "state of every job on your desk"
// feed was dropped: it re-rendered every open task as a synthetic timeline row,
// duplicating the Queue with no new information.
export default function MyActivity({ me }: { me: TeamMemberRecord }) {
  const activityQ = useActivity();
  const myEvents = (activityQ.data ?? []).filter((a) => a.actorInit === me.init);

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">history</span>
          Your recent activity
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

        {activityQ.isLoading && myEvents.length === 0 && (
          <div className="tl-empty">Loading your activity…</div>
        )}
        {!activityQ.isLoading && myEvents.length === 0 && (
          <div className="tl-empty">No activity yet — your work will show up here.</div>
        )}
      </div>
    </div>
  );
}
