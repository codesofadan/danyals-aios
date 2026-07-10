"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import anime from "animejs";
import { vaultKeys, maskSecret, type VaultKey } from "@/lib/vault";
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

let seq = 0;

export default function VaultWorkspace() {
  const [keys, setKeys] = useState<VaultKey[]>(vaultKeys);

  const stats = useMemo(() => {
    const providersConnected = new Set(keys.map((k) => k.provider)).size;
    const rotate = keys.filter((k) => k.status === "rotate").length;
    const expiring = keys.filter((k) => k.status === "expiring").length;
    return { stored: keys.length, providersConnected, rotate, expiring };
  }, [keys]);

  // Rotate → optimistically stamp "just now" and clear the rotation flag.
  function handleRotate(id: string) {
    setKeys((prev) => prev.map((k) =>
      k.id === id ? { ...k, rotated: "just now", status: "active" } : k
    ));
  }

  // Add → optimistic new row, masked by default, freshly rotated.
  function handleAdd(input: NewKey) {
    const key: VaultKey = {
      id: `k-new-${Date.now().toString(36)}${seq++}`,
      provider: input.provider,
      label: input.label,
      masked: maskSecret(input.value),
      secret: input.value,
      scope: input.scope,
      status: "active",
      rotated: "just now",
    };
    setKeys((prev) => [key, ...prev]);
  }

  return (
    <div className="kv-wrap">
      <section className="kpis">
        <NumKpi
          hero icon="vpn_key" label="Keys stored" value={stats.stored}
          sub={<><span className="delta up"><span className="material-symbols-rounded">lock</span>encrypted</span> in Supabase Vault</>}
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
              <div className="cs">Every API key &amp; password — masked by default, reveal &amp; rotate on demand.</div>
            </div>
          </div>
          <VaultTable keys={keys} onRotate={handleRotate} />
        </section>

        <div className="kv-side">
          <ProvidersOverview keys={keys} />
          <AddKeyForm onAdd={handleAdd} />
        </div>
      </div>
    </div>
  );
}
