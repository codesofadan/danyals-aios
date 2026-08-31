"use client";

// The Experience questionnaire — the only thing that can clear a halted page.
//
// The doctrine pipeline refuses to draft a page whose first-party facts nobody
// has supplied. That refusal is the system working, not a failure: it is what
// stops the writer inventing credentials, callout counts and review scores. It
// writes the questions it needs and stops, and until this screen existed there
// was nowhere to answer them, so a halted page stayed halted forever.
//
// The copy here does one job above all: make it obvious that a vague answer is
// worse than none. The gate wants a checkable artifact — a number with a source,
// a licence with an issuer, a dated photo — because that is what the draft is
// allowed to state as fact.

import { useEffect, useState } from "react";
import {
  useAnswerExperience,
  useExperience,
  type ExperienceAnswer,
  type ExperienceSlot,
} from "@/lib/hooks/content";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import { useToast, describeError } from "@/components/ui/Toast";

const STATUS_COPY: Record<string, { label: string; tone: string; meaning: string }> = {
  not_started: {
    label: "Not asked yet", tone: "mut",
    meaning: "This page has not run, so the pipeline has not worked out what it needs to know.",
  },
  empty: {
    label: "Nothing answered", tone: "warn",
    meaning: "The page is held until every question below has an answer.",
  },
  partial: {
    label: "Partly answered", tone: "warn",
    meaning: "Still held — the page resumes only when every question is answered.",
  },
  complete: {
    label: "Complete", tone: "ok",
    meaning: "Every question is answered; the page can be written from these facts.",
  },
};

export default function ExperiencePanel({ code }: { code: string }) {
  const q = useExperience(code);
  const answer = useAnswerExperience(code);
  const toast = useToast();
  const [draft, setDraft] = useState<Record<string, { answer: string; artifactUrl: string }>>({});

  // Seed the form from the server once, then let edits live locally until save.
  useEffect(() => {
    if (!q.data) return;
    setDraft((prev) =>
      Object.keys(prev).length
        ? prev
        : Object.fromEntries(
            q.data!.slots.map((s) => [s.slotKey, { answer: s.answer, artifactUrl: s.artifactUrl }]),
          ),
    );
  }, [q.data]);

  const set = (key: string, field: "answer" | "artifactUrl", value: string) =>
    setDraft((d) => ({ ...d, [key]: { ...(d[key] ?? { answer: "", artifactUrl: "" }), [field]: value } }));

  const filled = (s: ExperienceSlot) => {
    const d = draft[s.slotKey];
    return Boolean((d?.answer ?? "").trim() || (d?.artifactUrl ?? "").trim());
  };

  const submit = () => {
    const payload: ExperienceAnswer[] = Object.entries(draft).map(([slot_key, v]) => ({
      slot_key,
      answer: v.answer,
      artifact_url: v.artifactUrl,
    }));
    answer.mutate(payload, {
      onSuccess: (fresh) => {
        if (fresh.status === "complete") {
          toast.success(
            fresh.resumed ? "Answers saved — writing resumed" : "Answers saved",
            fresh.resumed
              ? "Every question is answered, so the page went back into the pipeline."
              : "Every question is answered, but the page could not be re-queued — the job queue looks unreachable. Your answers are saved; retry from the job when it is back.",
          );
        } else {
          const left = fresh.slots.filter((s) => !s.answered).length;
          toast.success("Answers saved", `${left} still to answer before this page can be written.`);
        }
      },
      onError: (e: unknown) => toast.error("Couldn't save the answers", describeError(e)),
    });
  };

  return (
    <QueryGuard queries={[q]} label="the Experience questions" minHeight={200}>
      {q.data && (
        <section className="card" style={{ padding: "var(--s-7)", maxWidth: 760 }}>
          <div className="card-h" style={{ padding: 0, marginBottom: 14 }}>
            <div>
              <div className="ct">First-party experience</div>
              <div className="cs" style={{ marginTop: 4 }}>
                {(STATUS_COPY[q.data.status] ?? STATUS_COPY.empty).meaning}
              </div>
            </div>
            <span className={`status-pill ${(STATUS_COPY[q.data.status] ?? STATUS_COPY.empty).tone}`}>
              {(STATUS_COPY[q.data.status] ?? STATUS_COPY.empty).label}
            </span>
          </div>

          {q.data.status === "not_started" || q.data.slots.length === 0 ? (
            <EmptyState
              icon="quiz"
              title="No questions yet"
              hint="The pipeline works out what it needs to know on its first run. Once this page starts, its questions appear here."
            />
          ) : (
            <>
              <div className="cs" style={{ marginBottom: 16 }}>
                Answer with something checkable — a number and where it comes from, a licence
                and who issued it, a dated photo you own. The draft may state these as fact and
                nothing else, so a vague answer is worse than leaving it blank.
              </div>

              {q.data.slots.map((s) => (
                <div key={s.slotKey} style={{ marginBottom: 18, paddingBottom: 16, borderBottom: "1px solid var(--line)" }}>
                  <label style={{ display: "flex", gap: 8, alignItems: "baseline", fontWeight: 700, fontSize: 13.5, color: "var(--ink)" }}>
                    <span
                      className="material-symbols-rounded"
                      style={{ fontSize: 17, color: filled(s) ? "var(--ok)" : "var(--muted)" }}
                      aria-hidden="true"
                    >
                      {filled(s) ? "check_circle" : "radio_button_unchecked"}
                    </span>
                    <span>{s.question || s.slotKey}</span>
                  </label>
                  <textarea
                    rows={2}
                    style={{ marginTop: 8, width: "100%" }}
                    value={draft[s.slotKey]?.answer ?? ""}
                    onChange={(e) => set(s.slotKey, "answer", e.target.value)}
                    placeholder="The fact, and what backs it up"
                    aria-label={s.question || s.slotKey}
                  />
                  <input
                    style={{ marginTop: 6, width: "100%" }}
                    value={draft[s.slotKey]?.artifactUrl ?? ""}
                    onChange={(e) => set(s.slotKey, "artifactUrl", e.target.value)}
                    placeholder="Or a link to the proof — a document, a dated photo (optional)"
                    aria-label={`${s.question || s.slotKey} — link to proof`}
                  />
                </div>
              ))}

              <button type="button" className="primary-btn" onClick={submit} disabled={answer.isPending}>
                {answer.isPending ? "Saving…" : "Save answers"}
              </button>
              <span className="cs" style={{ marginLeft: 12 }}>
                {q.data.slots.filter((s) => !filled(s)).length === 0
                  ? "Saving this resumes the page."
                  : `${q.data.slots.filter((s) => !filled(s)).length} still blank — the page stays held until all are answered.`}
              </span>
            </>
          )}
        </section>
      )}
    </QueryGuard>
  );
}
