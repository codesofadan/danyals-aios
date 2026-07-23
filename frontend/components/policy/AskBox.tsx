"use client";

import { useState, type FormEvent } from "react";
import { usePolicyAsk } from "@/lib/hooks/policy";

// The on-demand lookup box: type a policy topic, get a live, source-cited answer.
// The heavy lifting (Serper search + SSRF-guarded fetch + Claude Haiku) is all
// server-side and cost-gated; this component only submits the topic and renders the
// structured reply (answer + urgency + key rules + sources), degrading honestly.
export default function AskBox() {
  const ask = usePolicyAsk();
  const [topic, setTopic] = useState("");
  const result = ask.data;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const t = topic.trim();
    if (!t || ask.isPending) return;
    ask.mutate(t);
  }

  return (
    <section className="card pr-ask">
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded pr-ask-star">travel_explore</span>
            Ask Policy Radar
          </div>
          <div className="cs">Look up any Google policy or algorithm topic against the official sources, live.</div>
        </div>
      </div>

      <form className="pr-ask-bar" onSubmit={onSubmit}>
        <span className="material-symbols-rounded pr-ask-ic">search</span>
        <input
          className="pr-ask-in"
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. site reputation abuse, August core update, merchant listing schema…"
          maxLength={200}
          aria-label="Policy topic to look up"
        />
        <button className="pr-ask-btn" type="submit" disabled={ask.isPending || topic.trim().length === 0}>
          {ask.isPending ? "Searching…" : "Ask"}
        </button>
      </form>

      {ask.isError && (
        <div className="pr-empty pr-ask-msg">
          Couldn&apos;t run the lookup — {(ask.error as Error)?.message ?? "try again"}.
        </div>
      )}

      {result && (
        <div className="pr-ask-out">
          <div className="pr-ask-head">
            <span className={`pr-ask-urg ${result.urgency}`}>
              <span className="material-symbols-rounded">
                {result.urgency === "urgent" ? "priority_high" : "info"}
              </span>
              {result.urgency === "urgent" ? "Act soon" : "Informational"}
            </span>
            {result.status === "degraded" && (
              <span className="pr-ask-degraded">
                <span className="material-symbols-rounded">cloud_off</span>Degraded
              </span>
            )}
          </div>

          <p className="pr-ask-answer">{result.answer}</p>

          {result.rules.length > 0 && (
            <div className="pr-ask-rules">
              <span className="pr-rec-k">Key rules</span>
              <ul>
                {result.rules.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          {result.sources.length > 0 && (
            <div className="pr-ask-sources">
              <span className="pr-rec-k">Sources</span>
              <div className="pr-ask-src-list">
                {result.sources.map((s) => (
                  <a className="pr-src-link" key={s} href={s} target="_blank" rel="noreferrer" title={s}>
                    {sourceLabel(s)}
                    <span className="material-symbols-rounded">open_in_new</span>
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// Show a source's host (a full URL is noisy); fall back to the raw string if unparseable.
function sourceLabel(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
