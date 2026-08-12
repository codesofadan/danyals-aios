"use client";

// ============================================================
// AIOS · content Review PREVIEW — the FULL SEO package
// A tabbed reviewer surface that shows the COMPLETE SEO deliverable, not just the
// body, so a lead can sign off on SEO compliance at a glance. Five sections, each
// wired to the real staff-only rich-retrieval endpoints
// (GET /content/jobs/{code}/{column}):
//   (a) ARTICLE   — the rendered draft HTML            (…/draft)
//   (b) META      — <title> + <meta description> + SERP snippet (…/outline → meta)
//   (c) SCHEMA    — the JSON-LD block, pretty-printed  (…/schema)
//   (d) OUTLINE   — H1/H2/H3 structure + keyword + internal-link coverage
//                   (headings parsed from the draft; …/keywords + …/links)
//   (e) QA        — the 14-dimension scorecard, pass/fail per dimension (…/qa)
// Plus an "Request edit" action that sends the edit action + a free-text
// instruction note to POST /content/{code}/review (the GUIDED-EDIT flow).
// ============================================================

import { useState } from "react";
import {
  useContentDraft,
  useContentSchema,
  useContentOutline,
  useContentKeywords,
  useContentLinks,
  useContentQa,
  useContentWp,
} from "@/lib/hooks/content";
import type { ContentJob } from "@/lib/content";
import type { ReviewAction } from "./ReviewGate";

const PAGE_LABEL: Record<ContentJob["pageType"], string> = {
  service: "Service", blog: "Blog", local: "Local", gbp_post: "GMB Post",
};

// --- a tiny, dependency-free Markdown -> HTML render (mirrors the backend md_to_html:
// headings, paragraphs, bullet lists, inline links + bold). The draft is our own
// output and the iframe is sandboxed (no scripts), but we still escape first. ---
function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s: string): string {
  return escapeHtml(s)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" rel="noopener nofollow">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}
function mdToHtml(md: string): string {
  const out: string[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      out.push("<ul>" + bullets.map((b) => `<li>${inline(b)}</li>`).join("") + "</ul>");
      bullets = [];
    }
  };
  for (const raw of md.split(/\r?\n/)) {
    const s = raw.trim();
    if (!s) flush();
    else if (s.startsWith("### ")) { flush(); out.push(`<h3>${inline(s.slice(4))}</h3>`); }
    else if (s.startsWith("## ")) { flush(); out.push(`<h2>${inline(s.slice(3))}</h2>`); }
    else if (s.startsWith("# ")) { flush(); out.push(`<h1>${inline(s.slice(2))}</h1>`); }
    else if (s.startsWith("- ")) bullets.push(s.slice(2));
    else { flush(); out.push(`<p>${inline(s)}</p>`); }
  }
  flush();
  return out.join("\n");
}

function frameDoc(bodyHtml: string): string {
  // A self-contained page doc for the srcDoc iframe. Neutral, readable styling that
  // adapts to the viewer's color scheme.
  return `<!doctype html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root { color-scheme: light dark; }
  body { font: 16px/1.65 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    margin: 0; padding: 28px 34px; color: #241015; background: #fff; }
  @media (prefers-color-scheme: dark) { body { color: #e9e2e4; background: #141013; } a { color: #e78aa0; } }
  h1 { font-size: 30px; line-height: 1.2; margin: 0 0 14px; }
  h2 { font-size: 22px; margin: 26px 0 10px; }
  h3 { font-size: 18px; margin: 20px 0 8px; }
  p, li { font-size: 16px; }
  ul { padding-left: 22px; }
  a { color: #8C1D2E; }
  img { max-width: 100%; }
</style></head><body>${bodyHtml}</body></html>`;
}

// Pull an http(s) URL out of a done job's stage label ("Published: <url>").
function liveUrlFromStage(job: ContentJob): string | null {
  if (job.status !== "done") return null;
  const m = job.stage.match(/https?:\/\/\S+/);
  return m ? m[0] : null;
}

// Parse the H1/H2/H3 outline straight out of the draft markdown (deliverable d).
type Head = { level: number; text: string };
function headingsFromMd(md: string): Head[] {
  const out: Head[] = [];
  for (const raw of md.split(/\r?\n/)) {
    const m = raw.match(/^(#{1,3})\s+(.*)$/);
    if (m) out.push({ level: m[1].length, text: m[2].trim() });
  }
  return out;
}

const TABS = [
  { key: "article", label: "Article", icon: "article" },
  { key: "meta", label: "Meta", icon: "title" },
  { key: "schema", label: "Schema", icon: "data_object" },
  { key: "outline", label: "Outline & coverage", icon: "format_list_bulleted" },
  { key: "qa", label: "QA scorecard", icon: "fact_check" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

// A QA dimension passes at/above the doctrine per-dimension floor (70).
const QA_FLOOR = 70;
const prettyDim = (d: string) => d.replace(/_/g, " ");

export default function ReviewPreview({
  job, onAction, onClose, hideActions = false,
}: {
  job: ContentJob;
  onAction: (id: string, action: ReviewAction, note?: string) => void;
  // Optional so the preview can be embedded (e.g. inside the content wizard) with no
  // standalone close affordance.
  onClose?: () => void;
  // When embedded in a flow that owns the approve step, hide the inline
  // approve / request-edit / reject bar so there is a single approve action.
  hideActions?: boolean;
}) {
  const draftQ = useContentDraft(job.id);
  const schemaQ = useContentSchema(job.id);
  const outlineQ = useContentOutline(job.id);
  const keywordsQ = useContentKeywords(job.id);
  const linksQ = useContentLinks(job.id);
  const qaQ = useContentQa(job.id);
  // Only fetch the WordPress push URLs once the job reports it was pushed to the
  // plugin (its live-polled stage flips to "Pushed to WordPress..."), so this never
  // fetches for a job that will never be pushed.
  const pluginPushed = job.status === "done" && job.stage.startsWith("Pushed to WordPress");
  const wpQ = useContentWp(pluginPushed ? job.id : null);

  const [tab, setTab] = useState<TabKey>("article");
  const [editOpen, setEditOpen] = useState(false);
  const [note, setNote] = useState("");

  const md = draftQ.data?.draft ?? "";
  const liveUrl = liveUrlFromStage(job);
  const inReview = job.status === "needs_review";
  // The WordPress push result (once an approved job was pushed to the client's AIOS
  // Publisher plugin as a draft). edit_url points the reviewer straight at the WP
  // editor to publish it there; url is the (draft) permalink. Primary source is the
  // real stored field; the URL embedded in the live stage label is an instant
  // fallback so the button works while the fetch settles.
  const wp = wpQ.data?.wp ?? null;
  const stageUrl = pluginPushed ? job.stage.match(/https?:\/\/\S+/)?.[0] ?? null : null;
  const wpEditUrl = wp?.edit_url || null;
  const wpUrl = wp?.url || null;
  const wpLink = wpEditUrl ?? wpUrl ?? stageUrl;

  const meta = outlineQ.data?.outline?.meta ?? {};
  const metaTitle = meta.title ?? "";
  const metaDesc = meta.description ?? "";
  const heads = headingsFromMd(md);
  const kw = keywordsQ.data?.keywords ?? null;
  const links = linksQ.data?.links?.links ?? [];
  const qa = qaQ.data?.qa ?? null;

  function sendEdit() {
    onAction(job.id, "edit", note.trim());
    setEditOpen(false);
    setNote("");
  }

  return (
    <section className="card co-preview-card" style={{ marginTop: 12 }}>
      <div className="card-h">
        <div>
          <div className="ct">SEO review · {job.id}</div>
          <div className="cs">
            {PAGE_LABEL[job.pageType]} · {job.framework} · {job.words.toLocaleString()} words ·{" "}
            {job.schema || "no schema"} · {job.images} image{job.images === 1 ? "" : "s"}
          </div>
        </div>
        {onClose && (
          <div className="tools">
            <button className="ghostbtn" onClick={onClose} aria-label="Close preview">
              <span className="material-symbols-rounded">close</span>Close
            </button>
          </div>
        )}
      </div>

      {/* Pushed-to-WordPress (draft) banner: takes precedence when the approved page
          was pushed to the client's site as a DRAFT and is published FROM WordPress. */}
      {pluginPushed ? (
        <div
          role="status"
          style={{
            display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
            margin: "0 0 12px", padding: "10px 14px", borderRadius: 10,
            background: "rgba(140,29,46,0.10)", border: "1px solid rgba(140,29,46,0.30)",
          }}
        >
          <span className="material-symbols-rounded" style={{ color: "#8C1D2E" }}>cloud_done</span>
          <strong>Pushed to WordPress (draft).</strong>
          <span style={{ opacity: 0.85 }}>Publish it on the site to take it live.</span>
          <a
            className="primary-btn"
            href={wpLink ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            style={{ marginLeft: "auto", textDecoration: "none" }}
          >
            <span className="material-symbols-rounded">open_in_new</span>Open in WordPress
          </a>
        </div>
      ) : job.status === "done" ? (
        /* Published banner + the live-URL "open" test action (legacy live-publish). */
        <div
          role="status"
          style={{
            display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
            margin: "0 0 12px", padding: "10px 14px", borderRadius: 10,
            background: "rgba(34,224,192,0.12)", border: "1px solid rgba(34,224,192,0.35)",
          }}
        >
          <span className="material-symbols-rounded" style={{ color: "#12b48f" }}>check_circle</span>
          <strong>Published.</strong>
          {liveUrl ? (
            <>
              <span style={{ opacity: 0.8, wordBreak: "break-all" }}>{liveUrl}</span>
              <a
                className="primary-btn"
                href={liveUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{ marginLeft: "auto", textDecoration: "none" }}
              >
                <span className="material-symbols-rounded">open_in_new</span>Open live post
              </a>
            </>
          ) : (
            <span style={{ opacity: 0.8 }}>{job.stage}</span>
          )}
        </div>
      ) : null}

      {/* Tab bar */}
      <div
        role="tablist"
        style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "0 0 12px",
          borderBottom: "1px solid var(--line, #e8d2d7)", paddingBottom: 8 }}
      >
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              role="tab"
              aria-selected={active}
              className="ghostbtn"
              onClick={() => setTab(t.key)}
              style={{
                fontWeight: active ? 700 : 500,
                color: active ? "var(--maroon-2, #8C1D2E)" : undefined,
                borderColor: active ? "var(--maroon-2, #8C1D2E)" : "transparent",
                background: active ? "var(--blush, #F8ECEE)" : "transparent",
              }}
            >
              <span className="material-symbols-rounded">{t.icon}</span>{t.label}
            </button>
          );
        })}
      </div>

      {/* (a) ARTICLE */}
      {tab === "article" && (
        draftQ.isLoading ? (
          <div className="co-gate-empty"><span className="material-symbols-rounded">hourglass_top</span>
            <div>Loading the draft…</div></div>
        ) : draftQ.isError ? (
          <div className="co-gate-empty" role="alert"><span className="material-symbols-rounded">error</span>
            <div>Couldn&apos;t load the draft — {(draftQ.error as Error)?.message ?? "try again"}.</div></div>
        ) : !md ? (
          <div className="co-gate-empty"><span className="material-symbols-rounded">hourglass_empty</span>
            <div>No draft yet — the pipeline is still writing this one.</div></div>
        ) : (
          <iframe
            title={`Draft preview for ${job.id}`}
            sandbox=""
            srcDoc={frameDoc(mdToHtml(md))}
            style={{
              width: "100%", height: 460, border: "1px solid var(--line, #e8d2d7)",
              borderRadius: 12, background: "#fff",
            }}
          />
        )
      )}

      {/* (b) META — the <title> + <meta description> + a Google SERP-style snippet */}
      {tab === "meta" && (
        <div style={{ display: "grid", gap: 12 }}>
          <MetaRow
            label="Title tag"
            value={metaTitle}
            limit={60}
            loading={outlineQ.isLoading}
          />
          <MetaRow
            label="Meta description"
            value={metaDesc}
            limit={160}
            loading={outlineQ.isLoading}
          />
          {/* SERP snippet mock */}
          <div style={{ padding: "14px 16px", borderRadius: 12, border: "1px solid var(--line, #e8d2d7)" }}>
            <div className="cs" style={{ marginBottom: 6 }}>Search preview</div>
            <div style={{ color: "#1a0dab", fontSize: 18, lineHeight: 1.3 }}>
              {metaTitle || job.topic}
            </div>
            <div style={{ color: "#0b7a34", fontSize: 13, margin: "2px 0 4px" }}>
              {wpUrl ?? stageUrl ?? liveUrl ?? "example.com › " + job.topic.toLowerCase().replace(/\s+/g, "-")}
            </div>
            <div style={{ fontSize: 13, opacity: 0.85 }}>
              {metaDesc || "The meta description will appear here once the draft is written."}
            </div>
          </div>
        </div>
      )}

      {/* (c) SCHEMA — the JSON-LD block, pretty-printed, with the @type */}
      {tab === "schema" && (
        <SchemaTab loading={schemaQ.isLoading} error={schemaQ.error as Error | null}
          data={schemaQ.data?.schema ?? null} fallbackType={job.schema} />
      )}

      {/* (d) OUTLINE — headings + keyword + internal-link coverage */}
      {tab === "outline" && (
        <div style={{ display: "grid", gap: 16 }}>
          <div>
            <div className="cs" style={{ marginBottom: 6 }}>Headings (H1 / H2 / H3)</div>
            {heads.length === 0 ? (
              <div className="cs" style={{ opacity: 0.7 }}>No headings yet.</div>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 3 }}>
                {heads.map((h, i) => (
                  <li key={i} style={{ paddingLeft: (h.level - 1) * 18, fontSize: 14,
                    fontWeight: h.level === 1 ? 700 : h.level === 2 ? 600 : 400 }}>
                    <span className="cs" style={{ opacity: 0.55, marginRight: 8 }}>H{h.level}</span>
                    {h.text}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <div className="cs" style={{ marginBottom: 6 }}>Keyword coverage</div>
            {!kw ? (
              <div className="cs" style={{ opacity: 0.7 }}>{keywordsQ.isLoading ? "Loading…" : "No keyword map."}</div>
            ) : (
              <div style={{ display: "grid", gap: 6 }}>
                {kw.primary && <ChipRow label="Primary" items={[kw.primary]} accent />}
                {kw.secondary?.length ? <ChipRow label="Secondary" items={kw.secondary} /> : null}
                {kw.semantic_entities?.length ? <ChipRow label="Entities" items={kw.semantic_entities} /> : null}
                {kw.questions?.length ? <ChipRow label="Questions" items={kw.questions} /> : null}
              </div>
            )}
          </div>

          <div>
            <div className="cs" style={{ marginBottom: 6 }}>Internal links ({links.length})</div>
            {links.length === 0 ? (
              <div className="cs" style={{ opacity: 0.7 }}>{linksQ.isLoading ? "Loading…" : "No internal links suggested."}</div>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 4 }}>
                {links.map((l, i) => (
                  <li key={i} style={{ fontSize: 14 }}>
                    <span className="material-symbols-rounded" style={{ fontSize: 15, verticalAlign: "-2px", opacity: 0.6 }}>link</span>{" "}
                    <strong>{l.anchor}</strong> <span style={{ opacity: 0.6 }}>→ {l.url}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* (e) QA SCORECARD — pass/fail per dimension incl. schema validity */}
      {tab === "qa" && (
        <QaTab loading={qaQ.isLoading} error={qaQ.error as Error | null} qa={qa} />
      )}

      {/* Review actions (only meaningful while the job awaits review). Hidden when
          embedded in a flow that owns its own approve step. */}
      {inReview && !hideActions && (
        <div className="co-gate-actions" style={{ marginTop: 14 }}>
          <button className="primary-btn co-approve" onClick={() => onAction(job.id, "approve")}>
            <span className="material-symbols-rounded">check</span>Approve &amp; publish
          </button>
          <button className="ghostbtn" onClick={() => setEditOpen((v) => !v)} aria-expanded={editOpen}>
            <span className="material-symbols-rounded">edit</span>Request edit
          </button>
          <button className="ghostbtn co-reject" onClick={() => onAction(job.id, "reject")}>
            <span className="material-symbols-rounded">close</span>Reject
          </button>
        </div>
      )}

      {/* The guided-edit instruction panel. */}
      {inReview && !hideActions && editOpen && (
        <div style={{ marginTop: 12, padding: 14, borderRadius: 12,
          border: "1px solid var(--line, #e8d2d7)", background: "var(--blush, #F8ECEE)" }}>
          <label htmlFor="co-edit-note" className="cs" style={{ display: "block", marginBottom: 6 }}>
            What should the re-draft change? The pipeline re-drafts targeting exactly this note.
          </label>
          <textarea
            id="co-edit-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. make the intro punchier, add an FAQ section, tighten the H2s, cut the fluff"
            rows={3}
            style={{ width: "100%", resize: "vertical", padding: "10px 12px", borderRadius: 10,
              border: "1px solid var(--line, #e8d2d7)", font: "inherit", fontSize: 14 }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
            <button className="ghostbtn" onClick={() => { setEditOpen(false); setNote(""); }}>Cancel</button>
            <button className="primary-btn" onClick={sendEdit} disabled={!note.trim()}>
              <span className="material-symbols-rounded">send</span>Send edit request
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// --- small presentational helpers -------------------------------------------
function MetaRow({ label, value, limit, loading }: {
  label: string; value: string; limit: number; loading: boolean;
}) {
  const len = value.length;
  const over = len > limit;
  return (
    <div style={{ padding: "12px 16px", borderRadius: 12, border: "1px solid var(--line, #e8d2d7)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div className="cs">{label}</div>
        <div className="cs" style={{ color: over ? "var(--warn, #C0392B)" : undefined }}>
          {loading ? "…" : `${len} / ${limit}`}
        </div>
      </div>
      <div style={{ fontSize: 15, marginTop: 4 }}>{value || (loading ? "Loading…" : "—")}</div>
    </div>
  );
}

function ChipRow({ label, items, accent }: { label: string; items: string[]; accent?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
      <span className="cs" style={{ minWidth: 78, opacity: 0.7 }}>{label}</span>
      {items.map((it, i) => (
        <span key={i} className="pill-tag" style={accent ? { background: "var(--blush-2, #F1DADE)", fontWeight: 700 } : undefined}>
          {it}
        </span>
      ))}
    </div>
  );
}

function SchemaTab({ loading, error, data, fallbackType }: {
  loading: boolean; error: Error | null; data: Record<string, unknown> | null; fallbackType: string;
}) {
  if (loading) return <div className="co-gate-empty"><span className="material-symbols-rounded">hourglass_top</span><div>Loading schema…</div></div>;
  if (error) return <div className="co-gate-empty" role="alert"><span className="material-symbols-rounded">error</span><div>Couldn&apos;t load the schema — {error.message}.</div></div>;
  const empty = !data || Object.keys(data).length === 0;
  if (empty) {
    return (
      <div className="co-gate-empty"><span className="material-symbols-rounded">data_object</span>
        <div>{fallbackType ? `No JSON-LD assembled yet (@type ${fallbackType}).` : "This page type carries no JSON-LD."}</div></div>
    );
  }
  // Pull the primary @type out of the graph for the badge.
  const graph = (data["@graph"] as Array<Record<string, unknown>> | undefined) ?? [];
  const primaryType = fallbackType
    || (graph.map((n) => n["@type"]).find(Boolean) as string | undefined)
    || (data["@type"] as string | undefined)
    || "";
  return (
    <div>
      {primaryType && (
        <div style={{ marginBottom: 8 }}>
          <span className="pill-tag ok"><span className="material-symbols-rounded">verified</span>@type: {primaryType}</span>
        </div>
      )}
      <pre style={{ margin: 0, padding: "14px 16px", borderRadius: 12, overflowX: "auto",
        background: "var(--blush, #F8ECEE)", border: "1px solid var(--line, #e8d2d7)",
        fontSize: 12.5, lineHeight: 1.5 }}>
        <code>{JSON.stringify(data, null, 2)}</code>
      </pre>
    </div>
  );
}

function QaTab({ loading, error, qa }: {
  loading: boolean; error: Error | null;
  qa: { dimensions: Record<string, number>; weighted_total: number; passed: boolean;
    blocked_by: string[]; provisional: boolean; notes: string[] } | null;
}) {
  if (loading) return <div className="co-gate-empty"><span className="material-symbols-rounded">hourglass_top</span><div>Loading QA…</div></div>;
  if (error) return <div className="co-gate-empty" role="alert"><span className="material-symbols-rounded">error</span><div>Couldn&apos;t load the QA scorecard — {error.message}.</div></div>;
  if (!qa || Object.keys(qa.dimensions ?? {}).length === 0) {
    return <div className="co-gate-empty"><span className="material-symbols-rounded">fact_check</span><div>No QA scorecard yet — it is attached when the draft reaches review.</div></div>;
  }
  const dims = Object.entries(qa.dimensions);
  return (
    <div>
      {/* Headline verdict */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <span className={`pill-tag ${qa.passed ? "ok" : "warn"}`}>
          <span className="material-symbols-rounded">{qa.passed ? "check_circle" : "gpp_maybe"}</span>
          {qa.passed ? "Passes the publish gate" : "Below the publish gate"}
        </span>
        <span className="pill-tag"><strong>{qa.weighted_total}</strong>&nbsp;/ 100 weighted</span>
        {qa.provisional && <span className="pill-tag" style={{ opacity: 0.8 }}>provisional weights</span>}
      </div>

      {qa.blocked_by.length > 0 && (
        <div role="alert" style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 10,
          background: "rgba(192,57,43,0.10)", border: "1px solid rgba(192,57,43,0.35)", fontSize: 13 }}>
          Hard-blocked by: {qa.blocked_by.map(prettyDim).join(", ")}
        </div>
      )}

      {/* Per-dimension grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
        {dims.map(([dim, sc]) => {
          const pass = sc >= QA_FLOOR;
          return (
            <div key={dim} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
              gap: 8, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--line, #e8d2d7)" }}>
              <span style={{ fontSize: 13, textTransform: "capitalize" }}>{prettyDim(dim)}</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 13,
                color: pass ? "#12b48f" : "var(--warn, #C0392B)" }}>
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>
                  {pass ? "check_circle" : "cancel"}
                </span>{sc}
              </span>
            </div>
          );
        })}
      </div>

      {qa.notes.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary className="cs" style={{ cursor: "pointer" }}>Why ({qa.notes.length} note{qa.notes.length === 1 ? "" : "s"})</summary>
          <ul style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: 13, opacity: 0.85 }}>
            {qa.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
