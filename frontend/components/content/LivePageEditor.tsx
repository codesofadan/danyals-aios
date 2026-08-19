"use client";

// ============================================================
// AIOS · Content · LIVE PAGE EDITOR (WYSIWYG in the dashboard)
// Edits the EXACT page a job publishes: the iframe renders the real styled HTML
// (page_model.model_to_html) with every editable text made contentEditable and every
// image swappable, plus a side panel to reorder / show-hide sections. Save persists
// the model; Publish (approve) pushes the SAME model to WordPress as HTML + an
// Elementor tree. The preview IS the published page.
// ============================================================

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PageModelDoc, PageSection } from "@/lib/content";
import { usePageModel, usePreviewPageModel, useSavePageModel } from "@/lib/hooks/content";

// The script injected into the preview iframe: make fields editable, report edits +
// image clicks to the parent. srcDoc is our own trusted renderer output.
const EDITOR_SCRIPT = `
(function(){
  function sid(el){ var s=el.closest('[data-aios-id]'); return s?s.getAttribute('data-aios-id'):''; }
  document.querySelectorAll('[data-aios-field]').forEach(function(el){
    el.setAttribute('contenteditable','true'); el.setAttribute('spellcheck','false');
    el.addEventListener('blur',function(){
      parent.postMessage({t:'edit',id:sid(el),field:el.getAttribute('data-aios-field'),value:el.innerText.trim()},'*');
    });
  });
  document.querySelectorAll('[data-aios-id] img').forEach(function(img){
    img.style.cursor='pointer'; img.title='Click to replace image';
    img.addEventListener('click',function(){ parent.postMessage({t:'image',id:sid(img)},'*'); });
  });
})();
`;

const EDIT_STYLE = `
[data-aios-field]{outline:0;transition:outline .1s}
[data-aios-field]:hover{outline:2px dashed rgba(37,99,235,.45);outline-offset:4px;border-radius:4px}
[data-aios-field]:focus{outline:2px solid #2563eb;outline-offset:4px;border-radius:4px}
[data-aios-id] img:hover{outline:3px solid rgba(37,99,235,.6);outline-offset:2px}
`;

function frameDoc(fragmentHtml: string): string {
  return (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">" +
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" +
    "<style>" + EDIT_STYLE + "</style></head><body>" +
    fragmentHtml +
    "<script>" + EDITOR_SCRIPT + "</script></body></html>"
  );
}

// Apply one field edit to the model (immutably). Field paths: "heading", "subhead",
// "text", "html", "cards.N.title", "faq.N.a", "quotes.N", "steps.N".
function applyEdit(model: PageModelDoc, id: string, field: string, value: string): PageModelDoc {
  const next: PageModelDoc = structuredClone(model);
  const sec = next.sections.find((s) => s.id === id);
  if (!sec) return model;
  if (field === "heading") {
    sec.heading = value;
    return next;
  }
  const parts = field.split(".");
  const d = sec.data as Record<string, unknown>;
  if (parts.length === 1) {
    d[parts[0]] = value;
  } else if (parts.length === 2) {
    const arr = d[parts[0]];
    if (Array.isArray(arr)) arr[Number(parts[1])] = value;
  } else if (parts.length === 3) {
    const arr = d[parts[0]];
    if (Array.isArray(arr) && arr[Number(parts[1])] && typeof arr[Number(parts[1])] === "object") {
      (arr[Number(parts[1])] as Record<string, unknown>)[parts[2]] = value;
    }
  }
  return next;
}

const KIND_LABEL: Record<string, string> = {
  hero: "Hero", benefits: "Benefits", features: "Features", services: "Services",
  process: "How it works", proof: "Proof", stats: "Stats", testimonials: "Testimonials",
  faq: "FAQ", cta: "Call to action", about: "About", trust_bar: "Trust bar", body: "Body",
};
const kindLabel = (s: PageSection) => KIND_LABEL[s.kind] ?? s.kind.replace(/_/g, " ");

export default function LivePageEditor({
  code, onClose, onPublish,
}: {
  code: string;
  onClose: () => void;
  onPublish?: (code: string) => void;
}) {
  const modelQ = usePageModel(code);
  const preview = usePreviewPageModel();
  const save = useSavePageModel();
  const [model, setModel] = useState<PageModelDoc | null>(null);
  const [html, setHtml] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<string>("");
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const modelRef = useRef<PageModelDoc | null>(null);
  modelRef.current = model;

  // Load the model, then render the initial preview.
  useEffect(() => {
    if (modelQ.data && !model) {
      setModel(modelQ.data);
      preview.mutate(modelQ.data, { onSuccess: (r) => setHtml(r.html) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelQ.data]);

  // Re-render the iframe HTML for the CURRENT model (used after structural edits:
  // reorder / hide / image swap). Text edits don't reload (the DOM already shows them).
  const rerender = useCallback((m: PageModelDoc) => {
    preview.mutate(m, { onSuccess: (r) => setHtml(r.html) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Receive edits + image clicks from the iframe.
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      const d = e.data as { t?: string; id?: string; field?: string; value?: string };
      const cur = modelRef.current;
      if (!d || !cur || !d.id) return;
      if (d.t === "edit" && d.field != null) {
        const nextM = applyEdit(cur, d.id, d.field, d.value ?? "");
        setModel(nextM);
        setDirty(true); // text edit: model updated, iframe already shows it (no reload)
      } else if (d.t === "image") {
        const url = window.prompt("New image URL (leave blank to remove):", "");
        if (url === null) return;
        const nextM: PageModelDoc = structuredClone(cur);
        const sec = nextM.sections.find((s) => s.id === d.id);
        if (sec) {
          sec.images = url.trim() ? [{ url: url.trim(), alt: sec.heading || "" }] : [];
          setModel(nextM);
          setDirty(true);
          rerender(nextM);
        }
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [rerender]);

  function mutateModel(fn: (m: PageModelDoc) => void) {
    if (!model) return;
    const next: PageModelDoc = structuredClone(model);
    fn(next);
    setModel(next);
    setDirty(true);
    rerender(next);
  }

  function move(idx: number, dir: -1 | 1) {
    mutateModel((m) => {
      const j = idx + dir;
      if (j < 0 || j >= m.sections.length) return;
      [m.sections[idx], m.sections[j]] = [m.sections[j], m.sections[idx]];
    });
  }
  function toggle(idx: number) {
    mutateModel((m) => { m.sections[idx].visible = !m.sections[idx].visible; });
  }

  function doSave(then?: () => void) {
    if (!model) return;
    save.mutate({ code, model }, {
      onSuccess: () => {
        setDirty(false);
        setSavedAt(new Date().toLocaleTimeString());
        then?.();
      },
    });
  }
  function doPublish() {
    doSave(() => onPublish?.(code));
  }

  const sections = useMemo(() => model?.sections ?? [], [model]);

  return (
    <div className="lpe-overlay" role="dialog" aria-label="Live page editor">
      <div className="lpe">
        <header className="lpe-bar">
          <div className="lpe-title">
            <span className="lpe-dot" /> Live page editor
            <span className="lpe-code">{code}</span>
          </div>
          <div className="lpe-actions">
            <span className="lpe-status">
              {dirty ? "Unsaved changes" : savedAt ? `Saved ${savedAt}` : "Up to date"}
            </span>
            <button className="lpe-btn" onClick={() => doSave()} disabled={save.isPending || !dirty}>
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {onPublish && (
              <button className="lpe-btn lpe-primary" onClick={doPublish} disabled={save.isPending}>
                Save &amp; Publish
              </button>
            )}
            <button className="lpe-btn lpe-ghost" onClick={onClose}>Close</button>
          </div>
        </header>

        <div className="lpe-body">
          <aside className="lpe-side">
            <div className="lpe-side-h">Sections</div>
            <p className="lpe-hint">Click any text in the page to edit it. Click an image to replace it.</p>
            <ul className="lpe-secs">
              {sections.map((s, i) => (
                <li key={s.id} className={s.visible ? "" : "off"}>
                  <span className="lpe-sec-name">{kindLabel(s)}</span>
                  <span className="lpe-sec-tools">
                    <button title="Move up" onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
                    <button title="Move down" onClick={() => move(i, 1)} disabled={i === sections.length - 1}>↓</button>
                    <button title={s.visible ? "Hide" : "Show"} onClick={() => toggle(i)}>
                      {s.visible ? "👁" : "🚫"}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </aside>

          <main className="lpe-canvas">
            {modelQ.isLoading || !html ? (
              <div className="lpe-loading">Loading the page…</div>
            ) : (
              <iframe
                ref={iframeRef}
                className="lpe-frame"
                title="Page preview (editable)"
                sandbox="allow-scripts allow-same-origin"
                srcDoc={frameDoc(html)}
              />
            )}
          </main>
        </div>
      </div>

      <style jsx>{`
        .lpe-overlay { position: fixed; inset: 0; z-index: 60; background: rgba(10, 14, 26, .55);
          backdrop-filter: blur(2px); display: flex; padding: 18px; }
        .lpe { flex: 1; display: flex; flex-direction: column; background: var(--surface, #fff);
          border-radius: 14px; overflow: hidden; box-shadow: 0 30px 80px -20px rgba(0,0,0,.5); }
        .lpe-bar { display: flex; align-items: center; justify-content: space-between;
          padding: 12px 16px; border-bottom: 1px solid var(--line, #e6ebf2); background: var(--surface, #fff); }
        .lpe-title { display: flex; align-items: center; gap: 10px; font-weight: 700; color: var(--head, #0f172a); }
        .lpe-dot { width: 9px; height: 9px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 3px rgba(34,197,94,.2); }
        .lpe-code { font-weight: 500; color: var(--muted, #64748b); font-size: 13px; }
        .lpe-actions { display: flex; align-items: center; gap: 10px; }
        .lpe-status { font-size: 12px; color: var(--muted, #64748b); }
        .lpe-btn { padding: 8px 16px; border-radius: 9px; border: 1px solid var(--line, #e6ebf2);
          background: var(--surface, #fff); color: var(--head, #0f172a); font-weight: 600; font-size: 14px; cursor: pointer; }
        .lpe-btn:disabled { opacity: .5; cursor: default; }
        .lpe-primary { background: #2563eb; color: #fff; border-color: #2563eb; }
        .lpe-ghost { background: transparent; }
        .lpe-body { flex: 1; display: grid; grid-template-columns: 260px 1fr; min-height: 0; }
        .lpe-side { border-right: 1px solid var(--line, #e6ebf2); padding: 14px; overflow: auto; background: var(--surface, #fff); }
        .lpe-side-h { font-weight: 700; color: var(--head, #0f172a); margin-bottom: 6px; }
        .lpe-hint { font-size: 12px; color: var(--muted, #64748b); margin: 0 0 12px; line-height: 1.5; }
        .lpe-secs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
        .lpe-secs li { display: flex; align-items: center; justify-content: space-between; gap: 8px;
          padding: 8px 10px; border: 1px solid var(--line, #e6ebf2); border-radius: 9px; font-size: 13px; }
        .lpe-secs li.off { opacity: .45; }
        .lpe-sec-name { font-weight: 600; color: var(--head, #0f172a); text-transform: capitalize; }
        .lpe-sec-tools { display: flex; gap: 2px; }
        .lpe-sec-tools button { width: 26px; height: 26px; border: 1px solid var(--line, #e6ebf2);
          background: var(--surface, #fff); border-radius: 7px; cursor: pointer; font-size: 13px; line-height: 1; }
        .lpe-sec-tools button:disabled { opacity: .4; cursor: default; }
        .lpe-canvas { background: #f1f5f9; overflow: auto; padding: 18px; }
        .lpe-frame { width: 100%; height: 100%; min-height: 1200px; border: 0; border-radius: 10px;
          background: #fff; box-shadow: 0 10px 40px -12px rgba(15,23,42,.2); }
        .lpe-loading { display: grid; place-items: center; height: 100%; color: var(--muted, #64748b); }
      `}</style>
    </div>
  );
}
