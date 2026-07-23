"use client";

// ============================================================
// AIOS · ReportViewer — the in-dashboard audit-report page-viewer
// Renders the SAME self-contained report.html the backend delivers as a PDF
// (the PDF is rendered from this exact HTML), so what the operator/client reads
// on screen matches the download page for page. Shared by the staff audit view,
// the public free-audit funnel, and the client portal — the three differ only in
// how they obtain the HTML string (the `load` prop) and how the PDF downloads.
//
// Pagination: the report is a print-CSS (A4 @page) flowing document, so there are
// no discrete page elements to step between. We render it once into a sandboxed
// srcdoc iframe (no scripts; `allow-same-origin` only, so the report can do
// nothing but the parent can measure it), then WINDOW it: the iframe is laid out
// at full height and scaled to fit, and Next/Prev shift it by exactly one A4 page
// height inside a clipping stage — a PDF-style flip through the report's pages.
// ============================================================

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styles from "./ReportViewer.module.css";

// A4 at 96dpi. The iframe is laid out at this logical width (matching the PDF's
// page box) and scaled to the available width; the clip window is one page tall.
const A4_W = 794;
const A4_H = 1123;

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; html: string }
  | { kind: "error"; message: string };

export type ReportViewerProps = {
  /** Fetch the report HTML (caller owns auth: bearer for staff/portal, token URL for public). */
  load: () => Promise<string>;
  /** A short label for the toolbar (e.g. the domain or client name). */
  label?: string;
  /** When set, the viewer renders as a full-screen overlay with a close control. */
  onClose?: () => void;
  /** When set, shows a "Download PDF" button wired to this handler (bearer-authed callers). */
  onDownloadPdf?: () => void;
  /** A direct PDF href (public funnel) — an alternative to onDownloadPdf. */
  pdfHref?: string;
  /** Re-run `load` when this value changes (e.g. the selected audit id). */
  reloadKey?: string;
};

export default function ReportViewer({
  load,
  label,
  onClose,
  onDownloadPdf,
  pdfHref,
  reloadKey,
}: ReportViewerProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [page, setPage] = useState(0);
  const [pageCount, setPageCount] = useState(1);
  const [scale, setScale] = useState(1);
  const [docHeight, setDocHeight] = useState(A4_H);

  const stageWrapRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);

  // Fetch the report HTML (and re-fetch when the target changes).
  useEffect(() => {
    let alive = true;
    setState({ kind: "loading" });
    setPage(0);
    load()
      .then((html) => {
        if (alive) setState({ kind: "ready", html });
      })
      .catch((err: unknown) => {
        if (alive)
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "The report could not be loaded.",
          });
      });
    return () => {
      alive = false;
    };
  }, [load, reloadKey]);

  // Measure the laid-out document once the srcdoc finishes loading, and derive the
  // page count. Reading contentDocument needs same-origin, which srcdoc +
  // allow-same-origin grants; the report carries no scripts so nothing else runs.
  const measure = useCallback(() => {
    const frame = frameRef.current;
    const doc = frame?.contentDocument;
    if (!doc) return;
    // Lock the inner document's own scroll — we window it from the parent.
    doc.documentElement.style.overflow = "hidden";
    const h = Math.max(
      doc.documentElement.scrollHeight,
      doc.body ? doc.body.scrollHeight : 0,
      A4_H,
    );
    setDocHeight(h);
    setPageCount(Math.max(1, Math.ceil(h / A4_H)));
  }, []);

  // Fit the A4-wide page into the available width (never upscale past 1:1).
  useEffect(() => {
    const wrap = stageWrapRef.current;
    if (!wrap || typeof ResizeObserver === "undefined") return;
    const apply = () => {
      const avail = wrap.clientWidth;
      if (avail > 0) setScale(Math.min(1, avail / A4_W));
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [state.kind]);

  const clampPage = useCallback(
    (n: number) => Math.max(0, Math.min(pageCount - 1, n)),
    [pageCount],
  );
  const goPrev = useCallback(() => setPage((p) => clampPage(p - 1)), [clampPage]);
  const goNext = useCallback(() => setPage((p) => clampPage(p + 1)), [clampPage]);

  // Keyboard: arrows page, Escape closes (overlay only).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "ArrowRight") goNext();
      else if (e.key === "Escape" && onClose) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goPrev, goNext, onClose]);

  // Keep the page in range if the count shrinks after a re-measure.
  useEffect(() => setPage((p) => Math.min(p, pageCount - 1)), [pageCount]);

  const stageStyle = useMemo(
    () => ({ width: A4_W * scale, height: A4_H * scale }),
    [scale],
  );
  const frameStyle = useMemo(
    () => ({
      width: A4_W,
      height: docHeight,
      transform: `scale(${scale})`,
      transformOrigin: "top left",
      top: -(page * A4_H * scale),
    }),
    [scale, docHeight, page],
  );

  const body = (
    <div className={styles.viewer}>
      <div className={styles.toolbar}>
        <div className={styles.title}>
          <span className="material-symbols-rounded" aria-hidden>
            description
          </span>
          <span className={styles.titleText}>{label ?? "Audit report"}</span>
        </div>
        <div className={styles.pager}>
          <button
            type="button"
            className={styles.pgBtn}
            onClick={goPrev}
            disabled={state.kind !== "ready" || page <= 0}
            aria-label="Previous page"
          >
            <span className="material-symbols-rounded" aria-hidden>
              chevron_left
            </span>
          </button>
          <span className={styles.pgLabel}>
            {state.kind === "ready" ? `Page ${page + 1} / ${pageCount}` : "—"}
          </span>
          <button
            type="button"
            className={styles.pgBtn}
            onClick={goNext}
            disabled={state.kind !== "ready" || page >= pageCount - 1}
            aria-label="Next page"
          >
            <span className="material-symbols-rounded" aria-hidden>
              chevron_right
            </span>
          </button>
        </div>
        <div className={styles.actions}>
          {onDownloadPdf && (
            <button type="button" className={styles.dlBtn} onClick={onDownloadPdf}>
              <span className="material-symbols-rounded" aria-hidden>
                download
              </span>
              PDF
            </button>
          )}
          {pdfHref && !onDownloadPdf && (
            <a className={styles.dlBtn} href={pdfHref} download rel="noopener noreferrer">
              <span className="material-symbols-rounded" aria-hidden>
                download
              </span>
              PDF
            </a>
          )}
          {onClose && (
            <button
              type="button"
              className={styles.closeBtn}
              onClick={onClose}
              aria-label="Close report"
            >
              <span className="material-symbols-rounded" aria-hidden>
                close
              </span>
            </button>
          )}
        </div>
      </div>

      <div className={styles.stageWrap} ref={stageWrapRef}>
        {state.kind === "loading" && (
          <div className={styles.note}>
            <span className={`material-symbols-rounded ${styles.spin}`} aria-hidden>
              progress_activity
            </span>
            Loading report…
          </div>
        )}
        {state.kind === "error" && (
          <div className={styles.note}>
            <span className="material-symbols-rounded" aria-hidden>
              error
            </span>
            Report view is not available for this audit.
            {(pdfHref || onDownloadPdf) && " Try the PDF download instead."}
          </div>
        )}
        {state.kind === "ready" && (
          <div className={styles.stage} style={stageStyle}>
            <iframe
              ref={frameRef}
              className={styles.frame}
              style={frameStyle}
              srcDoc={state.html}
              sandbox="allow-same-origin"
              title={label ?? "Audit report"}
              onLoad={measure}
            />
          </div>
        )}
      </div>
    </div>
  );

  if (onClose) {
    return (
      <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Audit report">
        {body}
      </div>
    );
  }
  return body;
}
