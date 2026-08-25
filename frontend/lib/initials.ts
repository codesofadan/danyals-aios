// Avatar initials, derived from a display name. One implementation, because three
// shells render a user chip and each one deriving its own would drift.
//
// A pure display transform — never a source of identity. The admin sidebar used to
// hard-code "DA" / "Danyal" / "Super Admin" as literals, so every operator signed in
// as somebody else's name.
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}
