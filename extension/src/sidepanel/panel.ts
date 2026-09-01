/**
 * The operator's panel. Renders state and sends messages; it never calls the API and
 * never holds the token — that lives in the service worker, one process away from the
 * directory's own JavaScript.
 *
 * The panel is a SEPARATE DOCUMENT with its own lifetime: it dies when closed and is
 * rebuilt when reopened. So it holds no durable state either — every open re-asks the
 * worker what is going on.
 */

import type { CompleteResult, ConnectionReport, FillOutcome, PanelRequest, PanelResponse, QueueBoard, QueueItem } from "../lib/messages";
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
function renderBoard(board: QueueBoard): void {
  root.replaceChildren();
  root.append(el("h1", { textContent: "Citation queue" }));
  if (flash) { root.append(el("div", { className: "note", textContent: flash })); flash = ""; }
  root.append(
    el("p", {
      className: "muted",
      textContent:
        `${board.waiting} waiting · ${board.inProgress} in progress · median ` +
        (board.medianSeconds != null ? mmss(board.medianSeconds) : "not yet measured"),
    }),
  );
  const take = el("button", { className: "primary", textContent: "Take the next item" });
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
  const unpair = el("button", { textContent: "Unpair this device" });
  unpair.onclick = async () => { await send({ type: "unpair" }); renderPairing(); };
  root.append(el("hr"), el("div", { className: "row" }, unpair));
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

void refresh();
