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
  proofPoints: string[];
  testimonials: string[];
  uniqueData: string[];
  services: string[];
};

// One item per non-blank line — how the grounding textareas map to the API arrays.
const _lines = (s: string): string[] =>
  s.split("\n").map((l) => l.trim()).filter(Boolean);

const FW_OPTIONS: (Framework | "Auto")[] = ["Auto", ...FRAMEWORKS.map((f) => f.key)];

export default function NewJobForm(
  { onCreate, halted = false }: { onCreate: (job: NewJob) => void; halted?: boolean },
) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const [clientId, setClientId] = useState("");
  const [pageType, setPageType] = useState<PageType>("service");
  const [topic, setTopic] = useState("");
  const [framework, setFramework] = useState<Framework | "Auto">("Auto");
  const [target, setTarget] = useState<PublishTarget>("WordPress");
  const [proof, setProof] = useState("");
  const [testimonials, setTestimonials] = useState("");
  const [uniqueData, setUniqueData] = useState("");
  const [services, setServices] = useState("");

  const effectiveClientId = clientId || clients[0]?.id || "";
  const hasProof = _lines(proof).length + _lines(testimonials).length + _lines(uniqueData).length > 0;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    // Generating a content job spends metered research + Claude budget, so it is
    // blocked while the global API-spend halt is engaged.
    if (!topic.trim() || !effectiveClientId || halted) return;
    onCreate({
      clientId: effectiveClientId,
      pageType,
      topic: topic.trim(),
      framework,
      target,
      // Cap to the server max_length so pasting extra lines can't 422 the create.
      proofPoints: _lines(proof).slice(0, 12),
      testimonials: _lines(testimonials).slice(0, 12),
      uniqueData: _lines(uniqueData).slice(0, 12),
      services: _lines(services).slice(0, 20),
    });
    setTopic("");
    setFramework("Auto");
    setProof("");
    setTestimonials("");
    setUniqueData("");
    setServices("");
  }

  return (
    <section className="card co-form-card">
      <div className="card-h">
        <div>
          <div className="ct">New content job</div>
          <div className="cs">Pick a content type + topic. The engine handles the rest to the review gate.</div>
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

        <div className="fld">
          <label>Proof &amp; first-hand experience</label>
          <textarea
            rows={3}
            value={proof}
            onChange={(e) => setProof(e.target.value)}
            placeholder={"One per line — real projects, results, credentials.\ne.g. Manufactured 12,000+ sofas since 2011 across 3 production lines\ne.g. Kiln-dried hardwood frames, 15-year structural warranty"}
          />
          <div className="fld-hint">
            Required to publish. The E-E-A-T / fact-grounding QA gate blocks any page with
            zero first-hand proof, so a job without this will hold at review as un-publishable.
          </div>
        </div>

        <div className="fld">
          <label>Testimonials <span className="cs">(optional, one per line)</span></label>
          <textarea rows={2} value={testimonials} onChange={(e) => setTestimonials(e.target.value)}
            placeholder={"'Best build quality we've sourced in 10 years' - a Lahore buyer"} />
        </div>

        <div className="fld">
          <label>Unique data / original stats <span className="cs">(optional, one per line)</span></label>
          <textarea rows={2} value={uniqueData} onChange={(e) => setUniqueData(e.target.value)}
            placeholder={"Our 2025 teardown of 200 returned units found 68% of failures start at the frame joint"} />
        </div>

        <div className="fld">
          <label>Services <span className="cs">(optional, one per line)</span></label>
          <textarea rows={2} value={services} onChange={(e) => setServices(e.target.value)}
            placeholder={"Custom sofa manufacturing\nUpholstery\nFrame construction"} />
        </div>

        {!hasProof && (
          <div className="cs" role="status" style={{ color: "var(--warn)", marginBottom: 8 }}>
            <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: 16 }}>info</span>{" "}
            No proof added — the job will generate but hold at review below the publish gate.
          </div>
        )}

        <button className="primary-btn wide" type="submit" disabled={!topic.trim() || !effectiveClientId || halted}>
          <span className="material-symbols-rounded">{halted ? "block" : "add"}</span>
          {halted ? "API spend is halted" : "Queue content job"}
        </button>
        {halted && (
          <div className="cs" role="status" style={{ color: "var(--warn)", marginTop: 8 }}>
            API spend is halted. Resume it in Cost Controls to queue content jobs.
          </div>
        )}
      </form>
    </section>
  );
}
