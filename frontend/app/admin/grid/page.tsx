"use client";

import TopBar from "@/components/TopBar";
import "./grid.css";
import GridWorkspace from "@/components/grid/GridWorkspace";

// Local search GRID tracking (migration 0138). Its own screen rather than a tab on
// Citations: it answers a different question from anything else in the local surface
// — not "are we listed" or "where do we rank in this market", but "where across the
// service area does our visibility fall off, and in which direction".
//
// It is also the most expensive screen in the admin area per click: one run is 17-41
// paid map-pack probes. Every control here states its probe count before it is
// pressed, which is why the module has its own cost dial rather than sharing the
// single-locale one.
export default function GridPage() {
  return (
    <>
      <TopBar
        eyebrow="Admin · SEO Engine"
        title="Grid Tracking"
        searchPlaceholder="Search grids, keywords, locations…"
      />
      <GridWorkspace />
    </>
  );
}
