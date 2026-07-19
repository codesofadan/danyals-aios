"use client";

import { useState } from "react";
import {
  PAGE_TYPES, PAGE_TYPE_LABELS, TARGETS, FRAMEWORKS,
  type PageType, type PublishTarget, type Framework,
} from "@/lib/content";
import { useClients } from "@/lib/hooks/clients";

export type NewJob = {
  clientId: string;
  pageType: PageType;
  topic: string;
  framework: Framework | "Auto";
  target: PublishTarget;
};

const FW_OPTIONS: (Framework | "Auto")[] = ["Auto", ...FRAMEWORKS.map((f) => f.key)];

export default function NewJobForm({ onCreate }: { onCreate: (job: NewJob) => void }) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const [clientId, setClientId] = useState("");
  const [pageType, setPageType] = useState<PageType>("service");
  const [topic, setTopic] = useState("");
  const [framework, setFramework] = useState<Framework | "Auto">("Auto");
  const [target, setTarget] = useState<PublishTarget>("WordPress");

  const effectiveClientId = clientId || clients[0]?.id || "";

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!topic.trim() || !effectiveClientId) return;
    onCreate({ clientId: effectiveClientId, pageType, topic: topic.trim(), framework, target });
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
          <select
            value={effectiveClientId}
            onChange={(e) => setClientId(e.target.value)}
            disabled={clients.length === 0}
          >
            {clients.length === 0 ? (
              <option value="">{clientsQ.isLoading ? "Loading clients…" : "No clients yet"}</option>
            ) : (
              clients.map((c) => <option key={c.id} value={c.id}>{c.cn}</option>)
            )}
          </select>
        </div>

        <div className="fld">
          <label>Page type</label>
          <div className="co-chips">
            {PAGE_TYPES.map((p) => (
              <button type="button" key={p}
                className={pageType === p ? "chip on" : "chip"}
                onClick={() => setPageType(p)}>
                {PAGE_TYPE_LABELS[p]}
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

        <button className="primary-btn wide" type="submit" disabled={!topic.trim() || !effectiveClientId}>
          <span className="material-symbols-rounded">add</span>Queue content job
        </button>
      </form>
    </section>
  );
}
