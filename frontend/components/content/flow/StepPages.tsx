"use client";

// Screen 2 — which pages to build.
//
// Three ways in, because an agency genuinely works all three ways: pick from
// keywords already researched, run fresh research, or add a page you already know
// you want. The first of those is new - the keyword bank and its clusters existed
// with volume, difficulty and intent, and the content flow could not see any of
// it. Six of the keyword module's nine endpoints had no caller at all.
//
// Every row shows what it is chosen ON: volume, difficulty, intent. A page picked
// without those is a guess, and guesses are what the bank exists to end.

import { useMemo, useState } from "react";
import { useKeywordBank, useKeywordClusters, type BankKeyword } from "@/lib/hooks/keywords";
import { useContentResearch } from "@/lib/hooks/content";
import { DIFFICULTY_META, type ResearchItem } from "@/lib/content";
import { pageKind } from "@/lib/pageKinds";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import { useToast, describeError } from "@/components/ui/Toast";
import type { FlowState } from "./types";

type Source = "bank" | "research" | "manual";

const itemFromKeyword = (k: BankKeyword, kindKey: string): ResearchItem => ({
  title: k.keyword,
  pageType: pageKind(kindKey).pageType,
  primaryKeyword: k.keyword,
  secondaryKeywords: [],
  estVolume: k.volume,
  difficulty: k.difficulty <= 30 ? "easy" : k.difficulty <= 60 ? "medium" : "hard",
  rationale: `From the keyword bank — ${k.volume ? `${k.volume.toLocaleString()}/mo, ` : ""}difficulty ${k.difficulty}${k.cluster ? `, cluster "${k.cluster}"` : ""}.`,
  city: k.geo || "",
  service: "",
});

export default function StepPages({
  state, patch,
}: {
  state: FlowState;
  patch: (p: Partial<FlowState>) => void;
}) {
  const [source, setSource] = useState<Source>("bank");
  const [manual, setManual] = useState("");
  const [count, setCount] = useState("");
  const toast = useToast();

  const bankQ = useKeywordBank(state.clientId || null, source === "bank");
  const clustersQ = useKeywordClusters(state.clientId || null, source === "bank");
  const research = useContentResearch();

  const chosen = useMemo(() => new Set(state.picks.map((p) => p.title)), [state.picks]);
  const toggle = (item: ResearchItem) =>
    patch({
      picks: chosen.has(item.title)
        ? state.picks.filter((p) => p.title !== item.title)
        : [...state.picks, item],
    });

  const runResearch = () => {
    const n = parseInt(count, 10);
    research.mutate(
      {
        site: state.siteDomain,
        contentType: pageKind(state.kind).research,
        count: Number.isFinite(n) && n > 0 ? n : undefined,
      },
      {
        onSuccess: (r) => {
          if (r.status === "degraded") {
            toast.error("Research didn't run", researchFix(r.reason));
            return;
          }
          patch({ picks: [...state.picks, ...r.items.filter((i) => !chosen.has(i.title))] });
          toast.success(`${r.items.length} pages recommended`, "All selected — untick any you don't want.");
        },
        onError: (e: unknown) => toast.error("Research failed", describeError(e)),
      },
    );
  };

  const bank = bankQ.data ?? [];
  const clusters = clustersQ.data ?? [];
  const byCluster = useMemo(() => {
    const m = new Map<string, BankKeyword[]>();
    for (const k of bank) {
      const key = k.cluster || "Unclustered";
      m.set(key, [...(m.get(key) ?? []), k]);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [bank]);

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 860 }}>
      <div className="co-chips wrap" role="tablist" aria-label="Where the pages come from">
        {([["bank", "Keyword bank"], ["research", "Run research"], ["manual", "Add by hand"]] as const).map(
          ([key, label]) => (
            <button
              key={key} type="button" role="tab" aria-selected={source === key}
              className={source === key ? "chip on" : "chip"}
              onClick={() => setSource(key)}
            >
              {label}
            </button>
          ),
        )}
        <span className="cs" style={{ alignSelf: "center", marginLeft: 8 }}>
          {state.picks.length} page{state.picks.length === 1 ? "" : "s"} selected
        </span>
      </div>

      {source === "bank" && (
        <QueryGuard queries={[bankQ, clustersQ]} label="the keyword bank" minHeight={160}>
          {bank.length === 0 ? (
            <EmptyState
              icon="travel_explore"
              title="Nothing researched for this client yet"
              hint="Run research on this screen, or use the Search workspace to build the bank first."
            />
          ) : (
            <section className="card" style={{ padding: "var(--s-7)" }}>
              <div className="ct">
                {bank.length} keywords{clusters.length ? ` in ${clusters.length} cluster${clusters.length === 1 ? "" : "s"}` : ""}
              </div>
              <div className="cs" style={{ margin: "4px 0 14px" }}>
                Tick the ones worth their own page. Difficulty and volume come from the
                provider; a keyword with difficulty 0 was not scored, not scored as easy.
              </div>
              {byCluster.map(([cluster, rows]) => (
                <div key={cluster} style={{ marginBottom: 18 }}>
                  <div style={{ fontWeight: 700, fontSize: 12, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 6 }}>
                    {cluster} · {rows.length}
                  </div>
                  <div className="tbl-wrap">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th style={{ width: 34 }}><span className="sr-only">Select</span></th>
                          <th>Keyword</th>
                          <th className="num">Volume</th>
                          <th className="num">Difficulty</th>
                          <th>Intent</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((k) => {
                          const item = itemFromKeyword(k, state.kind);
                          return (
                            <tr key={k.code}>
                              <td>
                                <input
                                  type="checkbox"
                                  checked={chosen.has(item.title)}
                                  onChange={() => toggle(item)}
                                  aria-label={`Build a page for ${k.keyword}`}
                                />
                              </td>
                              <td>{k.keyword}</td>
                              <td className="num">{k.volume ? k.volume.toLocaleString() : "—"}</td>
                              <td className="num">{k.difficulty ? k.difficulty : "—"}</td>
                              <td>{k.intent || "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </section>
          )}
        </QueryGuard>
      )}

      {source === "research" && (
        <section className="card" style={{ padding: "var(--s-7)" }}>
          <div className="ct">Research {state.siteDomain || "the site"}</div>
          <div className="cs" style={{ margin: "4px 0 14px" }}>
            Claude reads the live SERP for this site&apos;s market and recommends a page set.
            A paid call, metered against the content budget.
          </div>
          <div className="fld-row">
            <div className="fld" style={{ maxWidth: 190 }}>
              <label htmlFor="flow-count">How many pages</label>
              <input
                id="flow-count" inputMode="numeric" value={count}
                onChange={(e) => setCount(e.target.value.replace(/[^0-9]/g, ""))}
                placeholder="Let it decide"
              />
            </div>
          </div>
          <button
            type="button" className="primary-btn" style={{ marginTop: 12 }}
            onClick={runResearch} disabled={research.isPending || !state.siteDomain}
            title={state.siteDomain ? undefined : "Research needs a site to measure against"}
          >
            <span className="material-symbols-rounded">travel_explore</span>
            {research.isPending ? "Researching…" : "Recommend pages"}
          </button>
          {/* Say why, rather than leaving a grey button. Research measures the
              client's site against the SERP, so it genuinely needs a domain -
              unlike the rest of the flow, which no longer does. */}
          {!state.siteDomain && (
            <div className="cs" style={{ marginTop: 8 }}>
              No site chosen on screen 1, so there is nothing to research against. Go
              back and pick one, or add the pages you want by hand below.
            </div>
          )}
        </section>
      )}

      {source === "manual" && (
        <section className="card" style={{ padding: "var(--s-7)" }}>
          <div className="ct">Add a page you already know you want</div>
          <div className="cs" style={{ margin: "4px 0 14px" }}>
            The title doubles as the target keyword, so write it as the thing people search.
          </div>
          <div className="fld-row">
            <div className="fld" style={{ flex: 3 }}>
              <label htmlFor="flow-manual">Page title / target keyword</label>
              <input
                id="flow-manual" value={manual}
                onChange={(e) => setManual(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && manual.trim()) {
                    e.preventDefault();
                    addManual();
                  }
                }}
                placeholder="emergency plumber in Lakewood"
              />
            </div>
            <button type="button" className="ghostbtn" onClick={addManual} disabled={!manual.trim()}>
              <span className="material-symbols-rounded">add</span>Add page
            </button>
          </div>
        </section>
      )}

      {state.picks.length > 0 && (
        <section className="card" style={{ padding: "var(--s-7)" }}>
          <div className="ct">Selected — {state.picks.length}</div>
          <div className="tbl-wrap" style={{ marginTop: 10 }}>
            <table className="tbl">
              <tbody>
                {state.picks.map((p) => (
                  <tr key={p.title}>
                    <td>{p.title}</td>
                    <td className="num">{p.estVolume ? `${p.estVolume.toLocaleString()}/mo` : "—"}</td>
                    <td>
                      <span className={`status-pill ${DIFFICULTY_META[p.difficulty]?.cls ?? "mut"}`}>
                        {DIFFICULTY_META[p.difficulty]?.label ?? p.difficulty}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button" className="mini-btn"
                        onClick={() => patch({ picks: state.picks.filter((x) => x.title !== p.title) })}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );

  function addManual() {
    const t = manual.trim();
    if (!t || chosen.has(t)) return;
    patch({
      picks: [...state.picks, {
        title: t, pageType: pageKind(state.kind).pageType, primaryKeyword: t,
        secondaryKeywords: [], estVolume: 0, difficulty: "medium",
        rationale: "Added by hand", city: "", service: "",
      }],
    });
    setManual("");
  }
}

/** The operator-actionable reason a research run produced nothing. */
function researchFix(reason: string): string {
  if (reason === "provider_out_of_credit")
    return "The AI provider account is out of credit. Top it up, then try again — nothing was charged.";
  if (reason === "provider_key_rejected")
    return "The AI provider key was rejected. Replace it in the key vault.";
  if (reason === "provider_rate_limited")
    return "The provider is rate-limiting us. Wait a minute and try again.";
  if (reason.startsWith("cost_gate:"))
    return `Your own spend controls blocked it (${reason.replace("cost_gate:", "")}). Check Cost Controls.`;
  return `The provider call failed${reason ? ` (${reason})` : ""}. You can still pick from the bank or add pages by hand.`;
}
