/**
 * The end of a log in at most six lines and `limit` characters, starting at
 * a line, or within a last line longer than that, at a word.
 */
export function tailExcerpt(text: string, limit: number) {
  const lines = text.split("\n").slice(-6);
  while (lines.length > 1 && lines.join("\n").length > limit) lines.shift();
  const excerpt = lines.join("\n");
  if (excerpt.length <= limit) return excerpt;
  const start = excerpt.length - limit;
  const cut = excerpt.slice(start);
  return /\s/.test(excerpt[start - 1])
    ? cut
    : cut.replace(/^\S*\s+/, "") || cut;
}
