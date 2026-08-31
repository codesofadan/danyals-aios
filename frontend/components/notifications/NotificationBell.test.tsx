// The notification bell.
//
// The backend delivery layer was complete and had ZERO frontend readers: `notify()`
// wrote rows nobody could see, while Settings offered per-event toggles for
// notifications the product never displayed. This is the surface that reads them, so
// the properties worth pinning are about honesty and cost, not layout:
//
//   * the badge shows a REAL count and nothing when there is none. The only badge
//     this app shipped before was the literal "3" pinned to Policy Radar;
//   * bodies are fetched only when the panel is open — the bell is on all 26 pages
//     and polls, so an always-on list fetch would be the app's most expensive habit;
//   * a portal client sees an inbox but never the staff alert queue, which the API
//     403s them from anyway.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationBell from "./NotificationBell";
import type { AppNotification } from "@/lib/notifications";
import type { Session } from "@/lib/auth";

let session: Session | null = { role: "admin", id: "u1", name: "Amara" };
let unread = 0;
let items: AppNotification[] = [];
const listEnabled: boolean[] = [];
const alertsEnabled: boolean[] = [];
const toastsEnabled: boolean[] = [];
const markAll = vi.fn();
const markRead = vi.fn();

vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return { ...actual, useAuth: () => ({ session, ready: true, login: vi.fn(), logout: vi.fn() }) };
});

vi.mock("@/lib/hooks/notifications", () => ({
  useUnreadCount: () => ({ data: { unread } }),
  useNotifications: (enabled: boolean) => {
    listEnabled.push(enabled);
    return { data: items, isLoading: false, isError: false, error: null, refetch: vi.fn() };
  },
  useAlerts: (enabled: boolean) => {
    alertsEnabled.push(enabled);
    return { data: [], isLoading: false, isError: false, error: null };
  },
  useMarkNotificationRead: () => ({ mutate: markRead, isPending: false }),
  useMarkAllRead: () => ({ mutate: markAll, isPending: false }),
  useAcknowledgeAlert: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  // The arrival-toast hook. Its own behaviour is pinned in
  // lib/hooks/notificationToasts.test.tsx; here it only needs to record whether the
  // bell suppresses it while the panel is open.
  useNotificationToasts: (enabled: boolean) => { toastsEnabled.push(enabled); },
}));

beforeEach(() => {
  session = { role: "admin", id: "u1", name: "Amara" };
  unread = 0;
  items = [];
  listEnabled.length = 0;
  alertsEnabled.length = 0;
  toastsEnabled.length = 0;
  markAll.mockClear();
  markRead.mockClear();
});

describe("NotificationBell", () => {
  it("shows no badge when nothing is unread", () => {
    const { container } = render(<NotificationBell />);
    expect(container.querySelector(".nb-badge")).toBeNull();
  });

  it("shows the real unread count", () => {
    unread = 4;
    render(<NotificationBell />);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByLabelText(/4 unread/i)).toBeInTheDocument();
  });

  it("caps an absurd count rather than breaking the badge", () => {
    unread = 512;
    render(<NotificationBell />);
    expect(screen.getByText("99+")).toBeInTheDocument();
  });

  it("does not fetch the inbox until the panel is opened", async () => {
    const user = userEvent.setup();
    render(<NotificationBell />);
    // The bell is mounted on every page and polls; fetching bodies for a closed
    // panel would make this the most expensive query in the product.
    expect(listEnabled.every((e) => e === false)).toBe(true);

    await user.click(screen.getByRole("button", { name: /Notifications/i }));
    expect(listEnabled.at(-1)).toBe(true);
  });

  it("renders the inbox and marks one read on click", async () => {
    const user = userEvent.setup();
    unread = 1;
    items = [
      { id: "n1", kind: "task_assigned", title: "Task assigned", body: "J-1042 is yours", read: false, createdAt: new Date().toISOString() },
      { id: "n2", kind: "audit_done", title: "Audit finished", body: "", read: true, createdAt: new Date().toISOString() },
    ];
    render(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: /Notifications/i }));

    expect(screen.getByText("Task assigned")).toBeInTheDocument();
    await user.click(screen.getByText("Task assigned"));
    expect(markRead).toHaveBeenCalledWith("n1");

    // An already-read row must not fire a pointless write.
    markRead.mockClear();
    await user.click(screen.getByText("Audit finished"));
    expect(markRead).not.toHaveBeenCalled();
  });

  it("offers mark-all-read only when there is something to clear", async () => {
    const user = userEvent.setup();
    render(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: /Notifications/i }));
    expect(screen.queryByRole("button", { name: /Mark all read/i })).not.toBeInTheDocument();
  });

  it("never offers the staff alert queue to a portal client", async () => {
    const user = userEvent.setup();
    session = { role: "client", id: "c1", name: "Bellevue Dental" };
    render(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: /Notifications/i }));

    // The API 403s a client from /alerts; the chrome should not imply otherwise.
    expect(screen.queryByRole("tab", { name: /Alerts/i })).not.toBeInTheDocument();
    expect(alertsEnabled.every((e) => e === false)).toBe(true);
  });

  it("stops announcing arrivals while the panel is open", async () => {
    const user = userEvent.setup();
    render(<NotificationBell />);
    expect(toastsEnabled.at(-1)).toBe(true);
    await user.click(screen.getByRole("button", { name: /Notifications/i }));
    // The operator is looking at the inbox — toasting what is already on screen is noise.
    expect(toastsEnabled.at(-1)).toBe(false);
  });

  it("renders nothing at all when signed out", () => {
    session = null;
    const { container } = render(<NotificationBell />);
    expect(container).toBeEmptyDOMElement();
  });
});
