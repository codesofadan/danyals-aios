/**
 * The link ledger, and the two distinctions a screen can destroy.
 *
 *   • `unknown` IS NOT `live`. It means nobody has successfully fetched the page —
 *     a gap in OUR monitoring, not a fact about theirs. Rendering it as an ok tells a
 *     client their link is fine on the strength of never having looked.
 *   • LOST-FIRST ORDER IS THE SERVER'S, and the component must not re-sort. Sorted by
 *     date, the three links that went missing sit under two hundred that are fine, and
 *     the missing ones are the only rows anybody needs to act on.
 *
 * `lostAt` is the column `web2_properties` could never fill: its three link columns
 * record the latest look and nothing else, so "live in March, lost in June" had no
 * answer anywhere in the system.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Web2PlacedLinks from "./Web2PlacedLinks";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async () => ({
      live: 200, removed: 2, nofollowed: 1, unknown: 4,
      links: [
        {
          id: "1", client: "Leeds Drainage Co", platform: "Ghost",
          pageUrl: "https://ghost.example/post", targetUrl: "https://leedsdrainage.co.uk",
          anchor: "Leeds Drainage Co", state: "removed", rel: "",
          firstSeenAt: "2026-03-01T00:00:00Z", lastCheckedAt: "2026-06-01T00:00:00Z",
          lostAt: "2026-06-01T00:00:00Z",
        },
        {
          id: "2", client: "Leeds Drainage Co", platform: "Mataroa",
          pageUrl: "https://mataroa.example/p", targetUrl: "https://leedsdrainage.co.uk",
          anchor: "drain help", state: "unknown", rel: "",
          firstSeenAt: "2026-05-01T00:00:00Z", lastCheckedAt: "", lostAt: "",
        },
        {
          id: "3", client: "Leeds Drainage Co", platform: "dev.to",
          pageUrl: "https://dev.to/p", targetUrl: "https://leedsdrainage.co.uk",
          anchor: "Leeds Drainage Co", state: "live", rel: "",
          firstSeenAt: "2026-01-01T00:00:00Z", lastCheckedAt: "2026-09-01T00:00:00Z",
          lostAt: "",
        },
      ],
    })),
    post: vi.fn(async () => ({})),
    put: vi.fn(async () => ({})),
  },
}));

function renderBoard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Web2PlacedLinks />
    </QueryClientProvider>,
  );
}

describe("the placed-link ledger", () => {
  it("counts a not-checked link separately from a live one", async () => {
    renderBoard();
    // Four unchecked links folded into "live" would read as 204 healthy links. They
    // are 200 healthy links and four we have never managed to look at.
    // Scoped to the summary strip: the SAME blurb is attached to every row in that
    // state, so an unscoped lookup cannot tell "4 links are unchecked" from "this one
    // link is".
    // The strip renders before the fetch does, so awaiting IT proves nothing — wait for
    // a row, which only exists once the board has actually arrived.
    await screen.findByText("Ghost");
    const strip = screen.getByRole("group", { name: "Link states" });
    const card = within(strip).getByTitle(/gap in our monitoring, not a pass/i);
    expect(card).toHaveTextContent("4");
    expect(card).toHaveTextContent("Not checked");
  });

  it("keeps the server's lost-first order", async () => {
    renderBoard();
    await screen.findByText("Ghost");
    const rows = screen.getAllByRole("row").slice(1); // drop the header
    // Removed first, then the unknown, then the healthy one — NOT newest-first, which
    // is what buries the rows that need acting on.
    expect(within(rows[0]).getByText("Ghost")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Mataroa")).toBeInTheDocument();
    expect(within(rows[2]).getByText("dev.to")).toBeInTheDocument();
  });

  it("shows WHEN a link was lost, not merely that it is gone", async () => {
    renderBoard();
    // Await a CELL, not a row: the header row exists before the fetch lands, so
    // `findAllByRole("row")` resolves against a table that has no data in it yet.
    await screen.findByText("Ghost");
    const removed = screen.getAllByRole("row")[1];
    expect(within(removed).getByTitle(/link is no longer on it/i)).toBeInTheDocument();
    // The date is the whole value of the ledger over the property row's mutable
    // columns: "live in March, lost in June" now has an answer. Read from the LAST
    // cell, since a link keeps being re-checked after it is lost and both stamps can
    // legitimately show the same day.
    const cells = within(removed).getAllByRole("cell");
    expect(cells[cells.length - 1])
      .toHaveTextContent(new Date("2026-06-01T00:00:00Z").toLocaleDateString());
  });

  it("says how many links stopped passing value, and does not count the unchecked in", async () => {
    renderBoard();
    // 2 removed + 1 nofollowed = 3. The 4 unknown are NOT added: claiming a link is
    // lost because we could not fetch it is the same error in the other direction.
    expect(await screen.findByText(/no longer passing value/i)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });
});
