"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  QUEUE_BLOCK_LABEL,
  type QueueBlockReason,
  type QueueItem,
} from "@/lib/offpage";
import {
  useBlockQueueItem,
  useCitationQueue,
  useClaimQueueItem,
  useCompleteQueueItem,
  useQueueHeartbeat,
  useReleaseQueueItem,
} from "@/lib/hooks/offpage";
import w from "./Wave4.module.css";

// The operator's working surface. Two numbers govern the cost of a live citation: what
// an aggregator charges per submission, and how many MINUTES a person spends on one by
// hand. This screen exists to shrink the second and, for the first time, to measure it —
// every second on an item is banked server-side, and the board shows the running median.
//
// The design rule throughout: the operator should never have to look anything up. The
// deep link, every field value, and the reason it needs a human are all here before they
// open the tab.

const HEARTBEAT_MS = 60_000;

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function CitationQueue() {
  const boardQ = useCitationQueue();
  const claim = useClaimQueueItem();
  const complete = useCompleteQueueItem();
  const block = useBlockQueueItem();
  const release = useReleaseQueueItem();
  const heartbeat = useQueueHeartbeat();

  const [item, setItem] = useState<QueueItem | null>(null);
  const [liveUrl, setLiveUrl] = useState("");
  const [note, setNote] = useState("");
  const [blockReason, setBlockReason] = useState<QueueBlockReason>("captcha_wall");
  const [showBlock, setShowBlock] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  // Elapsed time on the current item. Ticks locally; banked on every heartbeat and on
  // every exit, so the server total survives a closed tab.
  const [elapsed, setElapsed] = useState(0);
  const bankedRef = useRef(0);

  useEffect(() => {
    if (!item) return;
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [item]);

  useEffect(() => {
    if (!item) return;
    const t = setInterval(() => {
      const unbanked = elapsed - bankedRef.current;
      if (unbanked <= 0) return;
      bankedRef.current = elapsed;
      heartbeat.mutate({ citationId: item.citationId, workedSeconds: unbanked });
    }, HEARTBEAT_MS);
    return () => clearInterval(t);
  }, [item, elapsed, heartbeat]);

  const reset = useCallback(() => {
    setItem(null);
    setLiveUrl("");
    setNote("");
    setRefusal(null);
    setShowBlock(false);
    setElapsed(0);
    bankedRef.current = 0;
  }, []);

  function takeNext() {
    claim.mutate(undefined, {
      onSuccess: (next) => {
        reset();
        setItem(next);
        if (!next) setFlash("Nothing waiting — the queue is empty.");
      },
    });
  }

  function unbanked(): number {
    return Math.max(0, elapsed - bankedRef.current);
  }

  function submit() {
    if (!item || !liveUrl.trim()) return;
    setRefusal(null);
    complete.mutate(
      { citationId: item.citationId, liveUrl: liveUrl.trim(), workedSeconds: unbanked(), note },
      {
        onSuccess: (res) => {
          if (res.accepted) {
            setFlash(`Live — verified on the page in ${mmss(elapsed)}.`);
            reset();
          } else {
            // NOT an error. The commonest cause is a directory that accepted the
            // submission into moderation and hasn't published yet, in which case "not
            // live yet" is the honest answer and the right move is Release.
            setRefusal(res.reason || "The business wasn't found on that page.");
          }
        },
      },
    );
  }

  function reportBlocked() {
    if (!item) return;
    block.mutate(
      { citationId: item.citationId, reason: blockReason, detail: note, workedSeconds: unbanked() },
      {
        onSuccess: () => {
          setFlash("Recorded as blocked. That's a useful answer — thank you.");
          reset();
        },
      },
    );
  }

  function giveBack() {
    if (!item) return;
    release.mutate(
      { citationId: item.citationId, workedSeconds: unbanked() },
      { onSuccess: () => { setFlash("Item returned to the queue."); reset(); } },
    );
  }

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1200);
    } catch {
      setFlash("Couldn't reach the clipboard — select and copy manually.");
    }
  }

  const board = boardQ.data;

  return (
    <div>
      {flash && <div className={w.napFlash}>{flash}</div>}

      <div className={w.stats}>
        <div className={w.stat}>
          <div className={w.statNum}>{board?.waiting ?? "—"}</div>
          <div className={w.statLbl}>Waiting for a human</div>
        </div>
        <div className={w.stat}>
          <div className={w.statNum}>{board?.inProgress ?? "—"}</div>
          <div className={w.statLbl}>Being worked now</div>
        </div>
        <div className={w.stat}>
          <div className={w.statNum}>
            {board?.medianSeconds != null ? mmss(board.medianSeconds) : "not yet measured"}
          </div>
          <div className={w.statLbl}>Median time per finished item</div>
        </div>
      </div>

      {!item && (
        <div className="op-toolset" style={{ marginTop: 14 }}>
          <button className="primary-btn" onClick={takeNext} disabled={claim.isPending}>
            <span className="material-symbols-rounded">play_arrow</span>
            {claim.isPending ? "Finding one…" : "Take the next item"}
          </button>
        </div>
      )}

      {item && (
        <div className={w.step} style={{ marginTop: 14 }}>
          {item.prohibitedWarning && (
            <div className="status-pill op-crit" style={{ display: "block", padding: 12 }}>
              <b>Do not submit.</b> {item.prohibitedWarning}
            </div>
          )}

          <div className={w.stepH} style={{ flexWrap: "wrap" }}>
            <span className="material-symbols-rounded">assignment</span>
            {item.directory} · {item.client}
            <span className="op-muted" style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums" }}>
              {mmss(elapsed)} on this item
            </span>
          </div>

          <div className={w.rollup}>
            <span>Why it needs a person: <b>{item.queuedBecause}</b></span>
            {item.humanAttempts > 1 && (
              <span className="status-pill warn">
                Attempt {item.humanAttempts} — someone has tried this before
              </span>
            )}
          </div>

          <div className="op-toolset" style={{ marginTop: 10 }}>
            {item.addUrl ? (
              <a className="primary-btn" href={item.addUrl} target="_blank" rel="noreferrer">
                <span className="material-symbols-rounded">open_in_new</span>
                Open the add-listing form
              </a>
            ) : (
              <span className="status-pill warn">
                No verified add-listing URL on file — start from{" "}
                <a className="op-url" href={`https://${item.directoryUrl}`} target="_blank" rel="noreferrer">
                  {item.directoryUrl}
                </a>
              </span>
            )}
          </div>

          <div className="op-muted" style={{ marginTop: 12 }}>
            Every value is ready — click to copy:
          </div>
          <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
            {item.fields.map((f) => (
              <button
                key={f.key}
                className="ghostbtn"
                onClick={() => copy(f.value, f.key)}
                style={{ display: "flex", justifyContent: "space-between", gap: 12, textAlign: "left" }}
                title="Copy"
              >
                <span className="op-muted" style={{ minWidth: 120 }}>{f.label}</span>
                <span style={{ flex: 1 }}>{f.value}</span>
                <span className="material-symbols-rounded">
                  {copied === f.key ? "check" : "content_copy"}
                </span>
              </button>
            ))}
          </div>

          <div className={w.stepH} style={{ marginTop: 16 }}>
            <span className={w.stepN}>✓</span> Finish
          </div>
          <div className="op-muted" style={{ marginBottom: 6 }}>
            Paste the listing&apos;s public URL. We fetch it and check the business is
            actually on the page before marking it live.
          </div>
          <input
            className="op-input"
            style={{ width: "100%" }}
            placeholder="https://directory.example/biz/…"
            value={liveUrl}
            onChange={(e) => { setLiveUrl(e.target.value); setRefusal(null); }}
          />

          {refusal && (
            <div className="status-pill warn" style={{ display: "block", marginTop: 8, padding: 10 }}>
              <b>Not accepted yet:</b> {refusal}
              <div style={{ marginTop: 4 }} className="op-muted">
                If the directory hasn&apos;t published it yet, that&apos;s normal — put the
                item back and it will be picked up again.
              </div>
            </div>
          )}

          <textarea
            className="op-input"
            style={{ width: "100%", marginTop: 8, minHeight: 60 }}
            placeholder="Anything worth knowing next time? (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />

          <div className="op-toolset" style={{ marginTop: 10, flexWrap: "wrap" }}>
            <button
              className="primary-btn"
              onClick={submit}
              disabled={!liveUrl.trim() || complete.isPending || !!item.prohibitedWarning}
            >
              <span className="material-symbols-rounded">check_circle</span>
              {complete.isPending ? "Checking the page…" : "Verify & mark live"}
            </button>
            <button className="ghostbtn" onClick={() => setShowBlock((v) => !v)}>
              <span className="material-symbols-rounded">block</span>
              Can&apos;t do this one
            </button>
            <button className="ghostbtn" onClick={giveBack} disabled={release.isPending}>
              <span className="material-symbols-rounded">undo</span>
              Put it back
            </button>
          </div>

          {showBlock && (
            <div className={w.napBlock} style={{ marginTop: 10 }}>
              <div className="op-muted">
                What stopped you? This is a useful answer — it&apos;s how a directory
                earns its way off the list.
              </div>
              <select
                className="op-input"
                style={{ marginTop: 6 }}
                value={blockReason}
                onChange={(e) => setBlockReason(e.target.value as QueueBlockReason)}
              >
                {(Object.keys(QUEUE_BLOCK_LABEL) as QueueBlockReason[]).map((r) => (
                  <option key={r} value={r}>{QUEUE_BLOCK_LABEL[r]}</option>
                ))}
              </select>
              <button
                className="primary-btn"
                style={{ marginTop: 8 }}
                onClick={reportBlocked}
                disabled={block.isPending}
              >
                Record it and move on
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
