// Keeps stylesheets on the design tokens: sizes, weights, colors, spacing and
// radii come from app/src/styles/tokens.css, the one file that holds literals.
import fs from "node:fs";
import path from "node:path";
import { app } from "./dependencies.mjs";

const source = path.join(app, "src");
const tokens = path.join(source, "styles", "tokens.css");
const spacing =
  /^(margin|padding|gap|row-gap|column-gap|inset|top|right|bottom|left)(-[a-z-]+)?$/;
const length = /(?<![\w.-])(-?\d*\.?\d+)(px|rem|em)\b/g;
const color =
  /#[0-9a-f]{3,8}\b|\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|\b(white|black|red|green|blue|gray|grey|orange|yellow|purple|pink)\b/i;

const rules = [
  {
    test: (property) => property === "font-size",
    allowed: (value) => /^(var\(--font-[a-z-]+\)|inherit)$/.test(value),
    advice: "use a --font-* size token",
  },
  {
    test: (property) => property === "font-weight",
    allowed: (value) => /^(var\(--weight-[a-z]+\)|inherit)$/.test(value),
    advice: "use a --weight-* token",
  },
  {
    test: (property) => property === "font",
    allowed: (value) => value === "inherit" || !value.match(length),
    advice: "use the --font-* tokens instead of literal sizes",
  },
  {
    // Spacing follows the --space-* steps; 1px only aligns borders.
    test: (property) => spacing.test(property),
    allowed: (value) =>
      [...value.matchAll(length)].every(
        (match) => Math.abs(Number(match[1])) <= (match[2] === "px" ? 1 : 0),
      ),
    advice: "use a --space-* step",
  },
  {
    test: (property) => property.endsWith("radius"),
    allowed: (value) => !value.match(length),
    advice: "use --control-radius, --panel-radius or --dialog-radius",
  },
  {
    // Token names and url() contents (such as a mask's SVG) are not colors.
    test: () => true,
    allowed: (value) =>
      !color.test(
        value.replace(/var\(--[\w-]+/g, "").replace(/url\([^)]*\)/g, ""),
      ),
    advice: "use a named --color-* token",
  },
];

function files(folder) {
  return fs.readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(folder, entry.name);
    return entry.isDirectory()
      ? files(target)
      : entry.name.endsWith(".css") && target !== tokens
        ? [target]
        : [];
  });
}

// Comments and @font-face blocks keep their line breaks so reports stay exact.
const blank = (text) => text.replace(/[^\n]/g, " ");
const problems = [];
for (const file of files(source)) {
  const text = fs
    .readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/@font-face\s*\{[^}]*\}/g, blank);
  for (const match of text.matchAll(
    /(?<=[{;\s])(--)?([a-z-]+)\s*:\s*([^;{}]+?)\s*(?=[;}])/g,
  )) {
    if (match[1]) continue;
    const [property, value] = [match[2], match[3].replace(/\s+/g, " ")];
    const rule = rules.find(
      (item) => item.test(property) && !item.allowed(value),
    );
    if (!rule) continue;
    const line = text.slice(0, match.index).split("\n").length;
    problems.push(
      `${path.relative(process.cwd(), file)}:${line}: ${property}: ${value} - ${rule.advice} from tokens.css`,
    );
  }
}
if (problems.length) {
  console.error(problems.join("\n"));
  console.error(
    `${problems.length} style ${problems.length === 1 ? "value bypasses" : "values bypass"} the design tokens.`,
  );
  process.exit(1);
}
