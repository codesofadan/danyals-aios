"use client";

import { useEffect, useState } from "react";
import type { NewUpsell } from "./UpsellManager";

export default function AddUpsellModal({
  onClose, onAdd,
}: {
  onClose: () => void;
  onAdd: (u: NewUpsell) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [fiverrUrl, setFiverrUrl] = useState("");
  const [price, setPrice] = useState("");
  const [active, setActive] = useState(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const titleValid = title.trim().length > 2;
  const descValid = description.trim().length > 4;
  const valid = titleValid && descValid;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    onAdd({
      title: title.trim(),
      description: description.trim(),
      fiverrUrl: fiverrUrl.trim(),
      price: Math.max(0, Math.round(Number(price)) || 0),
      active,
    });
  }

  return (
    <div className="up-scrim" onClick={onClose}>
      <form className="up-modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <div className="up-modal-h">
          <div>
            <div className="up-modal-t">Add upsell</div>
            <div className="up-modal-s">Link a Fiverr gig as a new client-portal upsell card.</div>
          </div>
          <button type="button" className="up-modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        <div className="fld">
          <label>Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Premium Backlink Package" autoFocus />
        </div>

        <div className="fld">
          <label>Description</label>
          <textarea
            className="up-textarea"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What the client gets, in one line…"
            rows={2}
          />
        </div>

        <div className="fld-row">
          <div className="fld">
            <label>Fiverr URL</label>
            <input value={fiverrUrl} onChange={(e) => setFiverrUrl(e.target.value)} placeholder="https://www.fiverr.com/xegents/…" />
          </div>
          <div className="fld">
            <label>Starting price ($)</label>
            <input type="number" min={0} value={price} onChange={(e) => setPrice(e.target.value)} placeholder="99" />
          </div>
        </div>

        <div className="up-active-row">
          <div>
            <div className="up-active-l">Active</div>
            <div className="up-active-s">Show this card to clients immediately.</div>
          </div>
          <button
            type="button"
            className={`switch${active ? " on" : ""}`}
            role="switch"
            aria-checked={active}
            aria-label="Active on add"
            onClick={() => setActive((v) => !v)}
          >
            <span className="switch-knob" />
          </button>
        </div>

        <div className="up-modal-f">
          <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary-btn" disabled={!valid}>
            <span className="material-symbols-rounded">add</span>Add upsell
          </button>
        </div>
      </form>
    </div>
  );
}
