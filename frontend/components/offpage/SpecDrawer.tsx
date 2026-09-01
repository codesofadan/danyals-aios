"use client";

import { useMemo, useState } from "react";
import {
  useActivateSpec,
  useCreateSpec,
  useSpecBoard,
  useSpecFirstLive,
  useVerifySpec,
} from "@/lib/hooks/offpage";
import type { DirectorySpec, SpecFieldInput } from "@/lib/offpage";

// TEACH THE BOT — the flagship loop. An operator who just finished a directory by
// hand has produced, as a side effect, exactly the two things the earned-whitelist
// contract demands: a human who has SEEN the live form (the DOM check), and a
// submission that produced a public listing URL (first-live). This drawer files that
// evidence through the existing /specs endpoints — draft → verify → first-live →
// activate — and from activation on, the bot does this directory for every future
// client. Queue time becomes permanent automation instead of evaporating.
//
// Every step maps 1:1 to one endpoint; the server's own refusals (the DB CHECK that
// makes activation impossible without both halves) are surfaced verbatim.

const VALUE_KEYS = [
  "business_name", "address_line1", "address_line2", "city", "region",
  "postal_code", "phone", "website_url", "email", "description", "categories",
] as const;

type DraftField = SpecFieldInput & { id: number };

export default function SpecDrawer({
  directoryId,
  directoryName,
  prefillUrl,
  firstLiveUrl,
  onClose,
}: {
  directoryId: string;
  directoryName: string;
  /** The add-listing form the operator just used. */
  prefillUrl: string;
  /** The URL their completion just verified — the first-live candidate. */
  firstLiveUrl: string;
  onClose: () => void;
}) {
  const boardQ = useSpecBoard();
  const createSpec = useCreateSpec();
  const verify = useVerifySpec();
  const firstLive = useSpecFirstLive();
  const activate = useActivateSpec();

  // Resume an in-progress teach: the newest spec for this directory, if any.
  const existing: DirectorySpec | undefined = useMemo(
    () => (boardQ.data?.specs ?? []).find((sp) => sp.directoryId === directoryId && !sp.active),
    [boardQ.data, directoryId],
  );
  const activeAlready = useMemo(
    () => (boardQ.data?.specs ?? []).some((sp) => sp.directoryId === directoryId && sp.active),
    [boardQ.data, directoryId],
  );

  const [specId, setSpecId] = useState<string>("");
  const spec = specId
    ? (boardQ.data?.specs ?? []).find((sp) => sp.id === specId) ?? existing
    : existing;

  const [url, setUrl] = useState(prefillUrl);
  const [submitSelector, setSubmitSelector] = useState("");
  const [successIndicator, setSuccessIndicator] = useState("");
  const [liveUrl, setLiveUrl] = useState(firstLiveUrl);
  const [fields, setFields] = useState<DraftField[]>([
    { id: 1, selector: "", valueKey: "business_name" },
  ]);
  const [err, setErr] = useState<string>("");

  function fail(prefix: string) {
    return (e: unknown) => setErr(`${prefix} — ${(e as Error)?.message ?? "try again"}.`);
  }

  const canDraft =
    url.trim().length > 0 &&
    submitSelector.trim().length > 0 &&
    fields.some((f) => f.selector.trim() && f.valueKey);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">Teach the bot — {directoryName}</div>
            <div className="modal-s">
              You just proved this form by hand. Record its selectors and the bot does{" "}
              {directoryName} for every future client. Draft → verify → first live →
              activate; the server refuses anything unearned.
            </div>
          </div>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        <div className="wiz-body">
          {err && <div className="op-note crit">{err}</div>}

          {activeAlready && (
            <div className="op-note ok">
              {directoryName} already has an ACTIVE spec — the bot takes it from here.
              Nothing more to teach.
            </div>
          )}

          {!activeAlready && !spec && (
            <>
              <div className="fld">
                <label>The add-listing form this spec drives</label>
                <input className="op-input" value={url} onChange={(e) => setUrl(e.target.value)} />
              </div>
              <div className="fld">
                <label>Fields — the CSS selector each canonical value goes into</label>
                {fields.map((f) => (
                  <div key={f.id} className="op-toolset" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                    <input
                      className="op-input"
                      style={{ flex: 1, minWidth: 220 }}
                      placeholder='e.g. input[name="company"]'
                      value={f.selector}
                      onChange={(e) =>
                        setFields((fs) => fs.map((x) => (x.id === f.id ? { ...x, selector: e.target.value } : x)))
                      }
                    />
                    <select
                      className="op-input"
                      value={f.valueKey}
                      onChange={(e) =>
                        setFields((fs) => fs.map((x) => (x.id === f.id ? { ...x, valueKey: e.target.value } : x)))
                      }
                    >
                      {VALUE_KEYS.map((k) => (
                        <option key={k} value={k}>{k}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="ghostbtn"
                      onClick={() => setFields((fs) => fs.filter((x) => x.id !== f.id))}
                      aria-label="Remove field"
                    >
                      <span className="material-symbols-rounded">close</span>
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="ghostbtn"
                  style={{ marginTop: 6 }}
                  onClick={() => setFields((fs) => [...fs, { id: Date.now(), selector: "", valueKey: "phone" }])}
                >
                  <span className="material-symbols-rounded">add</span> Add a field
                </button>
              </div>
              <div className="fld">
                <label>Submit button selector</label>
                <input
                  className="op-input"
                  placeholder='e.g. button[type="submit"]'
                  value={submitSelector}
                  onChange={(e) => setSubmitSelector(e.target.value)}
                />
              </div>
              <div className="fld">
                <label>Success indicator (optional — text or selector the thank-you page shows)</label>
                <input
                  className="op-input"
                  placeholder="e.g. text=Thanks for your submission"
                  value={successIndicator}
                  onChange={(e) => setSuccessIndicator(e.target.value)}
                />
              </div>
              <button
                className="primary-btn"
                disabled={!canDraft || createSpec.isPending}
                onClick={() => {
                  setErr("");
                  createSpec.mutate(
                    {
                      directoryId,
                      url: url.trim(),
                      fields: fields
                        .filter((f) => f.selector.trim())
                        .map(({ selector, valueKey }) => ({ selector: selector.trim(), valueKey })),
                      submitSelector: submitSelector.trim(),
                      successIndicator: successIndicator.trim(),
                    },
                    {
                      onSuccess: (row) => setSpecId(row.id),
                      onError: fail("Couldn't save the draft"),
                    },
                  );
                }}
              >
                {createSpec.isPending ? "Saving…" : "Save draft (inactive — it has earned nothing yet)"}
              </button>
            </>
          )}

          {!activeAlready && spec && (
            <>
              <div className="op-muted" style={{ whiteSpace: "normal" }}>
                Draft on file: <b>{spec.fieldCount} field(s)</b> against <code>{spec.url}</code>.
                {spec.blocking.length > 0 && (
                  <> Still blocking activation: <b>{spec.blocking.join(" · ")}</b>.</>
                )}
              </div>

              {!spec.verified ? (
                <div className="fld">
                  <div className="op-note warn">
                    <b>The verification is a signed, dated, write-once statement.</b> Press
                    it only with the live form open, having compared each selector against
                    the real page. It cannot be edited later — a new revision is a new spec.
                  </div>
                  <button
                    className="primary-btn"
                    style={{ marginTop: 8 }}
                    disabled={verify.isPending}
                    onClick={() => {
                      setErr("");
                      verify.mutate(
                        { specId: spec.id },
                        { onError: fail("Couldn't record the verification") },
                      );
                    }}
                  >
                    {verify.isPending ? "Recording…" : "I checked these selectors against the live form"}
                  </button>
                </div>
              ) : !spec.hasFirstLiveUrl ? (
                <div className="fld">
                  <label>
                    The public listing URL this form produced (the server probes it before
                    recording)
                  </label>
                  <input
                    className="op-input"
                    value={liveUrl}
                    onChange={(e) => setLiveUrl(e.target.value)}
                  />
                  <button
                    className="primary-btn"
                    style={{ marginTop: 8 }}
                    disabled={!liveUrl.trim() || firstLive.isPending}
                    onClick={() => {
                      setErr("");
                      firstLive.mutate(
                        { specId: spec.id, liveUrl: liveUrl.trim() },
                        { onError: fail("The server wouldn't record that URL") },
                      );
                    }}
                  >
                    {firstLive.isPending ? "Probing…" : "Record the live listing it produced"}
                  </button>
                </div>
              ) : (
                <button
                  className="primary-btn"
                  disabled={activate.isPending}
                  onClick={() => {
                    setErr("");
                    activate.mutate(spec.id, {
                      onSuccess: onClose,
                      onError: fail("Activation refused"),
                    });
                  }}
                >
                  {activate.isPending
                    ? "Activating…"
                    : `Activate — the bot takes ${directoryName} from now on`}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
