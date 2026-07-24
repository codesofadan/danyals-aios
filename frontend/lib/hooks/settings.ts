"use client";

// ============================================================
// AIOS · settings data hooks
// The Settings screen's "My Account" tab reuses GET /me (profile) · PATCH /me ·
// POST /me/password (change password) — the same hooks the team portal owns,
// re-exported here so the screen has one hooks entrypoint. The roles matrix
// reuses useRbac(); the credential panels reuse useMembers() (with
// useRevealCredentials / useSetPassword) + useClients(). None are duplicated here.
//
// (The former workspace / security / notification-preference hooks were removed
// with their orphaned, unreachable panels — those /settings/* endpoints are not
// surfaced anywhere in the trimmed Settings screen.)
// ============================================================

export { useMe, useUpdateMe, useChangePassword } from "./portal";
