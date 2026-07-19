"use client";

import Link from "next/link";
import { TASK_STATUS_META, dueInfo, type Task } from "@/lib/data";
import { usePortal } from "./PortalContext";
import PortalHeader from "./PortalHeader";
import MyStats from "./MyStats";

const PRIORITY_LABEL: Record<Task["priority"], string> = { urgent: "Urgent", high: "High", med: "Medium", low: "Low" };

export default function DashboardHome() {
  const { me, myTasks } = usePortal();

  const open = myTasks.filter((t) => t.status !== "done");
  const upNext = [...open]
    .sort((a, b) => dueInfo(a.due).days - dueInfo(b.due).days)
    .slice(0, 5);

  const counts = {
    todo: myTasks.filter((t) => t.status === "todo").length,
    in_progress: myTasks.filter((t) => t.status === "in_progress").length,
    review: myTasks.filter((t) => t.status === "review").length,
    done: myTasks.filter((t) => t.status === "done").length,
  };

  return (
    <div className="tw portal">
      <PortalHeader me={me} myTasks={myTasks} />
      <MyStats me={me} myTasks={myTasks} />

      <div className="row">
        {/* Up next */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Up next</div>
              <div className="cs">Your open work, soonest due first.</div>
            </div>
            <div className="tools">
              <Link href="/team/queue" className="ghostbtn">
                <span className="material-symbols-rounded">view_kanban</span>Open queue
              </Link>
            </div>
          </div>

          {upNext.length === 0 ? (
            <div className="pt-empty sm">
              <span className="material-symbols-rounded">celebration</span>
              <div className="pt-empty-t">You're all caught up</div>
              <div className="pt-empty-s">Nothing open right now — new assignments will appear here.</div>
            </div>
          ) : (
            <div className="dh-list">
              {upNext.map((t) => {
                const due = dueInfo(t.due);
                const sm = TASK_STATUS_META[t.status];
                return (
                  <Link href="/team/queue" className="dh-row" key={t.id}>
                    <span className={`prio-bar ${t.priority}`} title={`${PRIORITY_LABEL[t.priority]} priority`} />
                    <div className="dh-main">
                      <div className="dh-title">{t.title}</div>
                      <div className="dh-meta">
                        <span className="task-id">{t.id}</span>
                        <span className="dot-sep">·</span>
                        <span>{t.client}</span>
                        <span className="task-type">{t.type}</span>
                      </div>
                    </div>
                    <div className="dh-right">
                      <span className={`status-pill ${sm.cls}`}>{sm.label}</span>
                      <span className={`pq-due ${due.tone}`}>
                        <span className="material-symbols-rounded">schedule</span>{due.label}
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        {/* At a glance + quick actions */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">At a glance</div>
              <div className="cs">Where your work stands today.</div>
            </div>
          </div>

          <div className="dh-glance">
            <div className="dh-stat mut"><div className="dh-stat-n">{counts.todo}</div><div className="dh-stat-l">To do</div></div>
            <div className="dh-stat info"><div className="dh-stat-n">{counts.in_progress}</div><div className="dh-stat-l">In progress</div></div>
            <div className="dh-stat warn"><div className="dh-stat-n">{counts.review}</div><div className="dh-stat-l">In review</div></div>
            <div className="dh-stat ok"><div className="dh-stat-n">{counts.done}</div><div className="dh-stat-l">Delivered</div></div>
          </div>

          <div className="dh-actions">
            <Link href="/team/deliver" className="dh-action">
              <span className="dh-action-ic"><span className="material-symbols-rounded">play_circle</span></span>
              <div><div className="dh-action-t">Run &amp; deliver</div><div className="dh-action-s">Work your assigned jobs</div></div>
              <span className="material-symbols-rounded dh-action-go">chevron_right</span>
            </Link>
            <Link href="/team/review" className="dh-action">
              <span className="dh-action-ic"><span className="material-symbols-rounded">how_to_reg</span></span>
              <div><div className="dh-action-t">Review checkpoint</div><div className="dh-action-s">{counts.review} awaiting sign-off</div></div>
              <span className="material-symbols-rounded dh-action-go">chevron_right</span>
            </Link>
            <Link href="/team/access" className="dh-action">
              <span className="dh-action-ic"><span className="material-symbols-rounded">shield_person</span></span>
              <div><div className="dh-action-t">My access</div><div className="dh-action-s">Features unlocked for you</div></div>
              <span className="material-symbols-rounded dh-action-go">chevron_right</span>
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}
