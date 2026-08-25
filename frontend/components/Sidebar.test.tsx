// The admin sidebar's user chip.
//
// It used to render three string literals: avatar "DA", name "Danyal", role "Super
// Admin". `useAuth()` was imported and destructured for `logout` alone, so the real
// signed-in identity sat one property away and was never read. Every operator, on
// every account, saw somebody else's name and an authority level that was not
// necessarily theirs.
//
// A chip that names the wrong person is worse than one that names nobody: it is the
// only place in the admin shell that answers "who am I signed in as", and it was
// answering confidently and wrongly.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Sidebar from "./Sidebar";
import type { Session } from "@/lib/auth";

let session: Session | null = null;
const logout = vi.fn();

vi.mock("next/navigation", () => ({ usePathname: () => "/admin" }));
vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return { ...actual, useAuth: () => ({ session, logout, ready: true, login: vi.fn() }) };
});

describe("Sidebar user chip", () => {
  it("shows the signed-in operator, not a hard-coded name", () => {
    session = { role: "admin", id: "u1", name: "Amara Okonkwo" };
    render(<Sidebar />);

    expect(screen.getByText("Amara Okonkwo")).toBeInTheDocument();
    expect(screen.getByText("AO")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    // The exact regression: the previous literals must not survive anywhere.
    expect(screen.queryByText("Danyal")).not.toBeInTheDocument();
    expect(screen.queryByText("DA")).not.toBeInTheDocument();
  });

  it("degrades to a neutral chip before the session hydrates", () => {
    session = null;
    render(<Sidebar />);

    expect(screen.getByText("Signed in")).toBeInTheDocument();
    expect(screen.queryByText("Danyal")).not.toBeInTheDocument();
  });

  it("puts no invented count on a nav badge", () => {
    // Policy Radar carried badge="3" — a literal, always three, regardless of how
    // many recommendations were open. A badge that cannot be wrong is a badge that
    // is not reading anything.
    session = { role: "admin", id: "u1", name: "Amara Okonkwo" };
    const { container } = render(<Sidebar />);

    const badges = [...container.querySelectorAll(".badge-n")].map((b) => b.textContent);
    expect(badges.filter((b) => b && /^\d+$/.test(b))).toEqual([]);
  });
});
