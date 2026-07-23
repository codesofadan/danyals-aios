"use client";

// GMB post composer: the operator picks a client + post type + CTA and prompts the AI
// to draft a GBP-policy-compliant post. Mirrors the content NewJobForm shape.

import { useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import type { CreateGmbPostInput } from "@/lib/hooks/gmb";
import {
  CTA_TYPES,
  GBP_RECOMMENDED_MAX,
  POST_TYPES,
  ctaNeedsUrl,
  type GmbCtaType,
  type GmbPostType,
} from "@/lib/gmb";

export default function GmbComposer({
  onCreate, pending,
}: {
  onCreate: (input: CreateGmbPostInput) => void;
  pending: boolean;
}) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];

  const [clientId, setClientId] = useState("");
  const [topic, setTopic] = useState("");
  const [postType, setPostType] = useState<GmbPostType>("update");
  const [ctaType, setCtaType] = useState<GmbCtaType>("learn_more");
  const [ctaUrl, setCtaUrl] = useState("");
  const [title, setTitle] = useState("");

  const needsUrl = ctaNeedsUrl(ctaType);
  const needsTitle = postType === "offer" || postType === "event";
  const canSubmit = !!clientId && topic.trim().length > 0 && (!needsUrl || ctaUrl.trim().length > 0) && !pending;

  function submit() {
    if (!canSubmit) return;
    onCreate({
      client_id: clientId,
      topic: topic.trim(),
      postType,
      ctaType,
      ctaUrl: needsUrl ? ctaUrl.trim() : "",
      title: needsTitle ? title.trim() : "",
    });
    setTopic("");
  }

  return (
    <section className="card gmb-composer">
      <div className="card-h">
        <div>
          <div className="ct">New GMB post</div>
          <div className="cs">Prompt the AI for a Google Business Profile post — policy-checked, no em dashes.</div>
        </div>
      </div>

      <label className="gmb-field">
        <span>Client</span>
        <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
          <option value="">Select a client…</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>{c.cn}</option>
          ))}
        </select>
      </label>

      <div className="gmb-field">
        <span>Post type</span>
        <div className="gmb-chips">
          {POST_TYPES.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`gmb-chip${postType === p.key ? " on" : ""}`}
              onClick={() => setPostType(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {needsTitle && (
        <label className="gmb-field">
          <span>Title</span>
          <input
            type="text"
            value={title}
            placeholder={postType === "offer" ? "e.g. 20% off weekend brunch" : "e.g. Summer tasting night"}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
      )}

      <label className="gmb-field">
        <span>What should the post say?</span>
        <textarea
          rows={3}
          value={topic}
          placeholder="e.g. Announce our new weekend brunch menu and invite locals to book a table."
          onChange={(e) => setTopic(e.target.value)}
        />
      </label>

      <div className="gmb-row2">
        <label className="gmb-field">
          <span>Call to action</span>
          <select value={ctaType} onChange={(e) => setCtaType(e.target.value as GmbCtaType)}>
            {CTA_TYPES.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        </label>
        {needsUrl && (
          <label className="gmb-field">
            <span>Button URL</span>
            <input
              type="url"
              value={ctaUrl}
              placeholder="https://example.com/book"
              onChange={(e) => setCtaUrl(e.target.value)}
            />
          </label>
        )}
      </div>

      <div className="gmb-composer-foot">
        <span className="cs">Keep it under {GBP_RECOMMENDED_MAX} characters for best reach.</span>
        <button className="primary-btn" disabled={!canSubmit} onClick={submit}>
          <span className="material-symbols-rounded">auto_awesome</span>
          {pending ? "Generating…" : "Generate post"}
        </button>
      </div>
    </section>
  );
}
