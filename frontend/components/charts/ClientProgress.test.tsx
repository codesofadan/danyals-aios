/**
 * The admin dashboard's progress rings, and the collision that made them lie.
 *
 * The list was keyed by the client NAME and the animation effect then read
 * `clients[idx]` at the matching DOM position. Both halves of that are only correct
 * while every name is unique. They are not: this deployment's database holds ninety
 * clients called "Brand Kit Test", and outside test data two franchises of one brand
 * share a name routinely.
 *
 * What went wrong is worth stating precisely, because the React console warning
 * undersells it. React drops a duplicate-keyed child, so the DOM held FEWER rings than
 * `clients` had entries — and every ring after the first collision animated a different
 * client's completion percentage, under the correct client's name. A dashboard that
 * quietly attributes one client's progress to another is worse than one that crashes.
 */
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import ClientProgress from "./ClientProgress";

// Drive the REDUCED-MOTION branch. It writes the final number synchronously instead of
// tweening it, so an assertion about which value landed on which ring is about the
// wiring rather than about animation timing — and it is the path a real visitor with
// "reduce motion" set actually gets.
beforeAll(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
});

// anime.js drives requestAnimationFrame and writes the final number asynchronously.
// Stubbed so the assertions are about WHICH value reaches WHICH ring, not about timing.
vi.mock("animejs", () => ({
  default: Object.assign(
    (opts: { targets: unknown; update?: () => void }) => {
      opts.update?.();
      return { pause: vi.fn() };
    },
    { remove: vi.fn() },
  ),
}));

const CLIENTS = [
  { cn: "Brand Kit Test", cd: "Home Services", p: 10 },
  { cn: "Brand Kit Test", cd: "Dentistry", p: 55 },
  { cn: "Alligator Pools", cd: "Pools", p: 90 },
];

describe("a ring per client, even when two clients share a name", () => {
  it("renders every client, not just the distinctly-named ones", () => {
    const { container } = render(<ClientProgress clients={CLIENTS} />);
    // Keyed by name, this was 2 — the second "Brand Kit Test" vanished entirely and
    // the client it belonged to was simply absent from the dashboard.
    expect(container.querySelectorAll(".ring")).toHaveLength(3);
    expect(screen.getAllByText("Brand Kit Test")).toHaveLength(2);
  });

  it("gives each ring ITS OWN percentage, not the one at its position", () => {
    const { container } = render(<ClientProgress clients={CLIENTS} />);
    const rings = [...container.querySelectorAll<HTMLElement>(".ring")];
    // The value travels on the element being animated, so a name collision cannot
    // slide one client's number onto another client's ring.
    expect(rings.map((r) => r.dataset.p)).toEqual(["10", "55", "90"]);
    for (const ring of rings) {
      const label = ring.querySelector(".cn")?.textContent;
      const shown = ring.querySelector(".pv")?.textContent;
      const expected = CLIENTS.find((c) => c.cn === label && String(c.p) === shown);
      expect(expected, `ring "${label}" showed ${shown}`).toBeTruthy();
    }
  });

  it("survives the client list shrinking under it", () => {
    // `clients[idx]` threw a TypeError here: the effect re-ran against a DOM that
    // still held the previous render's rings while the array had already shortened.
    const { rerender, container } = render(<ClientProgress clients={CLIENTS} />);
    expect(() => rerender(<ClientProgress clients={[CLIENTS[0]]} />)).not.toThrow();
    expect(container.querySelectorAll(".ring")).toHaveLength(1);
  });

  it("renders nothing rather than failing when there are no active clients", () => {
    const { container } = render(<ClientProgress clients={[]} />);
    expect(container.querySelectorAll(".ring")).toHaveLength(0);
    expect(screen.getByText(/Active Client Progress/i)).toBeInTheDocument();
  });
});
