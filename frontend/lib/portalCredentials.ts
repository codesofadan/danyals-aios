// ============================================================
// Portal login generation, once.
//
// These lived inside AddClientWizard, where they were the wizard's private
// business. Then QA found clients who could not sign in, and the repair needed
// the SAME pair-shape from two more places: re-provisioning a login whose
// creation failed, and resetting one whose password was never captured. Three
// copies of "what a portal credential looks like" is how the wizard's generated
// password and the server's stored one drift apart without anyone noticing.
//
// The password is a REAL stored credential (the server argon2-hashes exactly this
// string), so the randomness is crypto, not Math.random.
// ============================================================

const ADJ = ["Solar", "Rapid", "Cobalt", "Lunar", "Amber", "Quartz", "Nimbus", "Vivid", "Onyx", "Cedar", "Zephyr", "Crimson"];
const NOUN = ["Falcon", "Harbor", "Cipher", "Meadow", "Quasar", "Lynx", "Beacon", "Vertex", "Willow", "Ember", "Comet", "Delta"];
const SYM = "!@#$%&*?";

function rand(n: number): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] % n;
}

function pick<T>(arr: T[]): T {
  return arr[rand(arr.length)];
}

/** Mirrors the server's shape: Adjective-Noun####$xxxxxx (4 digits + symbol + 6 hex). */
export function genPortalPassword(): string {
  const digits = String(1000 + rand(9000));
  const sym = SYM[rand(SYM.length)];
  const tail = Array.from({ length: 6 }, () => "0123456789abcdef"[rand(16)]).join("");
  return `${pick(ADJ)}-${pick(NOUN)}${digits}${sym}${tail}`;
}

/**
 * Portal login as `<first-name>@aios.com`, from the contact's name (falling back
 * to the company name). Never the client's own email/domain — it is an AIOS portal
 * login, and reusing their address would collide with a staff account on the same
 * case-insensitive unique index.
 */
export function genPortalLogin(contactName: string, client: string): string {
  const source = contactName.trim() || client.trim();
  const first = source.split(/\s+/)[0].toLowerCase().replace(/[^a-z0-9]/g, "");
  return `${first || "client"}@aios.com`;
}
