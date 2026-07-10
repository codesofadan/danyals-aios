"use client";

import { useState } from "react";
import type { Upsell } from "@/lib/upsells";
import AddUpsellModal from "./AddUpsellModal";

export type NewUpsell = {
  title: string;
  description: string;
  fiverrUrl: string;
  price: number;
  active: boolean;
};

export default function UpsellManager({
  list, onToggle, onMove, onAdd,
}: {
  list: Upsell[];
  onToggle: (id: string) => void;
  onMove: (id: string, dir: -1 | 1) => void;
  onAdd: (u: NewUpsell) => void;
}) {
  const [open, setOpen] = useState(false);
  const activeCount = list.filter((u) => u.active).length;

  function handleAdd(u: NewUpsell) {
    onAdd(u);
    setOpen(false);
  }

  return (
    <section className="card up-manager">
      <div className="card-h">
        <div>
          <div className="ct">Upsell manager</div>
          <div className="cs">Curate the Fiverr gigs shown to clients — toggle, reorder &amp; add.</div>
        </div>
        <div className="tools">
          <button className="primary-btn" onClick={() => setOpen(true)}>
            <span className="material-symbols-rounded">add</span>Add upsell
          </button>
        </div>
      </div>

      <div className="panel-hint up-hint">
        <span className="material-symbols-rounded">info</span>
        {activeCount} of {list.length} active · order here sets the order clients see.
      </div>

      <div className="tbl-wrap">
        <table className="tbl up-tbl">
          <thead>
            <tr>
              <th>Upsell</th>
              <th>Fiverr gig</th>
              <th className="num">Clicks 30d</th>
              <th>Active</th>
              <th>Order</th>
            </tr>
          </thead>
          <tbody>
            {list.map((u, i) => (
              <tr key={u.id} className={u.active ? "" : "up-off"}>
                <td>
                  <div className="up-cell">
                    <span className="up-badge" style={{ background: `${u.color}22`, color: u.color }}>
                      <span className="material-symbols-rounded">{u.icon}</span>
                    </span>
                    <div className="up-meta">
                      <div className="up-title">{u.title}</div>
                      <div className="up-desc">{u.description}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <a
                    className="up-gig"
                    href={u.fiverrUrl || "#"}
                    target="_blank"
                    rel="noreferrer"
                    title={u.fiverrUrl}
                  >
                    <span className="up-fiverr-mark">fi</span>
                    Open gig
                    <span className="material-symbols-rounded">open_in_new</span>
                  </a>
                </td>
                <td className="num">
                  <span className="up-clicks">{u.clicks30d.toLocaleString()}</span>
                </td>
                <td>
                  <button
                    className={`switch${u.active ? " on" : ""}`}
                    role="switch"
                    aria-checked={u.active}
                    aria-label={`${u.active ? "Deactivate" : "Activate"} ${u.title}`}
                    onClick={() => onToggle(u.id)}
                  >
                    <span className="switch-knob" />
                  </button>
                </td>
                <td>
                  <div className="up-reorder">
                    <button
                      className="up-move"
                      disabled={i === 0}
                      onClick={() => onMove(u.id, -1)}
                      aria-label="Move up"
                    >
                      <span className="material-symbols-rounded">keyboard_arrow_up</span>
                    </button>
                    <button
                      className="up-move"
                      disabled={i === list.length - 1}
                      onClick={() => onMove(u.id, 1)}
                      aria-label="Move down"
                    >
                      <span className="material-symbols-rounded">keyboard_arrow_down</span>
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && <AddUpsellModal onClose={() => setOpen(false)} onAdd={handleAdd} />}
    </section>
  );
}
