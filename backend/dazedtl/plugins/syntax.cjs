// Parse source only. No plugin code or configuration expression executes.
const fs = require("node:fs");
const acorn = require("../../../app/node_modules/acorn");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const results = input.files.map(({ path, source, kind }) => {
  const issues = [],
    literals = [],
    plugins = [],
    comments = [];
  let tree,
    configurations = 0;
  try {
    tree = acorn.parse(source, {
      ecmaVersion: "latest",
      sourceType: "script",
      locations: true,
      onComment: comments,
    });
  } catch (e) {
    return { path, issues: [e.message], literals, plugins };
  }
  const byte = (p) => Buffer.byteLength(source.slice(0, p), "utf8");
  function constant(node) {
    if (!node) throw Error("Missing static configuration");
    if (
      node.type === "Literal" &&
      !node.regex &&
      typeof node.value !== "bigint"
    )
      return node.value;
    if (node.type === "TemplateLiteral" && !node.expressions.length)
      return node.quasis[0].value.cooked;
    if (node.type === "ArrayExpression") return node.elements.map(constant);
    if (node.type === "ObjectExpression") {
      const value = {};
      for (const p of node.properties) {
        if (
          p.type !== "Property" ||
          p.computed ||
          p.kind !== "init" ||
          p.method ||
          p.shorthand
        )
          throw Error("Configuration has a dynamic property");
        const key = p.key.name ?? p.key.value;
        if (typeof key !== "string" || Object.hasOwn(value, key))
          throw Error("Configuration has invalid or duplicate keys");
        Object.defineProperty(value, key, {
          value: constant(p.value),
          enumerable: true,
        });
      }
      return value;
    }
    throw Error(
      "Configuration must be a static literal array; expressions never execute",
    );
  }
  function walk(node, parents = []) {
    const parent = parents.at(-1);
    if (node.type === "VariableDeclarator" && node.id.name === "$plugins") {
      configurations++;
      try {
        const value = constant(node.init);
        if (!Array.isArray(value)) throw Error("$plugins must be an array");
        plugins.push(...value);
      } catch (e) {
        issues.push(e.message);
      }
    }
    const string = node.type === "Literal" && typeof node.value === "string";
    const template = node.type === "TemplateLiteral";
    if (string || template) {
      const expressions = template
        ? node.expressions.map((n) => source.slice(n.start, n.end))
        : [];
      let value = string ? node.value : node.quasis[0].value.cooked;
      if (template)
        for (let i = 0; i < expressions.length; i++)
          value +=
            "${" + expressions[i] + "}" + node.quasis[i + 1].value.cooked;
      const protectedNode =
        (parent?.type === "Property" && parent.key === node) ||
        (parent?.type === "MemberExpression" && parent.property === node) ||
        parent?.type === "SwitchCase" ||
        parent?.type === "ImportDeclaration" ||
        parent?.type === "ExportNamedDeclaration" ||
        (parent?.type === "BinaryExpression" &&
          ["==", "===", "!=", "!=="].includes(parent.operator)) ||
        parent?.type === "TaggedTemplateExpression" ||
        expressions.some((text) => /[\u3040-\u30ff\u3400-\u9fff]/.test(text));
      const chain = [];
      let cursor = node;
      for (const p of [...parents].reverse()) {
        if (p.type === "Property" && p.value === cursor)
          chain.unshift(p.key.name ?? p.key.value);
        if (p.type === "ArrayExpression")
          chain.unshift(p.elements.indexOf(cursor));
        cursor = p;
      }
      literals.push({
        start: byte(node.start),
        end: byte(node.end),
        value,
        raw: source.slice(node.start, node.end),
        expressions,
        protected: !!protectedNode,
        kind: template && expressions.length ? "template" : "literal",
        line: node.loc.start.line,
        column: node.loc.start.column + 1,
        path: chain,
      });
      if (template) return; // Embedded expressions are immutable parts of this occurrence.
    }
    for (const [key, value] of Object.entries(node)) {
      if (["loc", "start", "end"].includes(key)) continue;
      if (Array.isArray(value)) {
        for (const child of value)
          if (child && typeof child.type === "string")
            walk(child, [...parents, node]);
      } else if (value && typeof value.type === "string")
        walk(value, [...parents, node]);
    }
  }
  walk(tree);
  for (const comment of comments)
    for (const match of comment.value.matchAll(/@default[ \t]+([^\r\n]*)/g)) {
      const start =
          comment.start + 2 + match.index + match[0].length - match[1].length,
        end = start + match[1].length;
      literals.push({
        start: byte(start),
        end: byte(end),
        value: match[1],
        raw: match[1],
        expressions: [],
        protected: false,
        kind: "default",
        line: source.slice(0, start).split("\n").length,
        column: 1,
        path: [],
      });
    }
  literals.sort((a, b) => a.start - b.start);
  if (kind === "parameters" && configurations !== 1)
    issues.push("Exactly one static $plugins array is required");
  return { path, issues, literals, plugins };
});
process.stdout.write(JSON.stringify(results));
