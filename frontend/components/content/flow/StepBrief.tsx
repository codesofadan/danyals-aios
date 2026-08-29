"use client";

// Screen 3 — the facts the pages are allowed to state, and how they should look.
//
// Proof points are REQUIRED and always were; what was missing was any hint of
// what a usable one looks like. The writer may state these and nothing else, so
// "great service" costs a page its credibility while "412 callouts in 2025, from
// our dispatch log" earns it. The placeholder now teaches that.
//
// Design is a real choice between two real things: measure the client's actual
// site, or pick a template. Extraction wins when it succeeds, and says so.

import { useSiteDesign } from "@/lib/hooks/content";
import { FRAMEWORKS, TEMPLATE_THEME_DEFAULTS, type Framework, type PageTemplate } from "@/lib/content";
import TemplateGallery from "@/components/content/TemplateGallery";
import { useToast, describeError } from "@/components/ui/Toast";
import type { FlowState } from "./types";
import { lines } from "./types";

export default function StepBrief({
  state, patch,
}: {
  state: FlowState;
  patch: (p: Partial<FlowState>) => void;
}) {
  const extract = useSiteDesign();
  const toast = useToast();

  const runExtract = () =>
    extract.mutate(
      { site: state.siteDomain },
      {
        onSuccess: (res) => {
          if (res.status === "ok" && res.profile) {
            patch({ design: res.profile, designFrom: state.siteDomain });
            toast.success("Design measured", `Colours, fonts and section order taken from ${state.siteDomain}.`);
          } else {
            toast.error("Couldn't measure the site", res.reason || "The extractor degraded; a template will be used instead.");
          }
        },
        onError: (e: unknown) => toast.error("Couldn't measure the site", describeError(e)),
      },
    );

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 760 }}>
      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">What can these pages prove?</div>
        <div className="cs" style={{ margin: "4px 0 14px" }}>
          The writer may state these facts and nothing else. Anything vague gets cut rather
          than softened, so a number with a source beats an adjective every time.
        </div>
        <div className="fld">
          <label htmlFor="flow-proof">
            Proof points <span style={{ color: "var(--crit)" }}>*</span>
          </label>
          <textarea
            id="flow-proof" rows={4} value={state.proof}
            onChange={(e) => patch({ proof: e.target.value })}
            placeholder={"412 emergency callouts in 2025, from our dispatch log\nTexas Master Plumber licence M-41982\nMedian on-site time 47 minutes"}
          />
          <div className="fld-hint">
            One per line. {lines(state.proof).length === 0
              ? "At least one is required — pages cannot be written without something to stand on."
              : `${lines(state.proof).length} supplied.`}
          </div>
        </div>
        <div className="fld" style={{ marginTop: 12 }}>
          <label htmlFor="flow-services">Services offered</label>
          <textarea
            id="flow-services" rows={3} value={state.services}
            onChange={(e) => patch({ services: e.target.value })}
            placeholder={"Emergency leak repair\nWater heater replacement\nSlab leak detection"}
          />
        </div>
        <div className="fld-row" style={{ marginTop: 12 }}>
          <div className="fld">
            <label htmlFor="flow-testimonials">Testimonials (optional)</label>
            <textarea
              id="flow-testimonials" rows={3} value={state.testimonials}
              onChange={(e) => patch({ testimonials: e.target.value })}
              placeholder="One per line, with the customer's name if you have it"
            />
          </div>
          <div className="fld">
            <label htmlFor="flow-unique">Anything only you know (optional)</label>
            <textarea
              id="flow-unique" rows={3} value={state.uniqueData}
              onChange={(e) => patch({ uniqueData: e.target.value })}
              placeholder="Original data, internal stats, things competitors cannot say"
            />
          </div>
        </div>
      </section>

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">How should the pages look?</div>
        <div className="cs" style={{ margin: "4px 0 14px" }}>
          Measuring the client&apos;s own site copies its palette, fonts and section order, so
          the new pages match what is already there. One paid call.
        </div>
        {state.design ? (
          <div role="status" style={{ display: "flex", gap: 9, alignItems: "center", color: "var(--ok)", fontSize: 13.5 }}>
            <span className="material-symbols-rounded">check_circle</span>
            Using the measured design from <b>{state.designFrom}</b>.
            <button
              type="button" className="mini-btn" style={{ marginLeft: 8 }}
              onClick={() => patch({ design: null, designFrom: "" })}
            >
              Use a template instead
            </button>
          </div>
        ) : (
          <button
            type="button" className="ghostbtn" onClick={runExtract}
            disabled={extract.isPending || !state.siteDomain}
          >
            <span className="material-symbols-rounded">palette</span>
            {extract.isPending ? "Measuring the site…" : `Measure ${state.siteDomain || "the site"}`}
          </button>
        )}
        {!state.design && (
          <>
            <div className="cs" style={{ margin: "16px 0 10px" }}>
              Or pick a template and tune it. Leave it on Auto to use the blueprint that
              belongs to the page kind you chose.
            </div>
            <TemplateGallery
              value={state.template}
              theme={state.theme}
              onSelect={(tpl) => patch({
                template: tpl,
                // Switching to a NEW template seeds its curated theme; re-picking
                // the same one keeps whatever the operator has customised.
                ...(tpl !== "Auto" && tpl !== state.template
                  ? { theme: TEMPLATE_THEME_DEFAULTS[tpl as PageTemplate] }
                  : {}),
              })}
              onTheme={(theme) => patch({ theme })}
            />
          </>
        )}
      </section>

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">Copywriting framework</div>
        <div className="cs" style={{ margin: "4px 0 12px" }}>
          The persuasive structure the body follows. Auto picks the one that suits the page kind.
        </div>
        <div className="fld" style={{ maxWidth: 260 }}>
          <label htmlFor="flow-framework">Framework</label>
          <select
            id="flow-framework" value={state.framework}
            onChange={(e) => patch({ framework: e.target.value as Framework | "Auto" })}
          >
            <option value="Auto">Auto — choose for me</option>
            {FRAMEWORKS.map((f) => (
              <option key={f.key} value={f.key}>{f.key} — {f.expansion}</option>
            ))}
          </select>
        </div>
      </section>
    </div>
  );
}
