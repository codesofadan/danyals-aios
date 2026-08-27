"use client";

// A pipeline's stages, visible.
//
// The content worker streams fourteen named stages (research → cluster →
// serp_format → fan_out → winnability → teardown → outline → draft →
// titles_meta → doctrine → schema → images → assemble → qa) and the UI showed
// a single status pill - the owner's words: "seeing the actual processes...
// these are not matching". This renders what ran, what is running, and what
// has not started, so a job in flight is a sequence you can watch instead of
// a word you wait on.
//
// HONESTY RULE: a stage the payload does not mention renders as UNKNOWN, not
// as done. The timeline reports the worker's account, it does not embellish it.

export type StageState = "done" | "running" | "pending" | "failed";

export type Stage = {
  key: string;
  label: string;
  state: StageState;
  /** One line about what the stage produced ("6 SERP pulls, cached", "score 87"). */
  detail?: string;
};

const STATE_META: Record<StageState, { icon: string; colour: string }> = {
  done: { icon: "check_circle", colour: "var(--ok)" },
  running: { icon: "autorenew", colour: "var(--violet)" },
  pending: { icon: "radio_button_unchecked", colour: "var(--muted-2)" },
  failed: { icon: "error", colour: "var(--crit)" },
};

export default function StageTimeline({ stages }: { stages: Stage[] }) {
  return (
    <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {stages.map((s, i) => {
        const meta = STATE_META[s.state];
        const last = i === stages.length - 1;
        return (
          <li key={s.key} style={{ display: "flex", gap: "var(--s-5)" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <span
                className={`material-symbols-rounded${s.state === "running" ? " rp-spin" : ""}`}
                aria-hidden="true"
                style={{ fontSize: 20, color: meta.colour }}
              >
                {meta.icon}
              </span>
              {!last ? (
                <span
                  aria-hidden="true"
                  style={{
                    width: 2,
                    flex: 1,
                    minHeight: "var(--s-6)",
                    background: s.state === "done" ? "var(--ok)" : "var(--line)",
                    opacity: s.state === "done" ? 0.5 : 1,
                  }}
                />
              ) : null}
            </div>
            <div style={{ paddingBottom: last ? 0 : "var(--s-6)" }}>
              <div
                style={{
                  fontSize: "var(--fs-sm)",
                  fontWeight: s.state === "running" ? 800 : 600,
                  color: s.state === "pending" ? "var(--muted)" : "var(--ink)",
                }}
              >
                {s.label}
                <span className="sr-only">
                  {s.state === "done" ? " (completed)"
                    : s.state === "running" ? " (running now)"
                    : s.state === "failed" ? " (failed)" : " (not started)"}
                </span>
              </div>
              {s.detail ? (
                <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)", marginTop: 2 }}>
                  {s.detail}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
