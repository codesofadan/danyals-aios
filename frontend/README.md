# AIOS Dashboard

The web dashboard for **AIOS** — the SEO automation platform (Xegents AI). Next.js
App Router, TypeScript, with a persistent sidebar shell so modules mount as pages.

## Run

```bash
npm install
npm run dev        # http://localhost:3000
```

`npm run build && npm run start` for a production build.

> The Material Symbols icon font loads from Google Fonts, so the first run needs a
> network connection. The chart libraries (`three`, `animejs`) are installed locally.

## Structure

```
app/
  layout.tsx        Root shell — fonts, sidebar, ambient backdrop; children = page
  page.tsx          Command Center (admin/super-admin overview)
  globals.css       Full design system (dark-navy + violet Xegents brand)
components/
  Sidebar.tsx       Icon rail that expands on hover; active state from the route
  TopBar.tsx        Reusable page header (eyebrow + title + search)
  AmbientParticles  three.js point constellation behind the app
  StatTiles.tsx     KPI row with anime.js count-ups
  charts/
    AuditVolumeChart.tsx   three.js 3D bar chart (fixed 3/4 view, hover tooltip)
    TrafficChart.tsx       animated SVG area line + hover crosshair
    TeamTracking.tsx       animated bars + count-ups
    ClientProgress.tsx     animated SVG progress rings
lib/
  data.ts           Mock data + validated categorical palette — swap for the API
```

## Adding a module page

Create `app/<module>/page.tsx`, then point the matching item's `href` in
`components/Sidebar.tsx` at `/<module>`. The sidebar highlights it automatically.

## Data

`lib/data.ts` holds mock data shaped after the platform data model
(`../aios/context-docs/ARCHITECTURE-AND-PLAN.md` §8). Replace the exported arrays
with calls to the FastAPI service when the backend is wired.
