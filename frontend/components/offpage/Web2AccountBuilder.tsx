"use client";

import { useState } from "react";
import {
  useAdvanceWeb2Provisioning,
  useStartWeb2Provisioning,
  useWeb2Provisioning,
  useWeb2ClientIdentity,
  type Web2ProvisionItem,
} from "@/lib/hooks/offpage";
import { useWeb2Catalog } from "@/lib/hooks/offpage";
import Web2PlatformPicker from "./Web2PlatformPicker";

/**
 * The account builder: pick a client, pick platforms, work the queue.
 *
 * WHY A QUEUE AND NOT A FORM. A form is fine for one account and unusable at twenty
 * clients, because nothing survives being half-finished — there is no progress to
 * resume, nothing to hand to a colleague, and no answer to "what is left?". Each row
 * here names who is holding the ball right now, so the work can be picked up cold.
 */

const STEP: Record<Web2ProvisionItem["status"], { label: string; cls: string; next?: string; cta?: string }> = {
  queued: { label: "Queued", cls: "mut", next: "identity_ready", cta: "Start" },
  identity_ready: {
    label: "Ready to create", cls: "info", next: "awaiting_account", cta: "I'm creating it",
  },
  awaiting_account: {
    label: "Creating the account", cls: "info", next: "awaiting_verification",
    cta: "Created — awaiting email",
  },
  awaiting_verification: {
    label: "Waiting on their email", cls: "warn", next: "awaiting_credential",
    cta: "Verified",
  },
  awaiting_credential: { label: "Needs the token", cls: "warn" },
  live: { label: "Live", cls: "ok" },
  blocked: { label: "Blocked", cls: "crit" },
  cancelled: { label: "Cancelled", cls: "mut" },
};

export default function Web2AccountBuilder({ clientId }: { clientId?: string }) {
  const q = useWeb2Provisioning(clientId);
  const identityQ = useWeb2ClientIdentity(clientId);
  const start = useStartWeb2Provisioning();
  const advance = useAdvanceWeb2Provisioning();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [ack, setAck] = useState(false);
  const [error, setError] = useState("");

  const items = q.data ?? [];
  const openItems = items.filter((i) => i.status !== "cancelled" && i.status !== "live");
  const liveItems = items.filter((i) => i.status === "live");

  if (!clientId) {
    return (
      <div className="fld-hint" style={{ margin: "10px 0" }}>
        Pick a client above to build its publishing accounts.
      </div>
    );
  }

  async function queueSelected() {
    setError("");
    try {
      await start.mutateAsync({ clientId: clientId!, platforms: Array.from(picked) });
      setPicked(new Set());
      setAck(false);
    } catch (e) {
      setError((e as Error)?.message ?? "Could not queue those platforms.");
    }
  }

  async function move(item: Web2ProvisionItem, status: string) {
    setError("");
    try {
      await advance.mutateAsync({ id: item.id, status });
    } catch (e) {
      setError((e as Error)?.message ?? "Could not move that item.");
    }
  }

  return (
    <div style={{ margin: "12px 0" }}>
      <div className="panel-hint" style={{ marginBottom: 8 }}>
        <span className="material-symbols-rounded">checklist</span>
        Build this client&rsquo;s publishing accounts — one tracked item per platform.
      </div>

      {!identityQ.data?.contactEmail && (
        <div className="fld-hint" style={{ color: "#92400e", marginBottom: 8 }}>
          Set the publishing identity above first — accounts need a brand handle and an
          address on the client&rsquo;s own domain before any of them can start.
        </div>
      )}

      {/* Choose what to build. Any platform the pipeline can drive is offered. */}
      <details style={{ marginBottom: 10 }} open={openItems.length === 0}>
        <summary className="fld-hint" style={{ cursor: "pointer" }}>
          Add platforms to build
        </summary>
        <div style={{ marginTop: 8 }}>
          <Web2PlatformPicker
            clientId={clientId}
            selected={picked}
            onToggle={(key) =>
              setPicked((prev) => {
                const next = new Set(prev);
                if (next.has(key)) next.delete(key);
                else next.add(key);
                setAck(false);
                return next;
              })
            }
            acknowledged={ack}
            onAcknowledgedChange={setAck}
            emptyEligibleHint={
              <div className="fld-hint">
                Nothing to add — every platform this client can use is already queued or live.
              </div>
            }
          />
          <button
            className="primary-btn"
            style={{ marginTop: 10 }}
            disabled={picked.size === 0 || start.isPending}
            onClick={() => void queueSelected()}
          >
            {start.isPending ? "Queueing…" : `Build ${picked.size} account${picked.size === 1 ? "" : "s"}`}
          </button>
        </div>
      </details>

      {error && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          {error}
        </div>
      )}

      {q.isLoading && <div className="op-muted">Loading the queue…</div>}

      {openItems.length > 0 && (
        <div className="tbl-wrap">
          <table className="tbl op-tbl">
            <thead>
              <tr>
                <th>Platform</th>
                <th>Step</th>
                <th>Account</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {openItems.map((item) => {
                const step = STEP[item.status];
                return (
                  <tr key={item.id}>
                    <td className="op-strong">
                      {item.platform}
                      {item.lane === "auto" && (
                        <span className="w2-sub">automatic — no signup form</span>
                      )}
                    </td>
                    <td>
                      <span className={`status-pill ${step.cls}`}>{step.label}</span>
                      {item.note && <span className="w2-sub">{item.note}</span>}
                      {item.verifyLink && (
                        <span className="w2-sub">
                          <a href={item.verifyLink} target="_blank" rel="noopener noreferrer">
                            open the confirmation link
                          </a>
                        </span>
                      )}
                    </td>
                    <td>
                      <span>{item.handle || "—"}</span>
                      {item.registrationEmail && (
                        <span className="w2-sub">{item.registrationEmail}</span>
                      )}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {item.setupUrl && (
                        <a
                          className="op-act"
                          href={item.setupUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ marginRight: 6 }}
                        >
                          Open signup
                        </a>
                      )}
                      {step.next && step.cta && (
                        <button
                          className="op-act"
                          disabled={advance.isPending}
                          onClick={() => void move(item, step.next!)}
                        >
                          {step.cta}
                        </button>
                      )}
                      {item.status === "awaiting_credential" && (
                        <FinishForm item={item} onError={setError} />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {liveItems.length > 0 && (
        <div className="fld-hint" style={{ marginTop: 8, color: "var(--ok)" }}>
          {liveItems.length} account{liveItems.length === 1 ? "" : "s"} live:{" "}
          {liveItems.map((i) => i.platform).join(", ")}
        </div>
      )}

      {!q.isLoading && items.length === 0 && (
        <div className="op-muted">
          Nothing queued yet. Add platforms above to start building this client&rsquo;s accounts.
        </div>
      )}
    </div>
  );
}

/** The last step: paste the platform's token, and the account becomes real.
 *
 *  The credential fields are DECLARED PER PLATFORM by the backend catalogue, so adding
 *  a platform needs no change here. The token is posted once and sealed server-side —
 *  it is never echoed back, cached, or put in a query key. */
function FinishForm({
  item,
  onError,
}: {
  item: Web2ProvisionItem;
  onError: (msg: string) => void;
}) {
  const catalog = useWeb2Catalog();
  const advance = useAdvanceWeb2Provisioning();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [propertyUrl, setPropertyUrl] = useState("");

  const fields = catalog.data?.credentialFields?.[item.platform] ?? [];

  async function finish() {
    onError("");
    try {
      await advance.mutateAsync({
        id: item.id,
        status: "live",
        credential: values,
        handle: item.handle,
        propertyUrl: propertyUrl.trim(),
      });
      setOpen(false);
      setValues({});
    } catch (e) {
      onError((e as Error)?.message ?? "Could not finish that account.");
    }
  }

  if (!open) {
    return (
      <button className="op-act" onClick={() => setOpen(true)}>
        Add the token
      </button>
    );
  }

  return (
    <div style={{ marginTop: 6, display: "grid", gap: 6, minWidth: 260 }}>
      {(fields.length ? fields : ["token"]).map((f) => (
        <input
          key={f}
          value={values[f] ?? ""}
          onChange={(e) => setValues((prev) => ({ ...prev, [f]: e.target.value }))}
          placeholder={f}
          aria-label={f}
        />
      ))}
      <input
        value={propertyUrl}
        onChange={(e) => setPropertyUrl(e.target.value)}
        placeholder="the property URL (optional)"
        aria-label="property URL"
      />
      <div>
        <button className="primary-btn" disabled={advance.isPending} onClick={() => void finish()}>
          {advance.isPending ? "Saving…" : "Save & go live"}
        </button>{" "}
        <button className="op-act" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}
