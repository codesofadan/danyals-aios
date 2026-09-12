/**
 * The operator's panel. Renders state and sends messages; it never calls the API and
 * never holds the token — that lives in the service worker, one process away from the
 * directory's own JavaScript.
 *
 * The panel is a SEPARATE DOCUMENT with its own lifetime: it dies when closed and is
 * rebuilt when reopened. So it holds no durable state either — every open re-asks the
 * worker what is going on.
 */

import type {
  CompleteResult,
  ConnectionReport,
  FillOutcome,
  PanelRequest,
  PanelResponse,
  PlacementCompleteResult,
  QueueBoard,
  QueueItem,
  SessionClientCount,
  SessionTaskCard,
  Web2PlacementTaskCard,
} from "../lib/messages";
import { type ActiveSession, sessionKind } from "../lib/sessionBoard";
import {
  clientSummary,
  clientsForLane,
  type Lane,
  LANE_BLURB,
  LANE_LABEL,
  LANES,
  laneToSessionKind,
  laneWorkCount,
  readLane,
  sessionKindToLane,
  writeLane,
} from "../lib/lanes";
import { needsGrant, originPattern } from "../lib/origins";

const root = document.getElementById("root") as HTMLElement;

const BLOCK_REASONS: Record<string, string> = {
  captcha_wall: "CAPTCHA I couldn't clear",
  account_required: "Needs an account we don't have",
  paid_only: "Paid listing only",
  form_changed: "The form isn't what we expected",
  duplicate_listing: "Already listed",
  directory_dead: "Directory is dead / not accepting",
  phone_verification: "Wants to phone the business",
  postcard_verification: "Wants to post a card to the business",
  other: "Something else (see note)",
};

let item: QueueItem | null = null;
let lastFill: FillOutcome | null = null;
let flash = "";
/** The chosen tab. Restored from `storage.local` at boot (see `lanes.ts`), so an
 *  operator working one lane is not dropped back onto the other every reopen. */
let lane: Lane = "citation";

async function send(request: PanelRequest): Promise<PanelResponse> {
  return (await chrome.runtime.sendMessage(request)) as PanelResponse;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, props: Partial<HTMLElementTagNameMap[K]> = {}, ...kids: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
}

function mmss(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

// --------------------------------------------------------------------------- //
// Pairing.
// --------------------------------------------------------------------------- //
/**
 * Ensure this extension may talk to the dashboard the operator typed.
 *
 * localhost is already in `host_permissions`, so it needs no prompt - and asking
 * for it anyway would put a permission dialog in front of every developer. Any
 * other origin is requested once and remembered by Chrome.
 *
 * Returns false when the operator declines or the URL is unusable, so the caller
 * can say what happened rather than pairing into an origin every request will fail
 * against.
 */
async function ensureOriginPermission(apiBase: string): Promise<boolean> {
  let pattern: string;
  try {
    pattern = originPattern(apiBase);
  } catch {
    return false;
  }
  if (!needsGrant(pattern)) return true;
  try {
    if (await chrome.permissions.contains({ origins: [pattern] })) return true;
    return await chrome.permissions.request({ origins: [pattern] });
  } catch {
    return false;
  }
}

/**
 * Ensure this extension may INJECT into a directory's page before a Fill / Autofill.
 *
 * A directory host (2findlocal.com, brownbook.net…) is in `optional_host_permissions`,
 * NOT granted by default, so `chrome.scripting.executeScript` throws until the operator
 * grants it — which is exactly the "I clicked Autofill and nothing happened" symptom:
 * the inject failed and the service worker had no permission to report about. The grant
 * MUST be requested from THIS user gesture (a service worker cannot prompt), so callers
 * make this the first await in the click handler. Returns true when injection may
 * proceed (already granted, just granted, or no host to reason about → let activeTab
 * try). An empty URL is treated as "proceed" so a task with no add URL still attempts.
 */
async function ensureInjectPermission(pageUrl: string): Promise<boolean> {
  if (!pageUrl) return true;
  let pattern: string;
  try {
    pattern = originPattern(pageUrl);
  } catch {
    return true; // an unparseable URL is not a reason to block — let the inject try
  }
  if (!needsGrant(pattern)) return true;
  try {
    if (await chrome.permissions.contains({ origins: [pattern] })) return true;
    return await chrome.permissions.request({ origins: [pattern] });
  } catch {
    return false;
  }
}

/** One actionable sentence per verdict — the whole point of the diagnostic. */
function diagnosisCopy(report: ConnectionReport, base: string): string {
  switch (report.verdict) {
    case "server_unreachable":
      return (
        `Nothing answered at ${base}. Is the backend running? Copy the exact API ` +
        "address from the dashboard's Settings → Extension page rather than typing one from memory."
      );
    case "ipv6_localhost_trap":
      return (
        `"localhost" didn't answer, but the same server DOES answer at ${report.detail}. ` +
        "Pair with that address — on this machine, localhost points first at an address the server doesn't listen on."
      );
    case "cors_refused":
      return (
        "The server is up, but Chrome blocked this extension from calling it. Two fixes to try: " +
        "press Reload on this extension in chrome://extensions (a stale build keeps old permissions), " +
        `and have an admin allow-list this device on the server: EXTENSION_ORIGINS=chrome-extension://${report.extensionId} ` +
        "in backend/.env, then restart the API."
      );
    case "token_rejected":
      return (
        "The server answered: that token is missing, mistyped, expired, or revoked. Tokens last " +
        "one shift by design — mint a fresh one under Settings → Extension and paste the whole aop_… string."
      );
    case "scope_or_role_refused":
      return `The server refused this token's permissions: ${report.detail || "no detail given"}.`;
    case "server_error":
      return `The server answered with an error: ${report.detail || "no detail given"}.`;
    case "connected":
      return "Connection is good — try pairing again.";
  }
}

function renderPairing(message = "", baseValue = ""): void {
  root.replaceChildren();
  root.append(el("h1", { textContent: "Pair this device" }));
  if (message) root.append(el("div", { className: "note bad", textContent: message }));
  root.append(
    el("p", {
      className: "muted",
      textContent:
        "Create a token in the dashboard under Settings → Extension and copy the API address " +
        "shown beside it. The token only reaches the citation queue and expires after one shift.",
    }),
  );
  const base = el("input", {
    value: baseValue || "http://127.0.0.1:8000",
    placeholder: "API address — copy it from Settings → Extension",
  });
  const token = el("input", { placeholder: "aop_…", type: "password" });
  const go = el("button", { className: "primary", textContent: "Pair" });
  go.onclick = async () => {
    go.disabled = true;
    // Loopback (localhost / 127.0.0.1, any port) is granted by the manifest. Pairing
    // against the deployed dashboard - the only place a real operator's queue lives -
    // needs a runtime grant drawn from optional_host_permissions, and Chrome only
    // shows that prompt inside a user gesture, which this click is.
    const granted = await ensureOriginPermission(base.value);
    if (!granted) {
      go.disabled = false;
      renderPairing(
        "This device needs permission to reach that dashboard. Press Pair again and " +
          "choose Allow, or pair against http://127.0.0.1:8000 while developing.",
        base.value,
      );
      return;
    }
    const res = await send({ type: "pair", token: token.value, apiBase: base.value });
    if (res.ok) { flash = "Paired."; void refresh(); return; }
    go.disabled = false;
    if (res.needsPairing) {
      // The pair call itself came back 401 — the token is the problem, say so.
      renderPairing(
        "The server answered: that token is missing, mistyped, expired, or revoked. " +
          "Mint a fresh one under Settings → Extension.",
        base.value,
      );
      return;
    }
    if (res.diagnosis) {
      renderPairing(diagnosisCopy(res.diagnosis, base.value.trim()), base.value);
      return;
    }
    renderPairing(res.error, base.value);
  };
  root.append(el("div", { className: "row" }, base), el("div", { className: "row" }, token), el("div", { className: "row" }, go));

  // The one fact only this side can know: the identity the server's allow-list needs.
  // Rendered click-to-copy so "paste your extension ID" is never a chrome:// scavenger hunt.
  const idLine = el("p", {
    className: "muted",
    textContent: `This device: chrome-extension://${chrome.runtime.id} — click to copy`,
    style: "cursor: pointer;" as never,
  });
  idLine.onclick = () => void navigator.clipboard.writeText(`chrome-extension://${chrome.runtime.id}`);
  root.append(el("hr"), idLine);
}

// --------------------------------------------------------------------------- //
// The queue.
// --------------------------------------------------------------------------- //
/**
 * The tab bar. Present on every board and on an open session, because an operator has
 * to be able to see which lane they are in without reading the task cards.
 *
 * `lockedTo` is passed when a session is open: that lane's tab is marked current and
 * the other is DISABLED with the reason on it, rather than hidden. Hiding it would
 * read as "Web 2.0 is gone"; disabling it says "finish this session first", which is
 * the actual rule — a session is a server-side lease over specific tasks, and starting
 * a second lane's session would leave the first one's tabs orphaned.
 */
function renderTabs(active: Lane, lockedTo: Lane | null = null): HTMLElement {
  const bar = el("nav", { className: "tabs" });
  for (const l of LANES) {
    const current = l === active;
    const locked = lockedTo !== null && l !== lockedTo;
    const tab = el("button", {
      className: `tab${current ? " tab-on" : ""}`,
      textContent: LANE_LABEL[l],
      disabled: locked,
      title: locked
        ? `A ${LANE_LABEL[lockedTo!]} session is open — close it to switch lane.`
        : LANE_BLURB[l],
    });
    tab.setAttribute("aria-current", current ? "page" : "false");
    if (!current && !locked) {
      tab.onclick = async () => {
        lane = l;
        await writeLane(l);
        void refresh();
      };
    }
    bar.append(tab);
  }
  return bar;
}

function renderBoard(board: QueueBoard): void {
  root.replaceChildren();
  root.append(el("h1", { textContent: "AIOS Extension" }));
  root.append(renderTabs(lane));
  if (flash) { root.append(el("div", { className: "note", textContent: flash })); flash = ""; }

  // The citation queue's own numbers belong to the citation lane only. Showing them
  // above a Web 2.0 board would attribute directory work to placements.
  if (lane === "citation") {
    root.append(
      el("p", {
        className: "muted",
        textContent:
          `${board.waiting} waiting · ${board.inProgress} in progress · median ` +
          (board.medianSeconds != null ? mmss(board.medianSeconds) : "not yet measured"),
      }),
    );
  }

  // --- session mode (0130; web2 placement since 0136): pick a client. --- //
  root.append(el("h1", { textContent: `${LANE_LABEL[lane]} session` }));
  root.append(el("p", { className: "muted", textContent: LANE_BLURB[lane] }));
  const laneTotal = el("p", { className: "muted" });
  root.append(laneTotal);
  const clientSelect = el("select");
  // The client list is fetched on demand AND re-fetchable: this call used to fire once
  // at render, so a fetch that raced with pairing — or ran a moment before an audit
  // finished queuing work — left "No session-able work" frozen with no way back but
  // reopening the panel. loadClients() is idempotent and the ↻ button re-runs it.
  const refreshClients = el("button", {
    textContent: "↻",
    title: "Reload the client list (after running an audit or queuing a build)",
  });
  async function loadClients(): Promise<void> {
    clientSelect.replaceChildren(el("option", { value: "", textContent: "Loading clients…" }));
    refreshClients.disabled = true;
    const res = await send({ type: "sessionClients" });
    refreshClients.disabled = false;
    clientSelect.replaceChildren();
    if (!res.ok) {
      clientSelect.append(el("option", { value: "", textContent: "Couldn't load clients — press ↻ to retry" }));
      return;
    }
    const all = res.data as SessionClientCount[];
    // The lane's OWN total, and the clients that have work in it. A count the server
    // did not report reads "not reported", never "0" — see `lanes.ts`.
    const total = laneWorkCount(lane, all);
    laneTotal.textContent =
      all.length === 0
        ? ""
        : total === null
          ? `This server did not report a ${LANE_LABEL[lane]} backlog — the clients below may still have work.`
          : `${total} ${lane === "web2" ? "placement(s)" : "item(s)"} outstanding across ${all.length} client(s).`;
    if (all.length === 0) {
      clientSelect.append(
        el("option", { value: "", textContent: "No work yet — run an audit / queue a build, then press ↻" }),
      );
      return;
    }
    const mine = clientsForLane(lane, all);
    if (mine.length === 0) {
      clientSelect.append(
        el("option", {
          value: "",
          textContent: `No ${LANE_LABEL[lane]} work for any client — try the other tab, or press ↻`,
        }),
      );
      return;
    }
    for (const c of mine) {
      clientSelect.append(
        el("option", { value: c.clientId, textContent: clientSummary(lane, c) }),
      );
    }
  }
  refreshClients.onclick = () => void loadClients();
  void loadClients();
  const start = el("button", { className: "primary", textContent: "Start session" });
  start.onclick = async () => {
    if (!clientSelect.value) return;
    start.disabled = true;
    const res = await send({
      type: "startSession",
      clientId: clientSelect.value,
      kind: laneToSessionKind(lane),
    });
    start.disabled = false;
    if (!res.ok) { renderError(res); return; }
    renderSession(res.data as ActiveSession);
  };
  root.append(
    el("div", { className: "row" }, clientSelect, refreshClients),
    el("div", { className: "row" }, start),
  );

  // Single-claim mode is a CITATION-QUEUE affordance: `claim` pops the next citation
  // off that queue. There is no equivalent for placements (a placement is released by
  // an approved campaign, not claimed one at a time), so offering the button on the
  // Web 2.0 tab would hand the operator a citation while they are working placements.
  if (lane === "citation") {
    root.append(el("hr"));
    const take = el("button", { textContent: "Take one item (no session)" });
    take.onclick = async () => {
      take.disabled = true;
      const res = await send({ type: "claim" });
      if (!res.ok) { renderError(res); return; }
      if (!res.data) { flash = "Nothing waiting — the queue is empty."; void refresh(); return; }
      item = res.data as QueueItem;
      lastFill = null;
      renderItem();
    };
    root.append(el("div", { className: "row" }, take));
  }
  const unpair = el("button", { textContent: "Unpair this device" });
  unpair.onclick = async () => { await send({ type: "unpair" }); renderPairing(); };
  root.append(el("hr"), el("div", { className: "row" }, unpair));
}

// --------------------------------------------------------------------------- //
// The session board (0130).
// --------------------------------------------------------------------------- //

const STATE_LABEL: Record<string, string> = {
  pending: "waiting", released: "ready", opened: "tab open", form_detected: "form found",
  filled: "filled", awaiting_submit: "review & submit", submitted: "submitted ✓",
  skipped: "skipped", deferred: "deferred", blocked: "blocked",
};

const TERMINAL_STATES = new Set(["submitted", "skipped", "deferred", "blocked"]);

async function refreshSessionView(): Promise<void> {
  const res = await send({ type: "refreshSession" });
  if (!res.ok) { renderError(res); return; }
  if (!res.data) { flash = flash || "Session finished."; void refresh(); return; }
  renderSession(res.data as ActiveSession);
}

function renderSessionTask(task: SessionTaskCard): HTMLElement {
  const wrapper = el("div", { className: "note" });
  const pn = task.priceNote.trim();
  const low = pn.toLowerCase();
  // A directory that charges to SUBMIT (not just paid upsells on a free listing).
  const paidToSubmit = !!pn && !low.includes("free") && /\$|\bpaid\b|\bfee\b|\bpay\b/.test(low);

  // Collapsed HEADER: a chevron, the directory, its state, and a compact "paid" flag so
  // cost is visible without expanding. The whole header toggles the body.
  const chevron = el("span", { className: "muted", textContent: "▸" });
  const head = el("div", { className: "row" },
    chevron,
    el("b", { textContent: task.directory }),
    el("span", { className: "muted", textContent: ` · ${STATE_LABEL[task.uiState] ?? task.uiState}` }),
  );
  head.style.cursor = "pointer";
  head.style.alignItems = "center";
  if (paidToSubmit) head.append(el("span", { className: "note bad", textContent: "⚠ paid" }));
  wrapper.append(head);

  if (task.prohibitedWarning) {
    wrapper.append(el("div", { className: "note bad", textContent: `Do not submit. ${task.prohibitedWarning}` }));
    return wrapper;
  }
  // A finished task is header-only — which IS the collapsed look, so a card naturally
  // collapses once its work is done (refreshSessionView re-renders after a submit).
  if (TERMINAL_STATES.has(task.uiState)) return wrapper;

  // Collapsible BODY: hidden by default, revealed by the header/chevron. Every control
  // lives here, so each card starts collapsed showing only a dropdown affordance.
  const card = el("div");
  card.style.display = "none";
  let expanded = false;
  head.onclick = () => {
    expanded = !expanded;
    card.style.display = expanded ? "" : "none";
    chevron.textContent = expanded ? "▾" : "▸";
  };
  if (pn) {
    card.append(
      el("div", {
        className: paidToSubmit ? "note bad" : "muted",
        textContent: paidToSubmit
          ? `⚠ Costs money to submit — ${pn}. Skip unless the client agreed.`
          : `Cost: ${pn}`,
      }),
    );
  }

  const actions = el("div", { className: "row" });
  // ONE-CLICK primary path: open the add-form tab and autofill it in a single click.
  // Open / Autofill below stay for re-filling or when the page needs manual steps first.
  if (task.addUrl) {
    const oneClick = el("button", { className: "primary", textContent: "Open & Autofill" });
    const oneOut = el("div", { className: "muted" });
    oneClick.onclick = async () => {
      oneClick.disabled = true;
      const permitted = await ensureInjectPermission(task.addUrl);
      if (!permitted) {
        oneClick.disabled = false;
        oneOut.textContent = "Chrome needs permission to fill this site. Choose Allow, then click again.";
        return;
      }
      oneOut.textContent = "Opening the form and filling…";
      const res = await send({ type: "openAndAutofill", taskId: task.taskId });
      oneClick.disabled = false;
      if (!res.ok) { oneOut.textContent = `Couldn't autofill: ${res.error ?? "unknown error"}.`; return; }
      const outcome = res.data as FillOutcome;
      const noMatch = outcome.failed.filter((f) => f.reason === "no_field_matched").map((f) => f.key);
      oneOut.textContent =
        outcome.filled.length === 0 && noMatch.length === 0
          ? "Opened — no form fields detected yet. When the form is visible, press Autofill."
          : `Filled ${outcome.filled.length}${outcome.filled.length ? ` (${outcome.filled.join(", ")})` : ""}` +
            `${noMatch.length ? ` · no field for: ${noMatch.join(", ")} — copy those below` : ""}. Review, then submit.`;
    };
    actions.append(oneClick);
    card.append(oneOut);
  }
  const open = el("button", { textContent: task.addUrl ? "Open" : "No add URL" , disabled: !task.addUrl });
  open.onclick = async () => { await send({ type: "openTask", taskId: task.taskId }); };
  actions.append(open);

  if (task.hasSpec) {
    const fill = el("button", { textContent: "Fill" });
    const fillOut = el("div", { className: "muted" });
    fill.onclick = async () => {
      fill.disabled = true;
      const permitted = await ensureInjectPermission(task.addUrl);
      if (!permitted) {
        fill.disabled = false;
        fillOut.textContent = "Chrome needs permission to fill this site. Choose Allow, then click Fill again.";
        return;
      }
      const res = await send({ type: "fillTask", taskId: task.taskId });
      fill.disabled = false;
      if (!res.ok) { fillOut.textContent = `Fill couldn't run: ${res.error ?? "unknown error"}.`; return; }
      const outcome = res.data as FillOutcome;
      fillOut.textContent = `${outcome.filled.length} filled, ${outcome.failed.length} not`;
    };
    actions.append(fill);
    card.append(fillOut);
  } else {
    // No earned spec means no exact selectors — but the operator should not have to
    // copy ten fields by hand. "Autofill" scans THIS page and matches each value to a
    // field by its attributes; it is honest (reports what stuck), never submits, and
    // never touches a CAPTCHA. The copy-buttons stay as the fallback for whatever it
    // could not confidently identify. Finishing one by hand is how a spec gets earned.
    const auto = el("button", { textContent: "Autofill (best-effort)" });
    const autoOut = el("div", { className: "muted" });
    auto.onclick = async () => {
      auto.disabled = true;
      // FIRST await, inside the gesture: grant access to the directory's host so the
      // filler can be injected. Without this the inject throws and nothing happens.
      const permitted = await ensureInjectPermission(task.addUrl);
      if (!permitted) {
        auto.disabled = false;
        autoOut.textContent =
          "Chrome needs permission to fill this site. When it asks, choose Allow, then click Autofill again.";
        return;
      }
      autoOut.textContent = "Scanning the form…";
      const res = await send({ type: "fillTaskAuto", taskId: task.taskId });
      auto.disabled = false;
      // Errors render INLINE here (not a full re-render) so a failure is visible on the
      // card instead of looking like the panel just refreshed.
      if (!res.ok) {
        autoOut.textContent = `Autofill couldn't run: ${res.error ?? "unknown error"}. Open the form tab and try again.`;
        return;
      }
      const outcome = res.data as FillOutcome;
      const noMatch = outcome.failed.filter((f) => f.reason === "no_field_matched").map((f) => f.key);
      if (outcome.filled.length === 0 && noMatch.length === 0) {
        autoOut.textContent = "No form fields found on this page — make sure the add-listing form is open in the tab.";
        return;
      }
      autoOut.textContent =
        `Filled ${outcome.filled.length}${outcome.filled.length ? ` (${outcome.filled.join(", ")})` : ""}` +
        `${noMatch.length ? ` · no field found for: ${noMatch.join(", ")} — copy those below` : ""}` +
        `. Review the page before you submit.`;
    };
    card.append(auto, autoOut);

    // AI-ASSISTED FILL. The heuristic above matches on a curated synonym list, which
    // is free and instant and provably runs out on three things (measured in
    // tests/heuristicGap.test.ts): an abbreviation nobody listed ("Org.", "Ph."), a
    // box whose only clue is the text beside it, and a honeypot named `url` that the
    // heuristic FILLS with the website and then truthfully reports as filled - while
    // the directory silently discards the submission.
    //
    // This button describes the form's STRUCTURE to the server (never a value, never
    // the page) and asks what each remaining box wants. It still never submits.
    const ai = el("button", { textContent: "AI fill" });
    const aiOut = el("div", { className: "muted" });
    const aiReview = el("div", { className: "muted" });
    ai.onclick = async () => {
      ai.disabled = true;
      aiReview.textContent = "";
      const permitted = await ensureInjectPermission(task.addUrl);
      if (!permitted) {
        ai.disabled = false;
        aiOut.textContent =
          "Chrome needs permission to read this form. When it asks, choose Allow, then click AI fill again.";
        return;
      }
      // The four stages the operator sees. They are narrated rather than hidden behind
      // one spinner because the middle one can take a few seconds, and a button that
      // looks stuck is a button people press twice.
      aiOut.textContent = "Analysing form…";
      const res = await send({ type: "fillTaskAi", taskId: task.taskId });
      ai.disabled = false;
      if (!res.ok) {
        aiOut.textContent =
          `AI fill couldn't run: ${res.error ?? "unknown error"}. The copy buttons below still work.`;
        return;
      }
      const out = res.data as {
        stage: string;
        outcome: FillOutcome;
        review: { key: string; confidence: number }[];
        cached: boolean;
        reason: string;
        notes: string[];
      };
      if (out.stage === "held") {
        // An honest refusal, not an error: the operator lands back on copy buttons,
        // which is exactly where they were before this feature existed.
        aiOut.textContent = out.reason || "The form could not be mapped — copy the values below.";
        return;
      }
      const filled = out.outcome.filled;
      const noMatch = out.outcome.failed
        .filter((f) => f.reason === "no_field_matched").map((f) => f.key);
      aiOut.textContent =
        `Ready for review — filled ${filled.length}` +
        `${filled.length ? ` (${filled.join(", ")})` : ""}` +
        `${out.cached ? " · cached, cost nothing" : ""}` +
        `${noMatch.length ? ` · no field found for: ${noMatch.join(", ")}` : ""}` +
        `. Check the page before you submit.`;
      if (out.review.length) {
        // Mapped but under the confidence bar. OFFERED, never typed: a phone number in
        // a "fax" box is worse than an empty box.
        aiReview.textContent =
          `Needs your eye (not filled): ${out.review.map((r) => r.key).join(", ")}.`;
      }
    };
    card.append(ai, aiOut, aiReview);
    card.append(el("div", { className: "muted", textContent: "Or copy any value:" }));
    for (const f of task.fields) {
      const row = el("div", { className: "field" },
        el("span", { className: "muted", textContent: f.label }), el("b", { textContent: f.value }));
      row.onclick = () => void navigator.clipboard.writeText(f.value);
      card.append(row);
    }
  }
  card.append(actions);

  const url = el("input", { placeholder: "Public listing URL…" });
  const done = el("button", { className: "primary", textContent: "Mark submitted" });
  const outcome = el("div"); // holds the refusal message + the honest override actions

  async function submit(operatorConfirmed: boolean): Promise<void> {
    const liveUrl = url.value.trim();
    if (!liveUrl && !operatorConfirmed) {
      outcome.replaceChildren(el("div", { className: "muted",
        textContent: "Paste the public listing URL, or use “No public URL — I submitted it”." }));
      return;
    }
    done.disabled = true;
    outcome.replaceChildren(el("div", { className: "muted", textContent: "Checking the page…" }));
    const res = await send({ type: "markSubmitted", taskId: task.taskId, liveUrl, note: "", operatorConfirmed });
    done.disabled = false;
    if (!res.ok) { outcome.replaceChildren(); renderError(res); return; }
    const result = res.data as CompleteResult;
    if (result.accepted) {
      flash = result.operatorConfirmed
        ? `${task.directory}: recorded as submitted (your confirmation) — a re-check will verify it.`
        : `${task.directory}: live — verified on the page.`;
      void refreshSessionView();
      return;
    }
    // Refused. Show what we saw, and — when the page simply could not be READ (JS-render,
    // a block, a moderation hold) — offer the honest override that records the operator's
    // confirmation as `submitted` (never a fabricated "live"). If the page loaded fine but
    // the business was absent, no override is offered: that is a genuinely-not-live answer.
    outcome.replaceChildren(
      el("div", { className: "note" },
        el("b", { textContent: "Not accepted: " }),
        result.reason || "the business wasn't found on that page"),
    );
    if (result.canConfirm) {
      const confirmBtn = el("button", { textContent: "It's live — I checked (record my confirmation)" });
      confirmBtn.onclick = () => void submit(true);
      outcome.append(el("div", { className: "row" }, confirmBtn));
    }
  }
  done.onclick = () => void submit(false);
  // Some directories expose no public listing URL at all (the listing exists but there's
  // no page to link). This records an operator-confirmed submission with no URL.
  const noUrl = el("button", { textContent: "No public URL — I submitted it" });
  noUrl.onclick = () => { url.value = ""; void submit(true); };
  const skip = el("button", { textContent: "Skip" });
  skip.onclick = async () => {
    const reason = prompt("Why skip this one?") ?? "";
    if (!reason.trim()) return;
    const res = await send({ type: "skipTask", taskId: task.taskId, reason: reason.trim() });
    if (!res.ok) { renderError(res); return; }
    void refreshSessionView();
  };
  const defer = el("button", { textContent: "Later" });
  defer.onclick = async () => {
    const res = await send({ type: "deferTask", taskId: task.taskId });
    if (!res.ok) { renderError(res); return; }
    void refreshSessionView();
  };
  const cant = el("button", { textContent: "Can't" });
  cant.onclick = async () => {
    const reasons = Object.keys(BLOCK_REASONS).join(", ");
    const reason = prompt(`Reason (${reasons}):`, "captcha_wall") ?? "";
    if (!BLOCK_REASONS[reason]) return;
    const res = await send({ type: "blockTask", taskId: task.taskId, reason, detail: "" });
    if (!res.ok) { renderError(res); return; }
    void refreshSessionView();
  };
  card.append(
    el("div", { className: "row" }, url),
    el("div", { className: "row" }, done, noUrl),
    outcome,
    el("div", { className: "row" }, skip, defer, cant),
  );
  wrapper.append(card);
  return wrapper;
}

/**
 * One web2 placement card (0136). The approved draft travels as COPY-BLOCKS the
 * operator pastes into the platform's own editor; the extension NEVER auto-submits
 * and never fills contenteditable — a Fill button appears only when an ACTIVE earned
 * placement spec provides plain selectors (fail-closed to copy-blocks otherwise).
 * "Mark placed" asks for the public URL; the SERVER verifies host + link before
 * anything moves, and a refusal renders inline.
 */
function renderWeb2SessionTask(task: Web2PlacementTaskCard): HTMLElement {
  const card = el("div", { className: "note" });
  card.append(
    el("b", { textContent: `${task.platform}${task.title ? ` · ${task.title}` : ""}` }),
    el("span", { className: "muted", textContent: ` · ${STATE_LABEL[task.uiState] ?? task.uiState}` }),
  );
  if (TERMINAL_STATES.has(task.uiState)) return card;

  const actions = el("div", { className: "row" });
  const open = el("button", {
    textContent: task.editorUrl ? "Open editor" : "No editor URL on file",
    disabled: !task.editorUrl,
  });
  open.onclick = async () => { await send({ type: "openTask", taskId: task.taskId }); };
  actions.append(open);

  if (task.hasSpec) {
    const fill = el("button", { textContent: "Fill" });
    fill.onclick = async () => {
      fill.disabled = true;
      const res = await send({ type: "fillTask", taskId: task.taskId });
      fill.disabled = false;
      if (!res.ok) { renderError(res); return; }
      const outcome = res.data as FillOutcome;
      card.append(el("div", { className: "muted",
        textContent: `${outcome.filled.length} filled, ${outcome.failed.length} not` }));
    };
    actions.append(fill);
  } else {
    card.append(el("div", { className: "muted",
      textContent: "No verified editor spec — paste the draft yourself:" }));
  }
  // Copy-blocks are ALWAYS offered (they are the lane's default, not a fallback UI):
  // title, body, anchor, link target — click to copy, paste into the editor.
  for (const b of task.copyBlocks) {
    const preview = b.value.length > 120 ? `${b.value.slice(0, 117)}…` : b.value;
    const row = el("div", { className: "field" },
      el("span", { className: "muted", textContent: `${b.label} (copy)` }),
      el("b", { textContent: preview }));
    row.onclick = () => void navigator.clipboard.writeText(b.value);
    card.append(row);
  }
  card.append(actions);

  const url = el("input", { placeholder: "Public post URL…" });
  const done = el("button", { className: "primary", textContent: "Mark placed" });
  done.onclick = async () => {
    const postUrl = url.value.trim();
    if (!postUrl) return;
    done.disabled = true;
    const res = await send({ type: "markPlaced", taskId: task.taskId, url: postUrl });
    done.disabled = false;
    if (!res.ok) { renderError(res); return; }
    const result = res.data as PlacementCompleteResult;
    if (result.accepted) {
      flash = `${task.platform}: published — link verified on the page.`;
      void refreshSessionView();
      return;
    }
    // A refusal renders INLINE: commonest cause is a post still propagating, or a
    // URL pasted from the wrong tab. The honest state is "not verified yet".
    card.append(el("div", { className: "note" },
      el("b", { textContent: "Not accepted yet: " }),
      result.reason || "the link was not verified on that page"));
  };
  const skip = el("button", { textContent: "Skip" });
  skip.onclick = async () => {
    const reason = prompt("Why skip this one?") ?? "";
    if (!reason.trim()) return;
    const res = await send({ type: "skipTask", taskId: task.taskId, reason: reason.trim() });
    if (!res.ok) { renderError(res); return; }
    void refreshSessionView();
  };
  const defer = el("button", { textContent: "Later" });
  defer.onclick = async () => {
    const res = await send({ type: "deferTask", taskId: task.taskId });
    if (!res.ok) { renderError(res); return; }
    void refreshSessionView();
  };
  const cant = el("button", { textContent: "Can't" });
  cant.onclick = async () => {
    const reasons = Object.keys(BLOCK_REASONS).join(", ");
    const reason = prompt(`Reason (${reasons}):`, "account_required") ?? "";
    if (!BLOCK_REASONS[reason]) return;
    const res = await send({ type: "blockTask", taskId: task.taskId, reason, detail: "" });
    if (!res.ok) { renderError(res); return; }
    void refreshSessionView();
  };
  card.append(el("div", { className: "row" }, url), el("div", { className: "row" }, done, skip, defer, cant));
  return card;
}

function renderSession(state: ActiveSession): void {
  root.replaceChildren();
  const web2 = sessionKind(state) === "web2_placement";
  const web2Tasks = state.web2Tasks ?? [];
  // A session ADOPTED after a browser restart may be in the lane the operator was not
  // last looking at. The session is the authority on which lane is being worked, so it
  // moves the tab rather than the tab contradicting the work on screen.
  const sessionLane = sessionKindToLane(sessionKind(state));
  if (sessionLane !== lane) { lane = sessionLane; void writeLane(lane); }
  root.append(el("h1", { textContent: `${web2 ? "Web 2.0 session" : "Session"} · ${state.client}` }));
  root.append(renderTabs(sessionLane, sessionLane));
  if (flash) { root.append(el("div", { className: "note", textContent: flash })); flash = ""; }

  // The batch progress strip: where we are, and how the whole session is going.
  const all: Array<{ uiState: string; batchNo: number }> = web2 ? web2Tasks : state.tasks;
  const counts: Record<string, number> = {};
  for (const t of all) counts[t.uiState] = (counts[t.uiState] ?? 0) + 1;
  const done = all.filter((t) => TERMINAL_STATES.has(t.uiState)).length;
  root.append(
    el("p", {
      className: "muted",
      textContent:
        `Batch ${state.currentBatch} of ${state.totalBatches} · ` +
        `${done}/${all.length} finished · ` +
        Object.entries(counts).map(([s, n]) => `${n} ${STATE_LABEL[s] ?? s}`).join(" · "),
    }),
  );

  if (web2) {
    for (const task of web2Tasks.filter((t) => t.batchNo === state.currentBatch)) {
      root.append(renderWeb2SessionTask(task));
    }
  } else {
    const current = state.tasks.filter((t) => t.batchNo === state.currentBatch);
    for (const task of current) root.append(renderSessionTask(task));
  }

  const later = all.filter((t) => t.batchNo > state.currentBatch).length;
  if (later > 0) {
    root.append(el("p", {
      className: "muted",
      textContent: `${later} more task(s) release automatically when this batch is finished.`,
    }));
  }

  root.append(el("hr"));
  const sync = el("button", { textContent: "Refresh" });
  sync.onclick = () => void refreshSessionView();
  const close = el("button", { textContent: "Close session" });
  close.onclick = async () => {
    close.disabled = true;
    await send({ type: "closeSession" });
    flash = "Session closed.";
    void refresh();
  };
  root.append(el("div", { className: "row" }, sync, close));
}

function renderItem(): void {
  if (!item) return void refresh();
  root.replaceChildren();
  root.append(el("h1", { textContent: `${item.directory} · ${item.client}` }));

  if (item.prohibitedWarning) {
    root.append(el("div", { className: "note bad", textContent: `Do not submit. ${item.prohibitedWarning}` }));
  }
  root.append(el("p", { className: "muted", textContent: `Needs a person because: ${item.queuedBecause}` }));
  if (item.humanAttempts > 1) {
    root.append(el("p", { className: "muted", textContent: `Attempt ${item.humanAttempts} — someone has tried this before.` }));
  }

  if (item.addUrl) {
    const open = el("button", { textContent: "Open the form" });
    open.onclick = () => void chrome.tabs.create({ url: item!.addUrl });
    root.append(el("div", { className: "row" }, open));
  } else {
    root.append(el("p", { className: "muted", textContent: "No verified add-listing URL on file — start from the directory's home page." }));
  }

  const fillable = item.fields.filter((f) => f.selector).length;
  if (fillable === 0) {
    root.append(
      el("p", { className: "muted",
        textContent:
          "No verified form spec for this directory yet, so there is nothing to fill " +
          "automatically — copy the values below instead. Finishing one by hand is how a " +
          "spec earns its way onto the list.",
      }),
    );
  }
  const fill = el("button", {
    className: "primary",
    textContent: fillable ? `Fill ${fillable} field${fillable === 1 ? "" : "s"}` : "Fill this page",
    disabled: fillable === 0,
  });
  fill.onclick = async () => {
    fill.disabled = true;
    const res = await send({ type: "fill" });
    fill.disabled = false;
    if (!res.ok) { renderError(res); return; }
    lastFill = res.data as FillOutcome;
    renderItem();
  };
  root.append(el("div", { className: "row" }, fill));

  if (lastFill) {
    const bad = lastFill.failed.length;
    // The honest report. A filler that only writes values would say "9 filled" here even
    // when the page discarded every one of them.
    root.append(
      el("div", { className: bad ? "note" : "note" },
        el("b", { textContent: `${lastFill.filled.length} filled, ${bad} not` }),
        ...(bad
          ? [el("div", { className: "muted", textContent: lastFill.failed.map((f) => `${f.key}: ${f.reason.replace(/_/g, " ")}`).join(" · ") })]
          : []),
      ),
    );
  }

  root.append(el("p", { className: "muted", textContent: "Values — click to copy:" }));
  for (const f of item.fields) {
    const row = el("div", { className: "field" }, el("span", { className: "muted", textContent: f.label }), el("b", { textContent: f.value }));
    row.onclick = () => void navigator.clipboard.writeText(f.value);
    root.append(row);
  }

  root.append(el("hr"), el("p", { className: "muted", textContent: "Paste the listing's public URL. We fetch it and check the business is on the page." }));
  const url = el("input", { placeholder: "https://directory.example/biz/…" });
  const note = el("textarea", { placeholder: "Anything worth knowing next time? (optional)", rows: 2 });
  const done = el("button", { className: "primary", textContent: "Verify & mark live" });
  done.onclick = async () => {
    done.disabled = true;
    const res = await send({ type: "complete", liveUrl: url.value.trim(), note: note.value });
    done.disabled = false;
    if (!res.ok) { renderError(res); return; }
    const result = res.data as CompleteResult;
    if (result.accepted) { item = null; lastFill = null; flash = "Live — verified on the page."; void refresh(); return; }
    // A refusal is expected, not an error: usually the directory has not published yet.
    root.append(
      el("div", { className: "note" },
        el("b", { textContent: "Not accepted yet: " }), result.reason,
        el("div", { className: "muted", textContent: "If it hasn't been published yet, put the item back and it will come round again." }),
      ),
    );
  };

  const reasons = el("select");
  for (const [value, label] of Object.entries(BLOCK_REASONS)) reasons.append(el("option", { value, textContent: label }));
  const block = el("button", { textContent: "Can't do this one" });
  block.onclick = async () => {
    const res = await send({ type: "blocked", reason: reasons.value, detail: note.value });
    if (!res.ok) { renderError(res); return; }
    item = null; lastFill = null; flash = "Recorded as blocked — that's a useful answer."; void refresh();
  };
  const back = el("button", { textContent: "Put it back" });
  back.onclick = async () => { await send({ type: "release" }); item = null; lastFill = null; flash = "Returned to the queue."; void refresh(); };

  root.append(
    el("div", { className: "row" }, url), el("div", { className: "row" }, note),
    el("div", { className: "row" }, done), el("hr"),
    el("div", { className: "row" }, reasons), el("div", { className: "row" }, block, back),
  );
}

function renderError(res: PanelResponse & { ok: false }): void {
  if (res.needsPairing) { renderPairing("Your token expired or was revoked. Pair again."); return; }
  root.append(el("div", { className: "note bad", textContent: res.error }));
}

async function refresh(): Promise<void> {
  const session = await send({ type: "session" });
  if (!session.ok) return renderPairing(session.error);
  const { paired, claim } = session.data as { paired: boolean; claim: { citationId: string } | null };
  if (!paired) return renderPairing();

  // Session mode wins: an active batch session (local, or adopted from the server
  // after a browser restart) IS the operator's work surface.
  const work = await send({ type: "sessionState" });
  if (work.ok && work.data) return renderSession(work.data as ActiveSession);
  // A session exists on the server and could NOT be loaded. Falling through to the
  // board would offer Start session, which the server refuses ("You already have an
  // active session") - the loop reported on 2026-09-12, on both tabs, because only
  // one session runs per operator whichever lane it belongs to. Say what is wrong and
  // give the one action that clears it.
  if (!work.ok) {
    root.replaceChildren();
    root.append(el("h1", { textContent: "AIOS Extension" }));
    root.append(el("div", { className: "note bad", textContent: work.error }));
    const release = el("button", { className: "primary", textContent: "Close the stuck session" });
    release.onclick = async () => {
      release.disabled = true;
      await send({ type: "closeSession" });
      flash = "Session released - you can start a new one.";
      void refresh();
    };
    root.append(el("div", { className: "row" }, release));
    return;
  }

  if (claim) {
    // The worker may have been terminated and rebuilt since; re-fetch the item rather
    // than trusting anything the panel remembered.
    const res = await send({ type: "board" });
    if (!res.ok) return renderError(res);
  }
  const board = await send({ type: "board" });
  if (!board.ok) return renderError(board);
  renderBoard(board.data as QueueBoard);
}

/** Restore the chosen tab BEFORE the first render, so the panel never flashes the
 *  citation board on its way to the lane the operator was actually working. */
async function boot(): Promise<void> {
  lane = await readLane();
  await refresh();
}

void boot();
