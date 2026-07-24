"use client";

import { useAddVaultKey, useVaultKeys } from "@/lib/hooks/vault";
import VaultTable from "./VaultTable";
import ProvidersOverview from "./ProvidersOverview";
import AddKeyForm, { type NewKey } from "./AddKeyForm";

export default function VaultWorkspace() {
  const keysQ = useVaultKeys();
  const addKey = useAddVaultKey();
  const keys = keysQ.data ?? [];

  // Add → POST /vault/keys; the list refetches on success. The response is masked
  // metadata only (no secret), so nothing plaintext is ever cached.
  function handleAdd(input: NewKey) {
    addKey.mutate({
      provider: input.provider,
      label: input.label,
      secret: input.value,
      scope: input.scope,
    });
  }

  return (
    <div className="kv-wrap">
      {/* One slim status line — no decorative KPI cards. */}
      <div className="kv-summary">
        <span className="kv-summary-m">
          <span className="material-symbols-rounded">vpn_key</span>
          <b>{keys.length}</b>&nbsp;key{keys.length === 1 ? "" : "s"} stored
        </span>
        <span className="kv-summary-enc">
          <span className="material-symbols-rounded">lock</span>
          AES-256 encrypted at rest · never logged · Super-Admin only
        </span>
      </div>

      <div className="row">
        <section className="card kv-tablecard">
          <div className="card-h">
            <div>
              <div className="ct">Stored keys</div>
              <div className="cs">Masked by default — reveal or copy on demand.</div>
            </div>
          </div>
          {keysQ.isLoading ? (
            <div className="panel-hint" style={{ padding: "18px 20px" }}>Loading keys…</div>
          ) : keysQ.isError ? (
            <div className="panel-hint" role="alert" style={{ padding: "18px 20px", color: "var(--warn, #A96913)" }}>
              Couldn&apos;t load vault keys — {(keysQ.error as Error)?.message ?? "try again"}.
            </div>
          ) : keys.length === 0 ? (
            <div className="panel-hint" style={{ padding: "18px 20px" }}>
              No keys stored yet — add one from the panel on the right.
            </div>
          ) : (
            <VaultTable keys={keys} />
          )}
        </section>

        <div className="kv-side">
          <AddKeyForm onAdd={handleAdd} />
          {addKey.isError && (
            <div className="panel-hint" role="alert" style={{ color: "var(--warn, #A96913)" }}>
              Couldn&apos;t add key — {(addKey.error as Error)?.message ?? "try again"}.
            </div>
          )}
          <ProvidersOverview />
        </div>
      </div>
    </div>
  );
}
