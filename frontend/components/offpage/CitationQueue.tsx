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
import { useClients } from "@/lib/hooks/clients";
import ExtensionCallout from "./ExtensionCallout";
import SpecDrawer from "./SpecDrawer";
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
  const clientsQ = useClients();
  // Seeded from ?client= so the workspace's "Work the queue" links land pre-filtered.
  // Read lazily from window (never useSearchParams: that demands a Suspense boundary
  // at build time, and a missed one is a next-build failure nothing local catches).
  const [clientFilter, setClientFilter] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("client") ?? "";
  });
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
  // Tone travels with the message — the old single-string flash rendered clipboard
  // failures and "queue empty" in the same success green as a verified listing.
  const [flash, setFlashState] = useState<{ tone: "ok" | "warn" | "err"; msg: string } | null>(null);
  function setFlash(tone: "ok" | "warn" | "err", msg: string) {
    setFlashState({ tone, msg });
  }
  const [copied, setCopied] = useState<string | null>(null);
  // The teach-the-bot handoff: set when a completion is ACCEPTED, because at that
  // moment the operator has produced exactly what the earned-whitelist contract
  // demands — a human who saw the live form, and a listing URL the server verified.
  const [teach, setTeach] = useState<{
    directoryId: string; directory: string; addUrl: string; liveUrl: string;
  } | null>(null);
  const [showDrawer, setShowDrawer] = useState(false);

  // Elapsed time on the current item. Ticks locally; banked on every heartbeat and on
  // every exit, so the server total survives a closed tab.
  const [elapsed, setElapsed] = useState(0);
  const bankedRef = useRef(0);

  // RESUME WHAT THIS OPERATOR IS ALREADY HOLDING.
  //
  // The claimed item used to live in `item` alone, set only by the claim mutation's
  // onSuccess. So a reload - or opening the queue on a second screen - showed an
  // empty board while the row stayed claimed server-side for the rest of its
  // twenty-minute lease, and pressing "Take the next item" handed back a DIFFERENT
  // row while the first sat locked. Re-taking the original later incremented
  // `human_attempts`, which reads to the next person as "someone has tried this
  // before and failed".
  //
  // `mine` comes from the board's own poll, so this needs no extra request. Items
  // finished in this session are remembered so a completion is not immediately
  // resumed from a board response that predates it.
  const doneRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (item) return;
    const held = (boardQ.data?.mine ?? []).find((m) => !doneRef.current.has(m.citationId));
    if (!held) return;
    setItem(held);
    // Seed from the server's banked total, or the local tick would restart at zero
    // and the next heartbeat would bank the same seconds twice.
    setElapsed(held.workedSeconds);
    bankedRef.current = held.workedSeconds;
  }, [boardQ.data, item]);

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
    setItem((current) => {
      if (current) doneRef.current.add(current.citationId);
      return null;
    });
    setLiveUrl("");
    setNote("");
    setRefusal(null);
    setShowBlock(false);
    setElapsed(0);
    bankedRef.current = 0;
  }, []);

  function takeNext() {
    claim.mutate(clientFilter || undefined, {
      onSuccess: (next) => {
        reset();
        setItem(next);
        if (!next) setFlash("warn", "Nothing waiting — the queue is empty.");
      },
      onError: (err) => {
        setFlash("err", `Couldn't take an item — ${(err as Error)?.message ?? "try again"}.`);
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
            setFlash("ok", `Live — verified on the page in ${mmss(elapsed)}.`);
            if (item.directoryId) {
              setTeach({
                directoryId: item.directoryId,
                directory: item.directory,
                addUrl: item.addUrl,
                liveUrl: liveUrl.trim(),
              });
            }
            reset();
          } else {
            // NOT an error. The commonest cause is a directory that accepted the
            // submission into moderation and hasn't published yet, in which case "not
            // live yet" is the honest answer and the right move is Release.
            setRefusal(res.reason || "The business wasn't found on that page.");
          }
        },
        onError: (err) => {
          // A thrown failure is different from a refusal: the check itself never ran.
          // The likeliest cause mid-shift is an expired claim lease (the server 409s).
          const msg = (err as Error)?.message ?? "";
          setFlash(
            "err",
            /expired|claim/i.test(msg)
              ? "Your claim on this item expired — it went back to the queue. Take it again."
              : `Couldn't check that URL — ${msg || "try again"}.`,
          );
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
          setFlash("ok", "Recorded as blocked. That's a useful answer — thank you.");
          reset();
        },
        onError: (err) => {
          setFlash("err", `Couldn't record the block — ${(err as Error)?.message ?? "try again"}.`);
        },
      },
    );
  }

  function giveBack() {
    if (!item) return;
    release.mutate(
      { citationId: item.citationId, workedSeconds: unbanked() },
      {
        onSuccess: () => { setFlash("ok", "Item returned to the queue."); reset(); },
        onError: (err) => {
          setFlash("err", `Couldn't put it back — ${(err as Error)?.message ?? "try again"}.`);
        },
      },
    );
  }

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1200);
    } catch {
      setFlash("warn", "Couldn't reach the clipboard — select and copy manually.");
    }
  }

  const board = boardQ.data;

  return (
    <div>
      <ExtensionCallout />
      {flash && <div className={`op-note ${flash.tone === "err" ? "crit" : flash.tone}`}>{flash.msg}</div>}

      {teach && !showDrawer && (
        <div className="op-note ok" style={{ marginBottom: 10 }}>
          <b>Make {teach.directory} automatic next time?</b> You just proved this form by
          hand — record its field selectors (2–3 minutes with the form still open) and the
          bot does this directory for every future client.
          <div className="op-toolset" style={{ marginTop: 8 }}>
            <button className="primary-btn" onClick={() => setShowDrawer(true)}>
              <span className="material-symbols-rounded">school</span>
              Teach the bot
            </button>
            <button className="ghostbtn" onClick={() => setTeach(null)}>Not now</button>
          </div>
        </div>
      )}
      {teach && showDrawer && (
        <SpecDrawer
          directoryId={teach.directoryId}
          directoryName={teach.directory}
          prefillUrl={teach.addUrl}
          firstLiveUrl={teach.liveUrl}
          onClose={() => { setShowDrawer(false); setTeach(null); }}
        />
      )}

      {boardQ.isError && (
        <div className="op-note crit" style={{ marginBottom: 10 }}>
          The queue board couldn&apos;t load — {(boardQ.error as Error)?.message ?? "retry shortly"}.
        </div>
      )}

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
            {board?.medianSeconds != null
              ? mmss(board.medianSeconds)
              : board
                ? "not yet measured"
                : "—"}
          </div>
          <div className={w.statLbl}>Median time per finished item</div>
        </div>
      </div>

      {!item && (
        <div className="op-toolset" style={{ marginTop: 14, flexWrap: "wrap" }}>
          <button className="primary-btn" onClick={takeNext} disabled={claim.isPending}>
            <span className="material-symbols-rounded">play_arrow</span>
            {claim.isPending
              ? "Finding one…"
              : clientFilter
                ? "Take this client's next item"
                : "Take the next item"}
          </button>
          <select
            className="op-input"
            value={clientFilter}
            onChange={(e) => setClientFilter(e.target.value)}
            title="Scope the next claim to one client, or work the whole queue"
          >
            <option value="">Any client</option>
            {(clientsQ.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.cn}</option>
            ))}
          </select>
        </div>
      )}

      {item && (
        <div className={w.step} style={{ marginTop: 14 }}>
          {item.prohibitedWarning && (
            <div className="op-note crit">
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
              <>
                <span className="status-pill warn">attempt {item.humanAttempts}</span>
                <span className="op-muted" style={{ fontSize: 12 }}>
                  someone has tried this before — their note may say why it stalled
                </span>
              </>
            )}
          </div>

          <div className="op-toolset" style={{ marginTop: 10 }}>
            {item.addUrl ? (
              <a className="primary-btn" href={item.addUrl} target="_blank" rel="noreferrer">
                <span className="material-symbols-rounded">open_in_new</span>
                Open the add-listing form
              </a>
            ) : (
              <span className="op-note warn">
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
            <div className="op-note warn" style={{ marginTop: 8 }}>
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
