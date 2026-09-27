"use client";

// The questions only the business owner can answer, asked of the business owner.
//
// WHY THIS SCREEN EXISTS. The content pipeline refuses to write a page whose first-party
// facts nobody has supplied — it will not invent a licence number, a van count or the story
// of a job that taught you something. That refusal is the feature. But the facts live in the
// owner's head, and until now the only person who could type them was an agency operator:
// the questions travelled to the client as a message, and the answers travelled back as a
// message, and pages sat held for days in between.
//
// THE SAFETY RULE IS UNCHANGED HERE, and it is the reason a dropdown is allowed at all:
// every option is derived from evidence THIS client already gave us, and each one says where
// it came from. Nothing is generated. Picking is the owner confirming their own fact.
//
// It shares its rendering with the operator's panel (`components/content/experienceForm`) so
// that rule has exactly one implementation. What differs is the framing: an operator is told
// the page is held; the owner is told what their page is waiting for and what happens when
// they answer.

import {
  SlotRow,
  useExperienceDraft,
} from "@/components/content/experienceForm";
import {
  useAnswerClientExperience,
  useClientExperience,
  type PortalAnswer,
} from "@/lib/hooks/portalContent";

const STATUS_COPY: Record<string, { label: string; tone: string; meaning: string }> = {
  not_started: {
    label: "Not asked yet",
    tone: "mut",
    meaning: "This page has not started, so we have not worked out what we need to ask you.",
  },
  empty: {
    label: "Waiting on you",
    tone: "warn",
    meaning: "We have paused this page until you answer the questions below.",
  },
  partial: {
    label: "Partly answered",
    tone: "warn",
    meaning: "Still paused — the page starts again once every question has an answer.",
  },
  complete: {
    label: "All answered",
    tone: "ok",
    meaning: "Everything we needed is here. Your page can be written from these facts.",
  },
};

export default function ClientExperiencePanel({
  code,
  onClose,
}: {
  code: string;
  onClose?: () => void;
}) {
  const q = useClientExperience(code);
  const answer = useAnswerClientExperience(code);
  const { draft, set, pick, chooseOwnWords, filled, payload } = useExperienceDraft(q.data?.slots);

  const data = q.data;
  const status = STATUS_COPY[data?.status ?? "empty"] ?? STATUS_COPY.empty;
  const blank = (data?.slots ?? []).filter((s) => !filled(s)).length;
  const saveErr = answer.error instanceof Error ? answer.error.message : null;

  return (
    <section className="card" style={{ padding: "var(--s-7)" }}>
      <div className="card-h" style={{ padding: 0, marginBottom: 14 }}>
        <div>
          <div className="ct">{data?.topic || code}</div>
          <div className="cs" style={{ marginTop: 4 }}>
            {status.meaning}
          </div>
        </div>
        <div className="tools">
          <span className={`status-pill ${status.tone}`}>{status.label}</span>
          {onClose ? (
            <button type="button" className="ghostbtn" onClick={onClose}>
              Close
            </button>
          ) : null}
        </div>
      </div>

      {q.isLoading ? (
        <div className="pt-empty sm">
          <span className="material-symbols-rounded spin">progress_activity</span>
          <div className="pt-empty-t">Loading your questions…</div>
        </div>
      ) : q.isError ? (
        <div className="pt-empty sm">
          <span className="material-symbols-rounded">error</span>
          <div className="pt-empty-t">Couldn&apos;t load these questions</div>
          <div className="pt-empty-s">There was a problem reaching the server.</div>
          <button
            type="button"
            className="primary-btn sm"
            style={{ marginTop: 12 }}
            onClick={() => q.refetch()}
          >
            <span className="material-symbols-rounded">refresh</span>Retry
          </button>
        </div>
      ) : !data || data.slots.length === 0 ? (
        <div className="pt-empty sm">
          <span className="material-symbols-rounded">quiz</span>
          <div className="pt-empty-t">Nothing to answer</div>
          <div className="pt-empty-s">
            This page has no outstanding questions. If it is still paused, your team is
            looking at it.
          </div>
        </div>
      ) : (
        <>
          <div className="cs" style={{ marginBottom: 16 }}>
            Pick the answer that is true, or write your own. Every option below comes from
            something you have already told us or something already on your site — we never
            invent one. Your page may state these as fact, so please only confirm what you
            can stand behind. If something is not true of your business, choose the option
            that says so and we will not claim it.
          </div>

          {data.slots.map((s) => (
            <SlotRow
              key={s.slotKey}
              slot={s}
              row={draft[s.slotKey]}
              set={set}
              pick={pick}
              chooseOwnWords={chooseOwnWords}
              isFilled={filled(s)}
              textPlaceholder="In your own words — and what backs it up"
              artifactPlaceholder="Or a link to proof — a certificate, a dated photo (optional)"
            />
          ))}

          {saveErr ? (
            <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
              Couldn&apos;t save your answers. {saveErr}.
            </div>
          ) : null}

          {answer.isSuccess && !answer.isPending ? (
            <div className="cs" style={{ color: "var(--ok)", marginBottom: 8 }}>
              {answer.data?.status === "complete"
                ? answer.data?.resumed
                  ? "Saved — your page is being written now."
                  : "Saved. Your page will start again shortly."
                : "Saved. The page starts once the rest are answered."}
            </div>
          ) : null}

          <button
            type="button"
            className="primary-btn"
            onClick={() => answer.mutate(payload() as PortalAnswer[])}
            disabled={answer.isPending}
          >
            {answer.isPending ? "Saving…" : "Save my answers"}
          </button>
          <span className="cs" style={{ marginLeft: 12 }}>
            {blank === 0
              ? "This is everything — saving starts your page."
              : `${blank} still to answer. Your page waits until all of them are done.`}
          </span>
        </>
      )}
    </section>
  );
}
