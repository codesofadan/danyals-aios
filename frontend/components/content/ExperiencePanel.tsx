"use client";

// The Experience questionnaire — the only thing that can clear a halted page.
//
// The doctrine pipeline refuses to draft a page whose first-party facts nobody has
// supplied. That refusal is the system working, not a failure: it is what stops the writer
// inventing credentials, callout counts and review scores.
//
// WHAT CHANGED, 2026-09-26 (the operator's decision). This used to be seven empty
// textareas, and a business owner asked to write seven paragraphs abandons the form — so
// pages sat held and the module's best safety property read as its worst friction. Each
// question now arrives with PICKABLE OPTIONS, every one derived from evidence this client
// already gave us and labelled with where it came from. The rule that makes that safe, and
// the rendering of it, live in `experienceForm.tsx` — shared with the client portal, which
// asks the same questions of the business owner directly.
//
// This file is the OPERATOR's framing of it: the page is held, here is what it is waiting
// for, and saving a complete set resumes it.

import {
  OWN_WORDS,
  SlotRow,
  useExperienceDraft,
} from "@/components/content/experienceForm";
import {
  useAnswerExperience,
  useExperience,
  type ExperienceAnswer,
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
  const { draft, set, pick, chooseOwnWords, filled, payload } = useExperienceDraft(q.data?.slots);

  const submit = () => {
    answer.mutate(payload() as ExperienceAnswer[], {
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

  const status = (code: string) => STATUS_COPY[code] ?? STATUS_COPY.empty;
  const blank = (q.data?.slots ?? []).filter((s) => !filled(s)).length;

  return (
    <QueryGuard queries={[q]} label="the Experience questions" minHeight={200}>
      {q.data && (
        <section className="card" style={{ padding: "var(--s-7)", maxWidth: 820 }}>
          <div className="card-h" style={{ padding: 0, marginBottom: 14 }}>
            <div>
              <div className="ct">First-party experience</div>
              <div className="cs" style={{ marginTop: 4 }}>
                {status(q.data.status).meaning}
              </div>
            </div>
            <span className={`status-pill ${status(q.data.status).tone}`}>
              {status(q.data.status).label}
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
                Pick the answer that is true, or write your own. Every option below comes from
                something the client already gave us — we never guess one. The draft may state
                these as fact and nothing else, so an answer that is not checkable is worse
                than none.
              </div>

              {q.data.slots.map((s) => (
                <SlotRow
                  key={s.slotKey}
                  slot={s}
                  row={draft[s.slotKey]}
                  set={set}
                  pick={pick}
                  chooseOwnWords={chooseOwnWords}
                  isFilled={filled(s)}
                />
              ))}

              <button type="button" className="primary-btn" onClick={submit} disabled={answer.isPending}>
                {answer.isPending ? "Saving…" : "Save answers"}
              </button>
              <span className="cs" style={{ marginLeft: 12 }}>
                {blank === 0
                  ? "Saving this resumes the page."
                  : `${blank} still blank — the page stays held until all are answered.`}
              </span>
            </>
          )}
        </section>
      )}
    </QueryGuard>
  );
}

// Re-exported so the sentinel has one definition even for callers that only touch this
// screen (a second literal would drift the moment either side changed it).
export { OWN_WORDS };
