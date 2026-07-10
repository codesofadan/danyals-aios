"use client";

import { useState } from "react";
import {
  PAGE_TYPES, TARGETS, FRAMEWORKS,
  type PageType, type PublishTarget, type Framework,
} from "@/lib/content";

const CLIENTS = [
  "NorthPeak Dental", "Lumen Realty", "Verde Cafe", "Atlas Legal",
  "BrightHVAC", "Coastline Fit", "Meridian Wealth", "Orchard Pediatrics",
];

export type NewJob = {
  client: string;
  pageType: PageType;
  topic: string;
  framework: Framework | "Auto";
  target: PublishTarget;
};

const FW_OPTIONS: (Framework | "Auto")[] = ["Auto", ...FRAMEWORKS.map((f) => f.key)];

export default function NewJobForm({ onCreate }: { onCreate: (job: NewJob) => void }) {
  const [client, setClient] = useState(CLIENTS[0]);
  const [pageType, setPageType] = useState<PageType>("service");
  const [topic, setTopic] = useState("");
  const [framework, setFramework] = useState<Framework | "Auto">("Auto");
  const [target, setTarget] = useState<PublishTarget>("WordPress");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!topic.trim()) return;
    onCreate({ client, pageType, topic: topic.trim(), framework, target });
    setTopic("");
    setFramework("Auto");
  }

  return (
    <section className="card co-form-card">
      <div className="card-h">
        <div>
          <div className="ct">New content job</div>
          <div className="cs">Pick a content type + topic — the engine handles the rest to the review gate.</div>
        </div>
      </div>

      <form className="co-form" onSubmit={submit}>
        <div className="fld">
          <label>Client</label>
          <select value={client} onChange={(e) => setClient(e.target.value)}>
            {CLIENTS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        <div className="fld">
          <label>Page type</label>
          <div className="co-chips">
            {PAGE_TYPES.map((p) => (
              <button type="button" key={p}
                className={pageType === p ? "chip on" : "chip"}
                onClick={() => setPageType(p)}>
                {p}
              </button>
            ))}
          </div>
        </div>

        <div className="fld">
          <label>Topic</label>
          <input value={topic} onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Emergency dental care in Denver" />
        </div>

        <div className="fld">
          <label>Framework</label>
          <div className="co-chips wrap">
            {FW_OPTIONS.map((f) => (
              <button type="button" key={f}
                className={framework === f ? "chip on" : "chip"}
                onClick={() => setFramework(f)}>
                {f}
              </button>
            ))}
          </div>
          <div className="fld-hint">
            {framework === "Auto"
              ? "Auto selects a framework from the page type + search intent."
              : FRAMEWORKS.find((x) => x.key === framework)?.expansion}
          </div>
        </div>

        <div className="fld">
          <label>Publish target</label>
          <div className="seg co-target-seg">
            {TARGETS.map((t) => (
              <button type="button" key={t}
                className={target === t ? "on" : ""}
                onClick={() => setTarget(t)}>
                {t === "WordPress" ? "WordPress" : "PDF / Markdown"}
              </button>
            ))}
          </div>
        </div>

        <button className="primary-btn wide" type="submit" disabled={!topic.trim()}>
          <span className="material-symbols-rounded">add</span>Queue content job
        </button>
      </form>
    </section>
  );
}
