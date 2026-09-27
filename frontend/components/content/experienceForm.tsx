"use client";

// The Experience questionnaire's shared parts — one definition of how a first-party fact
// is asked for, and of how its PROVENANCE is shown.
//
// WHY THIS IS SHARED AND NOT COPIED. Two audiences answer these questions: an operator on
// the admin screen, and the business owner themselves in the client portal. Their framing
// differs, their data hooks differ (staff `/content/experience` vs client-scoped
// `/portal/experience`), and almost nothing else does. The part that must NOT diverge is
// the rule that makes a pickable answer safe in the first place:
//
//   EVERY OPTION IS DERIVED FROM EVIDENCE THIS CLIENT ALREADY GAVE US — a prior answer for
//   another cluster, the proof points supplied for this build, their business record, their
//   own site copy — and each one states where it came from. Nothing is generated. Picking
//   is the answerer CONFIRMING their own fact; a list of plausible-sounding sentences would
//   be exactly the fabrication the gate exists to stop, wearing a click.
//
// If that rule were expressed twice, one copy would eventually render an option without its
// provenance, and a guessed sentence would become indistinguishable from an attested one.

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

/** One pickable answer, and the words that say where it came from. */
export type OptionLike = { value: string; evidence: string; kind: string };

/** One proof question, structurally what both the staff and portal payloads carry. */
export type SlotLike = {
  slotKey: string;
  question: string;
  answer: string;
  artifactUrl: string;
  answered: boolean;
  source?: string;
  answerEvidence?: string;
  answeredOn?: string;
  options?: OptionLike[];
};

/** The free-text sentinel: not an option, the absence of one. */
export const OWN_WORDS = "__own_words__";

/** What each kind of option IS, in the answerer's language. */
export const KIND_COPY: Record<string, string> = {
  prior: "you told us this before",
  supplied: "from what you supplied",
  record: "from your record",
  site: "from your own site",
  artifact: "you'll attach it",
  decline: "we won't claim it",
};

export const KIND_TONE: Record<string, string> = {
  prior: "var(--ok)",
  supplied: "var(--ok)",
  record: "var(--ok)",
  site: "var(--ok)",
  artifact: "var(--muted)",
  decline: "var(--warn)",
};

export type DraftRow = { answer: string; artifactUrl: string; evidence: string; picked: string };

/** The answer payload both endpoints accept (snake_case on the wire, by contract). */
export type AnswerPayload = {
  slot_key: string;
  answer?: string;
  artifact_url?: string;
  answer_evidence?: string;
};

/**
 * The local edit state for one page's questions.
 *
 * Seeded from the server ONCE and then owned locally until save, so a poll landing
 * mid-typing cannot overwrite what the answerer is writing. An answer already stored is
 * shown as free text rather than matched back to an option: it IS the answer, and
 * re-deriving which option produced it would be a guess.
 */
export function useExperienceDraft(slots: SlotLike[] | undefined) {
  const [draft, setDraft] = useState<Record<string, DraftRow>>({});

  useEffect(() => {
    if (!slots) return;
    setDraft((prev) =>
      Object.keys(prev).length
        ? prev
        : Object.fromEntries(
            slots.map((s) => [
              s.slotKey,
              {
                answer: s.answer,
                artifactUrl: s.artifactUrl,
                evidence: s.answerEvidence ?? "",
                picked: s.answer ? OWN_WORDS : "",
              },
            ]),
          ),
    );
  }, [slots]);

  const set = (key: string, patch: Partial<DraftRow>) =>
    setDraft((d) => {
      // The empty row is the BASE, then whatever is already there, then the patch. Written
      // as a variable rather than inline so the defaults cannot read as being overwritten
      // by the spread that follows them.
      const base: DraftRow = { answer: "", artifactUrl: "", evidence: "", picked: "" };
      return { ...d, [key]: { ...base, ...(d[key] ?? {}), ...patch } };
    });

  const pick = (slot: SlotLike, option: OptionLike) =>
    set(slot.slotKey, {
      picked: option.value,
      answer: option.value,
      // The provenance travels with the answer: it is what separates a confirmed fact from
      // a plausible-looking sentence when somebody audits this in six months.
      evidence: option.evidence,
    });

  const chooseOwnWords = (slot: SlotLike) =>
    set(slot.slotKey, { picked: OWN_WORDS, answer: "", evidence: "" });

  const filled = (slot: SlotLike) => {
    const row = draft[slot.slotKey];
    return Boolean((row?.answer ?? "").trim() || (row?.artifactUrl ?? "").trim());
  };

  const payload = (): AnswerPayload[] =>
    Object.entries(draft).map(([slot_key, v]) => ({
      slot_key,
      answer: v.answer,
      artifact_url: v.artifactUrl,
      answer_evidence: v.evidence,
    }));

  return { draft, set, pick, chooseOwnWords, filled, payload };
}

/**
 * One question: what is already attested, the options derived from this client's own
 * evidence, free text for anything a list cannot carry, and an optional link to proof.
 */
export function SlotRow({
  slot,
  row,
  set,
  pick,
  chooseOwnWords,
  isFilled,
  textPlaceholder = "The fact, and what backs it up",
  artifactPlaceholder = "Or a link to the proof — a document, a dated photo (optional)",
  footer,
}: {
  slot: SlotLike;
  row: DraftRow | undefined;
  set: (key: string, patch: Partial<DraftRow>) => void;
  pick: (slot: SlotLike, option: OptionLike) => void;
  chooseOwnWords: (slot: SlotLike) => void;
  isFilled: boolean;
  textPlaceholder?: string;
  artifactPlaceholder?: string;
  footer?: ReactNode;
}) {
  const options = slot.options ?? [];
  // No options at all means extraction found nothing about this client for this question,
  // and free text is then the ONLY honest input — so it is shown, not hidden behind a
  // choice the answerer cannot make.
  const showText = row?.picked === OWN_WORDS || options.length === 0;

  return (
    <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: "1px solid var(--line)" }}>
      <label
        style={{
          display: "flex",
          gap: 8,
          alignItems: "baseline",
          fontWeight: 700,
          fontSize: 13.5,
          color: "var(--ink)",
        }}
      >
        <span
          className="material-symbols-rounded"
          style={{ fontSize: 17, color: isFilled ? "var(--ok)" : "var(--muted)" }}
          aria-hidden="true"
        >
          {isFilled ? "check_circle" : "radio_button_unchecked"}
        </span>
        <span>{slot.question || slot.slotKey}</span>
      </label>

      {/* The attestation already on record, when there is one. */}
      {slot.answered && slot.answeredOn ? (
        <div className="cs" style={{ marginTop: 4, marginLeft: 25 }}>
          Answered {slot.answeredOn}
          {slot.source === "client" ? " by the client" : ""}
          {slot.answerEvidence ? ` — ${slot.answerEvidence}` : ""}
        </div>
      ) : null}

      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => pick(slot, o)}
            aria-pressed={row?.picked === o.value}
            style={{
              textAlign: "left",
              cursor: "pointer",
              padding: "9px 12px",
              borderRadius: 10,
              background: "transparent",
              border: `1px solid ${row?.picked === o.value ? "var(--ok)" : "var(--line)"}`,
              boxShadow: row?.picked === o.value ? "inset 0 0 0 1px var(--ok)" : "none",
            }}
          >
            <span style={{ fontSize: 13.5, color: "var(--ink)" }}>{o.value}</span>
            <span
              className="cs"
              style={{ display: "block", marginTop: 2, color: KIND_TONE[o.kind] ?? "var(--muted)" }}
            >
              {KIND_COPY[o.kind] ?? o.kind} — {o.evidence}
            </span>
          </button>
        ))}

        {options.length > 0 && (
          <button
            type="button"
            onClick={() => chooseOwnWords(slot)}
            aria-pressed={row?.picked === OWN_WORDS}
            style={{
              textAlign: "left",
              cursor: "pointer",
              padding: "9px 12px",
              borderRadius: 10,
              background: "transparent",
              border: `1px dashed ${row?.picked === OWN_WORDS ? "var(--ok)" : "var(--line)"}`,
            }}
          >
            <span style={{ fontSize: 13.5, color: "var(--ink)" }}>
              None of these — I&rsquo;ll write it
            </span>
            <span className="cs" style={{ display: "block", marginTop: 2 }}>
              For anything a list cannot carry
            </span>
          </button>
        )}
      </div>

      {showText && (
        <textarea
          rows={2}
          style={{ marginTop: 8, width: "100%" }}
          value={row?.answer ?? ""}
          onChange={(e) => set(slot.slotKey, { answer: e.target.value, evidence: "" })}
          placeholder={textPlaceholder}
          aria-label={slot.question || slot.slotKey}
        />
      )}

      <input
        style={{ marginTop: 6, width: "100%" }}
        value={row?.artifactUrl ?? ""}
        onChange={(e) => set(slot.slotKey, { artifactUrl: e.target.value })}
        placeholder={artifactPlaceholder}
        aria-label={`${slot.question || slot.slotKey} — link to proof`}
      />

      {footer}
    </div>
  );
}
