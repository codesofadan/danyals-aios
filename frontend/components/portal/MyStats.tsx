"use client";

import { dueInfo, type TeamMemberRecord, type Task } from "@/lib/data";

type Tile = {
  icon: string;
  label: string;
  value: string;
  delta?: string;
  deltaDir?: "up" | "down";
  note: string;
  hero?: boolean;
};

export default function MyStats({ me, myTasks }: { me: TeamMemberRecord; myTasks: Task[] }) {
  const open = myTasks.filter((t) => t.status !== "done");
  const attention = open.filter((t) => {
    const tone = dueInfo(t.due).tone;
    return tone === "overdue" || tone === "today";
  }).length;
  const inReview = myTasks.filter((t) => t.status === "review").length;

  const tiles: Tile[] = [
    { icon: "assignment", label: "Active tasks", value: String(open.length), note: "in your queue", hero: true },
    {
      icon: "priority_high", label: "Needs attention", value: String(attention),
      note: "due today or overdue",
      ...(attention > 0 ? { delta: String(attention), deltaDir: "down" as const } : {}),
    },
    { icon: "schedule", label: "On-time delivery", value: `${me.onTime}%`, delta: "1.3%", deltaDir: "up", note: "rolling 30 days" },
    { icon: "task_alt", label: "Delivered", value: String(me.completed), note: `this cycle · ${inReview} in review` },
  ];

  return (
    <section className="kpis">
      {tiles.map((t) => (
        <div key={t.label} className={t.hero ? "kpi hero" : "kpi"}>
          <div className="ic"><span className="material-symbols-rounded">{t.icon}</span></div>
          <div className="lab">{t.label}</div>
          <div className="val">{t.value}</div>
          <div className="sub">
            {t.delta && (
              <span className={`delta ${t.deltaDir}`}>
                <span className="material-symbols-rounded">
                  {t.deltaDir === "up" ? "trending_up" : "trending_down"}
                </span>
                {t.delta}
              </span>
            )}{" "}
            {t.note}
          </div>
        </div>
      ))}
    </section>
  );
}
