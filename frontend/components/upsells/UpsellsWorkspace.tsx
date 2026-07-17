"use client";

import { SERIES } from "@/lib/data";
import {
  useUpsells,
  useCreateUpsell,
  useToggleUpsell,
  useReorderUpsells,
} from "@/lib/hooks/upsells";
import UpsellStats from "./UpsellStats";
import UpsellManager, { type NewUpsell } from "./UpsellManager";
import ClientPreview from "./ClientPreview";

const ADD_COLORS = [SERIES.c1, SERIES.c2, SERIES.c3, SERIES.c4, SERIES.c5];
const ADD_ICONS = ["rocket_launch", "trending_up", "workspace_premium", "auto_awesome", "bolt"];

export default function UpsellsWorkspace() {
  const upsellsQ = useUpsells();
  const createUpsell = useCreateUpsell();
  const toggleUpsell = useToggleUpsell();
  const reorderUpsells = useReorderUpsells();
  const list = upsellsQ.data ?? [];

  function handleToggle(id: string) {
    toggleUpsell.mutate(id);
  }

  function handleMove(id: string, dir: -1 | 1) {
    const i = list.findIndex((u) => u.id === id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    const ids = list.map((u) => u.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorderUpsells.mutate(ids);
  }

  function handleAdd(input: NewUpsell) {
    // icon/color are chosen client-side so the new card renders branded; the
    // backend tracks clicks30d (starts at 0) and assigns the id.
    const n = list.length;
    createUpsell.mutate({
      title: input.title,
      description: input.description,
      fiverrUrl: input.fiverrUrl || "#",
      active: input.active,
      price: input.price,
      rating: 5.0,
      reviews: 0,
      icon: ADD_ICONS[n % ADD_ICONS.length],
      color: ADD_COLORS[n % ADD_COLORS.length],
    });
  }

  const mutError = createUpsell.error ?? toggleUpsell.error ?? reorderUpsells.error;

  return (
    <>
      <UpsellStats list={list} />

      {upsellsQ.isLoading && <div className="panel-hint" style={{ marginTop: 4 }}>Loading upsells…</div>}
      {upsellsQ.isError && (
        <div className="panel-hint" role="alert" style={{ marginTop: 4, color: "var(--warn, #d9822b)" }}>
          Couldn&apos;t load upsells — {(upsellsQ.error as Error)?.message ?? "try again"}.
        </div>
      )}
      {mutError && (
        <div className="panel-hint" role="alert" style={{ marginTop: 4, color: "var(--warn, #d9822b)" }}>
          {(mutError as Error)?.message ?? "That action failed — try again."}
        </div>
      )}

      <div className="row up-row">
        <UpsellManager
          list={list}
          onToggle={handleToggle}
          onMove={handleMove}
          onAdd={handleAdd}
        />
        <ClientPreview list={list} />
      </div>
    </>
  );
}
