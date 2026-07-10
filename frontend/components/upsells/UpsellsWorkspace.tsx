"use client";

import { useState } from "react";
import { SERIES } from "@/lib/data";
import { upsells as seed, type Upsell } from "@/lib/upsells";
import UpsellStats from "./UpsellStats";
import UpsellManager, { type NewUpsell } from "./UpsellManager";
import ClientPreview from "./ClientPreview";

const ADD_COLORS = [SERIES.c1, SERIES.c2, SERIES.c3, SERIES.c4, SERIES.c5];
const ADD_ICONS = ["rocket_launch", "trending_up", "workspace_premium", "auto_awesome", "bolt"];

let idSeq = 0;
const nextId = () => `up-${Date.now().toString(36)}${idSeq++}`;

export default function UpsellsWorkspace() {
  const [list, setList] = useState<Upsell[]>(seed);

  function handleToggle(id: string) {
    setList((prev) => prev.map((u) => (u.id === id ? { ...u, active: !u.active } : u)));
  }

  function handleMove(id: string, dir: -1 | 1) {
    setList((prev) => {
      const i = prev.findIndex((u) => u.id === id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  function handleAdd(input: NewUpsell) {
    const n = list.length;
    const item: Upsell = {
      id: nextId(),
      title: input.title,
      description: input.description,
      fiverrUrl: input.fiverrUrl || "#",
      active: input.active,
      clicks30d: 0,
      price: input.price,
      rating: 5.0,
      reviews: 0,
      icon: ADD_ICONS[n % ADD_ICONS.length],
      color: ADD_COLORS[n % ADD_COLORS.length],
    };
    setList((prev) => [item, ...prev]); // optimistic prepend
  }

  return (
    <>
      <UpsellStats list={list} />

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
