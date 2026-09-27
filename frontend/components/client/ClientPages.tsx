"use client";

// The client's own pages — where each one is, and what it is waiting for.
//
// WHAT WAS MISSING. The content module ran entirely behind the agency's screens, so the
// client's two most ordinary questions had no answer in the product:
//
//   "Where is my page?"            → asked by message, answered by a person reading a board
//   "What do you need from me?"    → the pipeline knew, and only staff could see it
//
// WHAT THIS DELIBERATELY DOES NOT DO. A client approves nothing here. A page under review
// is not a client-facing document until a lead has read it, so no draft, no cost and no
// internal score is on this screen — the read comes from the client-safe view
// (`portal_content_jobs`, 0156), which cannot carry them.
//
// WAITING-ON-YOU COMES FIRST, above the list, because it is the only part of the screen
// with an action in it. A page held on an unanswered question is the single thing on this
// dashboard that only the client can unblock, and burying it inside a status list is how a
// page ends up sitting held for a fortnight.

import { useState } from "react";
import {
  useClientContent,
  useClientExperienceTodo,
  type PortalContentJob,
} from "@/lib/hooks/portalContent";
import ClientHeader from "./ClientHeader";
import ClientExperiencePanel from "./ClientExperiencePanel";

const STATUS_META: Record<string, { label: string; cls: string; icon: string }> = {
  queued: { label: "Queued", cls: "mut", icon: "schedule" },
  drafting: { label: "In progress", cls: "info", icon: "sync" },
  needs_review: { label: "With your team", cls: "info", icon: "rate_review" },
  publishing: { label: "Publishing", cls: "info", icon: "publish" },
  done: { label: "Live", cls: "ok", icon: "check_circle" },
  rejected: { label: "Stopped", cls: "warn", icon: "block" },
  failed: { label: "Stopped", cls: "warn", icon: "error" },
};

const PAGE_TYPE_LABEL: Record<string, string> = {
  blog: "Blog post",
  service: "Service page",
  location: "Location page",
  product: "Product page",
  landing: "Landing page",
  pillar: "Pillar page",
};

const prettyType = (t: string) =>
  PAGE_TYPE_LABEL[t] ?? (t ? t.replace(/[_-]/g, " ").replace(/^./, (c) => c.toUpperCase()) : "Page");

const waitingOnYou = (j: PortalContentJob) => j.stage.toLowerCase().startsWith("waiting on your");

export default function ClientPages() {
  const pagesQ = useClientContent();
  const todoQ = useClientExperienceTodo();
  const [openCode, setOpenCode] = useState<string | null>(null);

  const pages = pagesQ.data ?? [];
  const todo = todoQ.data ?? [];
  const live = pages.filter((p) => p.status === "done").length;

  return (
    <div className="tw cl">
      <ClientHeader
        focus={
          <>
            <span className="cl-focus-k">Your pages</span>
            <span className="cl-focus-v">
              {live} published{pages.length ? ` of ${pages.length}` : ""}
            </span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">
                {todo.length ? "help" : "article"}
              </span>
              {todo.length
                ? `${todo.length} page${todo.length === 1 ? "" : "s"} waiting on your answers`
                : "Nothing is waiting on you"}
            </span>
          </>
        }
      />

      {/* 1. THE ONLY PART WITH AN ACTION IN IT. */}
      {todo.length > 0 && (
        <section className="card" style={{ borderLeft: "4px solid var(--warn)" }}>
          <div className="card-h">
            <div>
              <div className="ct">We need a few facts from you</div>
              <div className="cs">
                We never invent details about your business — so when a page needs something
                only you know, we pause it and ask. Answering takes a minute: most questions
                offer choices drawn from what you have already told us.
              </div>
            </div>
          </div>

          <div className="cl-rp-list">
            {todo.map((t) => (
              <div className="cl-rp-row" key={t.code}>
                <span className="cl-rp-ic">
                  <span className="material-symbols-rounded">quiz</span>
                </span>
                <div className="cl-rp-main">
                  <div className="cl-rp-t">{t.topic || t.code}</div>
                  <div className="cl-rp-meta">
                    <span>{prettyType(t.pageType)}</span>
                    <span className="dot-sep">·</span>
                    <span>
                      {t.answered} of {t.slots} answered
                    </span>
                  </div>
                </div>
                <div className="cl-rp-actions">
                  <button
                    type="button"
                    className={openCode === t.code ? "ghostbtn" : "primary-btn sm"}
                    onClick={() => setOpenCode(openCode === t.code ? null : t.code)}
                  >
                    <span className="material-symbols-rounded">
                      {openCode === t.code ? "close" : "edit_note"}
                    </span>
                    {openCode === t.code ? "Close" : "Answer"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {openCode ? (
        <div style={{ marginTop: "var(--s-6)" }}>
          <ClientExperiencePanel code={openCode} onClose={() => setOpenCode(null)} />
        </div>
      ) : null}

      {/* 2. EVERY PAGE, AND WHERE IT HAS GOT TO. */}
      <section className="card" style={{ marginTop: "var(--s-7)" }}>
        <div className="card-h">
          <div>
            <div className="ct">Your pages</div>
            <div className="cs">
              Everything we are writing for you, and everything already published.
            </div>
          </div>
        </div>

        {pagesQ.isLoading ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded spin">progress_activity</span>
            <div className="pt-empty-t">Loading your pages…</div>
          </div>
        ) : pagesQ.isError ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">error</span>
            <div className="pt-empty-t">Couldn&apos;t load your pages</div>
            <div className="pt-empty-s">There was a problem reaching the server.</div>
            <button
              className="primary-btn sm"
              type="button"
              onClick={() => pagesQ.refetch()}
              style={{ marginTop: 12 }}
            >
              <span className="material-symbols-rounded">refresh</span>Retry
            </button>
          </div>
        ) : pages.length === 0 ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">article</span>
            <div className="pt-empty-t">No pages yet</div>
            <div className="pt-empty-s">
              Pages your team writes for you will appear here as they are built.
            </div>
          </div>
        ) : (
          <div className="cl-rp-list">
            {pages.map((p) => {
              const meta = STATUS_META[p.status] ?? STATUS_META.drafting;
              const asks = waitingOnYou(p);
              return (
                <div className={`cl-rp-row${asks ? " gen" : ""}`} key={p.code}>
                  <span className="cl-rp-ic">
                    <span className="material-symbols-rounded">
                      {p.status === "done" ? "public" : "article"}
                    </span>
                  </span>
                  <div className="cl-rp-main">
                    <div className="cl-rp-t">{p.topic || p.code}</div>
                    <div className="cl-rp-meta">
                      <span>{prettyType(p.pageType)}</span>
                      <span className="dot-sep">·</span>
                      {/* The stage is translated server-side into words written for you —
                          the operator's own labels (and anything about cost) never reach
                          this screen. */}
                      <span>{p.stage}</span>
                      {p.words > 0 && (
                        <>
                          <span className="dot-sep">·</span>
                          <span>{p.words.toLocaleString()} words</span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="cl-rp-actions">
                    {asks ? (
                      <button
                        type="button"
                        className="primary-btn sm"
                        onClick={() => setOpenCode(p.code)}
                      >
                        <span className="material-symbols-rounded">edit_note</span>Answer
                      </button>
                    ) : null}
                    <span className={`status-pill ${meta.cls}`}>
                      <span
                        className={`material-symbols-rounded${p.status === "drafting" ? " spin" : ""}`}
                        style={{ fontSize: 13 }}
                      >
                        {meta.icon}
                      </span>
                      {meta.label}
                    </span>
                    {p.url ? (
                      <a
                        className="ghostbtn"
                        href={p.url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        <span className="material-symbols-rounded">open_in_new</span>View
                      </a>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
