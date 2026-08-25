// Changing your own password.
//
// `POST /me/password` and `useChangePassword` both existed and nothing called them:
// there was no way, anywhere in the product, for a signed-in person to change their
// own password. A team member's only route was to ask an admin to reset it — which
// hands their credential to another human, and is precisely what a self-service
// change exists to avoid.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AccountSettings from "./AccountSettings";

const changeMutate = vi.fn();

vi.mock("@/lib/hooks/portal", () => ({
  useChangePassword: () => ({ mutate: changeMutate, isPending: false, error: null }),
}));
vi.mock("@/lib/hooks/settings", () => ({
  useNotifPrefs: () => ({ data: [], isLoading: false, isError: false, error: null }),
  useUpdateNotifPrefs: () => ({ mutate: vi.fn(), isPending: false }),
  useMe: () => ({ data: { id: "u1", name: "Amara", title: "Lead", email: "a@x.com" }, isLoading: false, isError: false, error: null }),
  useUpdateMe: () => ({ mutate: vi.fn(), isPending: false }),
}));

beforeEach(() => changeMutate.mockClear());

async function fill(user: ReturnType<typeof userEvent.setup>, cur: string, next: string, confirm: string) {
  await user.type(screen.getByLabelText(/Current password/i), cur);
  await user.type(screen.getByLabelText(/^New password/i), next);
  await user.type(screen.getByLabelText(/Confirm new password/i), confirm);
}

describe("change password", () => {
  it("submits the current and new password", async () => {
    const user = userEvent.setup();
    render(<AccountSettings />);
    await fill(user, "OldPassw0rd!x", "BrandNewPassw0rd!", "BrandNewPassw0rd!");
    await user.click(screen.getByRole("button", { name: /Change password/i }));

    expect(changeMutate).toHaveBeenCalledTimes(1);
    expect(changeMutate.mock.calls[0][0]).toEqual({
      current_password: "OldPassw0rd!x",
      new_password: "BrandNewPassw0rd!",
    });
  });

  it("will not submit when the confirmation does not match", async () => {
    const user = userEvent.setup();
    render(<AccountSettings />);
    await fill(user, "OldPassw0rd!x", "BrandNewPassw0rd!", "Different!");
    expect(screen.getByText(/do not match/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Change password/i }));
    expect(changeMutate).not.toHaveBeenCalled();
  });

  it("will not submit a short password", async () => {
    const user = userEvent.setup();
    render(<AccountSettings />);
    await fill(user, "OldPassw0rd!x", "short", "short");
    expect(screen.getByText(/at least 12 characters/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Change password/i }));
    expect(changeMutate).not.toHaveBeenCalled();
  });

  it("will not submit without the current password", async () => {
    // The server verifies it; sending an empty one is a guaranteed round trip to a 4xx.
    const user = userEvent.setup();
    render(<AccountSettings />);
    await user.type(screen.getByLabelText(/^New password/i), "BrandNewPassw0rd!");
    await user.type(screen.getByLabelText(/Confirm new password/i), "BrandNewPassw0rd!");
    await user.click(screen.getByRole("button", { name: /Change password/i }));
    expect(changeMutate).not.toHaveBeenCalled();
  });
});
