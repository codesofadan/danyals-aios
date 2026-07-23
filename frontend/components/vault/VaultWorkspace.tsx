"use client";

import { useEffect, useMemo, useRef } from "react";
import anime from "animejs";
import { useVaultKeys, useAddVaultKey } from "@/lib/hooks/vault";
import VaultTable from "./VaultTable";
import ProvidersOverview from "./ProvidersOverview";
import AddKeyForm, { type NewKey } from "./AddKeyForm";

// count-up hook (respects reduced motion)
function useCountUp(target: number, dur = 1100) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = String(target);
      return;
    }
    const o = { n: 0 };
    const a = anime({
      targets: o, n: target, duration: dur, easing: "easeOutExpo",
      update: () => { node.textContent = String(Math.round(o.n)); },
    });
    return () => a.pause();
  }, [target, dur]);
  return ref;
}

function NumKpi({ icon, label, value, sub, hero }: {
  icon: string; label: string; value: number; sub: React.ReactNode; hero?: boolean;
}) {
  const ref = useCountUp(value);
  return (
    <div className={hero ? "kpi hero" : "kpi"}>
      <div className="ic"><span className="material-symbols-rounded">{icon}</span></div>
      <div className="lab">{label}</div>
      <div className="val"><span ref={ref}>0</span></div>
      <div className="sub">{sub}</div>
    </div>
  );
}

export default function VaultWorkspace() {
  const keysQ = useVaultKeys();
  const addKey = useAddVaultKey();
  const keys = keysQ.data ?? [];

  const stats = useMemo(() => {
    const providersConnected = new Set(keys.map((k) => k.provider)).size;
    const rotate = keys.filter((k) => k.status === "rotate").length;
    const expiring = keys.filter((k) => k.status === "expiring").length;
    return { stored: keys.length, providersConnected, rotate, expiring };
  }, [keys]);

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
      <section className="kpis">
        <NumKpi
          hero icon="vpn_key" label="Keys stored" value={stats.stored}
          sub={<><span className="delta up"><span className="material-symbols-rounded">lock</span>encrypted</span> in the key vault</>}
        />
        <NumKpi
          icon="hub" label="Providers connected" value={stats.providersConnected}
          sub={<>Serper · DataForSEO · Google · Anthropic · more</>}
        />
        <NumKpi
          icon="cached" label="Keys needing rotation" value={stats.rotate}
          sub={
            stats.rotate > 0
              ? <><span className="delta down"><span className="material-symbols-rounded">priority_high</span>{stats.rotate}</span> overdue · {stats.expiring} expiring soon</>
              : <>all keys within rotation window</>
          }
        />
        <div className="kpi kv-statuskpi">
          <div className="ic"><span className="material-symbols-rounded">verified_user</span></div>
          <div className="lab">Vault status</div>
          <div className="val kv-statusval">Encrypted</div>
          <div className="sub"><span className="delta up"><span className="material-symbols-rounded">check_circle</span>OK</span> AES-256 · at rest</div>
        </div>
      </section>

      <div className="kv-banner">
        <span className="kv-banner-ic"><span className="material-symbols-rounded">lock</span></span>
        <div className="kv-banner-txt">
          <b>Encrypted at rest · never in logs · Super-Admin only.</b>
          <span>Keys are agency-global, decrypted server-side only, and never shipped in the client bundle.</span>
        </div>
        <span className="kv-banner-tag">
          <span className="material-symbols-rounded">shield_person</span>Super Admin
        </span>
      </div>

      <div className="row">
        <section className="card kv-tablecard">
          <div className="card-h">
            <div>
              <div className="ct">Encrypted key vault</div>
              <div className="cs">Every API key &amp; password — masked by default, reveal on demand.</div>
            </div>
          </div>
          {keysQ.isLoading ? (
            <div className="panel-hint" style={{ padding: "18px 20px" }}>Loading keys…</div>
          ) : keysQ.isError ? (
            <div className="panel-hint" role="alert" style={{ padding: "18px 20px", color: "var(--warn, #A96913)" }}>
              Couldn&apos;t load vault keys — {(keysQ.error as Error)?.message ?? "try again"}.
            </div>
          ) : (
            <VaultTable keys={keys} />
          )}
        </section>

        <div className="kv-side">
          <ProvidersOverview />
          <AddKeyForm onAdd={handleAdd} />
          {addKey.isError && (
            <div className="panel-hint" role="alert" style={{ color: "var(--warn, #A96913)" }}>
              Couldn&apos;t add key — {(addKey.error as Error)?.message ?? "try again"}.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
