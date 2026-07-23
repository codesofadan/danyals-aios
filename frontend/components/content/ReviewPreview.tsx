"use client";

// ============================================================
// AIOS · content Review PREVIEW (Wave 5)
// A framed, embedded HTML preview of a draft on the Review surface. Fetches the
// server-only draft markdown (GET /content/jobs/{code}/draft), renders it to HTML
// inside a sandboxed <iframe srcDoc> so it reads like the published page, and - for a
// published job - surfaces the LIVE post URL with an "open live post" test action.
// (The live URL rides on the wire-visible `stage` label: "Published: <url>".)
// ============================================================

import { useContentDraft } from "@/lib/hooks/content";
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

export default function ReviewPreview({
  job, onAction, onClose,
}: {
  job: ContentJob;
  onAction: (id: string, action: ReviewAction) => void;
  onClose: () => void;
}) {
  const draftQ = useContentDraft(job.id);
  const md = draftQ.data?.draft ?? "";
  const liveUrl = liveUrlFromStage(job);
  const inReview = job.status === "needs_review";

  return (
    <section className="card co-preview-card" style={{ marginTop: 12 }}>
      <div className="card-h">
        <div>
          <div className="ct">Draft preview · {job.id}</div>
          <div className="cs">
            {PAGE_LABEL[job.pageType]} · {job.framework} · {job.words.toLocaleString()} words ·{" "}
            {job.schema || "no schema"} · {job.images} image{job.images === 1 ? "" : "s"}
          </div>
        </div>
        <div className="tools">
          <button className="ghostbtn" onClick={onClose} aria-label="Close preview">
            <span className="material-symbols-rounded">close</span>Close
          </button>
        </div>
      </div>

      {/* Published banner + the live-URL "open" test action (deliverable 4). */}
      {job.status === "done" && (
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
      )}

      {/* The framed HTML preview. */}
      {draftQ.isLoading ? (
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
      )}

      {/* Review actions (only meaningful while the job awaits review). */}
      {inReview && (
        <div className="co-gate-actions" style={{ marginTop: 12 }}>
          <button className="primary-btn co-approve" onClick={() => onAction(job.id, "approve")}>
            <span className="material-symbols-rounded">check</span>Approve &amp; publish
          </button>
          <button className="ghostbtn" onClick={() => onAction(job.id, "edit")}>
            <span className="material-symbols-rounded">edit</span>Request edit
          </button>
          <button className="ghostbtn co-reject" onClick={() => onAction(job.id, "reject")}>
            <span className="material-symbols-rounded">close</span>Reject
          </button>
        </div>
      )}
    </section>
  );
}
