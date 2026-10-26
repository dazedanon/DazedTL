// Reads a game's plugin code without running any of it: whether each enabled
// plugin compiles as a browser script, and every string in it holding the
// game's source language with the evidence for whether players can see it.
//
// stdin: {acorn, plugins: [{name, file, parameters, commands}], core: [file],
//         tokens: [name], source: {pattern, placeholders, phrases}}
// stdout: [{name, issue?, unreadable?, literals: [...]}]
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const acorn = require(input.acorn);

// Source text (util/playtest/run.reading), and the glyphs Japanese text uses
// for a hidden word, as in "Day ◯/30", which read as a missing character in
// another script.
const SOURCE = new RegExp(input.source.pattern);
// Words a Latin source's string must read as, since its identifiers hold
// letters too: two of them, or one ending a sentence.
const PHRASE = input.source.phrases
  ? /\p{L}\s+\p{L}|\p{L}[.!?…]+\s*$/u
  : /(?:)/;
const PLACEHOLDER = input.source.placeholders ? /[◯〇]|○○/ : /(?!)/;
// Sentence punctuation no asset name holds.
const SENTENCE = /[。、！？!?…「」『』（）"“”]|\.\s/;
const TEXT_LIMIT = 160;
// Calls whose first argument is matched against text, never shown.
const MATCHERS = new Set([
  "startsWith",
  "endsWith",
  "indexOf",
  "lastIndexOf",
  "includes",
  "match",
  "matchAll",
  "replace",
  "replaceAll",
  "split",
  "search",
  "test",
]);
// Objects whose calls take asset names, ids or registry keys.
const ASSET_OWNERS = new Set([
  "ImageManager",
  "AudioManager",
  "Bitmap",
  "FontManager",
  "EffectManager",
  "PluginManager",
  "StorageManager",
  "DataManager",
]);
// Properties that hold an asset's name.
const ASSET_KEYS = new Set([
  "faceName",
  "characterName",
  "battlerName",
  "picture",
  "pic",
  "image",
  "img",
  "cg",
  "file",
  "filename",
  "fileName",
  "bgm",
  "bgs",
  "me",
  "se",
  "voice",
  "sound",
  "src",
  "icon",
  "movie",
  "video",
]);
// Properties beside a name that make it a picture's or a sound's.
const ASSET_SPEC = new Set([
  "volume",
  "pitch",
  "pan",
  "scale",
  "x",
  "y",
  "opacity",
  "blendMode",
  "origin",
  "hue",
]);
// A file name, as in arina_服_通常.png.
const ASSET_FILE =
  /^[^\s]+\.(?:png|png_|rpgmvp|ogg|ogg_|rpgmvo|m4a|m4a_|rpgmvm|webm|mp4|json|js|txt|csv|woff2?|ttf|otf)$/i;

/** Whether a string names an asset: a file name, a folder path such as
 * 07痴漢2/痴漢＿胸 (14), or a name joined by underscores such as
 * 断面図_01_未挿入, which sentences never look like. */
const assetPath = (value) =>
  ASSET_FILE.test(value.trim()) ||
  (value.includes("/") &&
    !SENTENCE.test(value) &&
    value
      .split("/")
      .every((part) => part.length <= 40 && part.split(/\s/).length <= 3)) ||
  /^[^\s　。、！？!?…「」]+_[^\s　]+$/.test(value.trim());
// A script line's speaker tag, as in ア:Eek!, which its parser matches and
// players never see.
const SPEAKER_TAG = /^[ \t]*[^\s:：]{1,6}[:：]/gm;
// Calls that put their text straight on screen.
const DRAWING = new Set([
  "drawText",
  "drawTextEx",
  "addText",
  "setText",
  "drawWrapped",
]);

const text = (value) =>
  value.length > TEXT_LIMIT ? value.slice(0, TEXT_LIMIT) + "…" : value;

/** Every identifier and property name code uses, which keeps a function
 * defined under that name reachable. */
function uses(tree, into) {
  walk(tree, (node, parent) => {
    if (node.type === "Identifier" && !defines(node, parent))
      into.add(node.name);
    if (
      node.type === "Literal" &&
      typeof node.value === "string" &&
      /^[A-Za-z_$][\w$]*$/.test(node.value)
    )
      into.add(node.value);
  });
}

/** Whether an identifier names what its parent defines rather than a use. */
function defines(node, parent) {
  if (!parent) return false;
  if (parent.type === "FunctionDeclaration" && parent.id === node) return true;
  if (parent.type === "MethodDefinition" && parent.key === node) return true;
  if (
    parent.type === "Property" &&
    parent.key === node &&
    !parent.computed &&
    isFunction(parent.value)
  )
    return true;
  if (
    parent.type === "VariableDeclarator" &&
    parent.id === node &&
    (isFunction(parent.init) || isData(parent.init))
  )
    return true;
  if (
    parent.type === "MemberExpression" &&
    parent.property === node &&
    !parent.computed &&
    parent.assigned
  )
    return true;
  return false;
}

const isFunction = (node) =>
  !!node &&
  ["FunctionExpression", "ArrowFunctionExpression", "ClassExpression"].includes(
    node.type,
  );
const isData = (node) =>
  !!node && ["ObjectExpression", "ArrayExpression"].includes(node.type);

/** Visits every node with its parent; marks assigned members first. */
function walk(node, visit, parent = null) {
  if (!node || typeof node.type !== "string") return;
  if (
    node.type === "AssignmentExpression" &&
    node.left.type === "MemberExpression" &&
    isFunction(node.right)
  )
    node.left.assigned = true;
  visit(node, parent);
  for (const [key, value] of Object.entries(node)) {
    if (key === "loc" || key === "assigned") continue;
    if (Array.isArray(value))
      for (const child of value) walk(child, visit, node);
    else if (value && typeof value.type === "string") walk(value, visit, node);
  }
}

/** The name code calls a function by: its declaration, the member it is
 * assigned to, its method or property key, or its variable. */
function functionName(node, parent) {
  if (node.id?.name) return node.id.name;
  if (!parent) return "";
  if (parent.type === "MethodDefinition" || parent.type === "Property")
    return parent.computed ? "" : (parent.key.name ?? String(parent.key.value));
  if (parent.type === "VariableDeclarator") return parent.id.name || "";
  if (
    parent.type === "AssignmentExpression" &&
    parent.left.type === "MemberExpression" &&
    !parent.left.computed
  )
    return parent.left.property.name;
  return "";
}

/** Where a member assignment's owner lives, such as Window_Foo.prototype. */
function owner(parent) {
  if (
    parent?.type !== "AssignmentExpression" ||
    parent.left.type !== "MemberExpression"
  )
    return "";
  const object = parent.left.object;
  if (object.type === "Identifier") return object.name;
  if (
    object.type === "MemberExpression" &&
    object.object.type === "Identifier" &&
    object.property.name === "prototype"
  )
    return object.object.name + ".prototype";
  return "";
}

/**
 * Reads constant values: literals, constants bound once and never assigned,
 * the plugin's own parameters and the few operators flags are built from.
 */
class Constants {
  constructor(tree, plugin) {
    this.plugin = plugin.name;
    this.parameters = plugin.parameters || {};
    this.source = plugin.source;
    this.bound = new Map();
    this.assigned = new Set();
    walk(tree, (node) => {
      if (node.type === "VariableDeclarator" && node.id.type === "Identifier")
        this.bound.set(
          node.id.name,
          this.bound.has(node.id.name) ? null : node.init,
        );
      // A parameter that shares a constant's name hides it in its function.
      if (isFunction(node) || node.type === "FunctionDeclaration")
        for (const param of node.params || [])
          walk(param, (inner) => {
            if (inner.type === "Identifier") this.bound.set(inner.name, null);
          });
      if (
        node.type === "AssignmentExpression" &&
        node.left.type === "Identifier"
      )
        this.assigned.add(node.left.name);
      if (
        node.type === "UpdateExpression" &&
        node.argument.type === "Identifier"
      )
        this.assigned.add(node.argument.name);
    });
    this.seen = new Set();
  }

  /** The value, or undefined when it is not constant. */
  value(node) {
    if (!node) return undefined;
    switch (node.type) {
      case "Literal":
        return node.regex ? undefined : node.value;
      case "TemplateLiteral":
        return node.expressions.length
          ? undefined
          : node.quasis[0].value.cooked;
      case "Identifier": {
        if (node.name === "undefined") return undefined;
        const init = this.bound.get(node.name);
        if (!init || this.assigned.has(node.name) || this.seen.has(node.name))
          return undefined;
        this.seen.add(node.name);
        try {
          return this.value(init);
        } finally {
          this.seen.delete(node.name);
        }
      }
      case "UnaryExpression": {
        if (node.operator === "void") return undefined;
        const value = this.value(node.argument);
        if (value === undefined) return undefined;
        if (node.operator === "!") return !value;
        if (node.operator === "-") return -value;
        if (node.operator === "+") return +value;
        return undefined;
      }
      case "BinaryExpression": {
        const left = this.value(node.left);
        const right = this.value(node.right);
        if (left === undefined || right === undefined) return undefined;
        if (node.operator === "===") return left === right;
        if (node.operator === "!==") return left !== right;
        if (node.operator === "==") return left == right;
        if (node.operator === "!=") return left != right;
        return undefined;
      }
      case "LogicalExpression": {
        const left = this.value(node.left);
        if (left === undefined) return undefined;
        if (node.operator === "&&") return left ? this.value(node.right) : left;
        if (node.operator === "||") return left ? left : this.value(node.right);
        return left ?? this.value(node.right);
      }
      case "CallExpression":
        return this.call(node);
      case "MemberExpression":
        return this.member(node);
      default:
        return undefined;
    }
  }

  call(node) {
    const callee = node.callee;
    const argument = node.arguments[0];
    if (callee.type === "Identifier") {
      const value = this.value(argument);
      if (value === undefined) return undefined;
      if (callee.name === "String") return String(value);
      if (callee.name === "Number") return Number(value);
      if (callee.name === "Boolean") return Boolean(value);
      return undefined;
    }
    if (callee.type !== "MemberExpression" || callee.computed) return undefined;
    const method = callee.property.name;
    if (callee.object.type === "Identifier" && callee.object.name === "JSON") {
      const value = this.value(argument);
      if (method !== "parse" || typeof value !== "string") return undefined;
      try {
        return JSON.parse(value);
      } catch {
        return undefined;
      }
    }
    if (
      callee.object.type === "Identifier" &&
      callee.object.name === "PluginManager" &&
      method === "parameters"
    ) {
      // A name read from document.currentScript is the plugin's own.
      const name = this.value(argument);
      return name === undefined || name === this.plugin
        ? this.parameters
        : undefined;
    }
    const value = this.value(callee.object);
    if (typeof value !== "string") return undefined;
    if (method === "toLowerCase") return value.toLowerCase();
    if (method === "toUpperCase") return value.toUpperCase();
    if (method === "trim") return value.trim();
    return undefined;
  }

  member(node) {
    const object = this.value(node.object);
    if (!object || typeof object !== "object") return undefined;
    const key = node.computed ? this.value(node.property) : node.property.name;
    if (typeof key !== "string" || !Object.hasOwn(object, key))
      return undefined;
    return object[key];
  }

  /** The condition's source, shortened, for a reason a reader can check. */
  quote(node) {
    const code = this.source.slice(node.start, node.end).replace(/\s+/g, " ");
    return code.length > 60 ? code.slice(0, 60) + "…" : code;
  }
}

/** Whether a literal names something rather than showing text. */
function named(node, parent, grand) {
  if (!parent) return false;
  // A plugin parameter's name, as in getParamNumber(["ClockX", "時計X座標"]).
  const call =
    parent.type === "ArrayExpression" &&
    grand?.type === "CallExpression" &&
    grand.arguments.includes(parent)
      ? grand
      : parent.type === "CallExpression" && parent.arguments.includes(node)
        ? parent
        : null;
  const callee = call?.callee;
  const callName =
    callee?.type === "Identifier"
      ? callee.name
      : callee?.type === "MemberExpression" && !callee.computed
        ? callee.property.name
        : "";
  if (/^get(?:Param|Parameter|Arg|Meta)/i.test(callName)) return true;
  if (parent.type === "Property" && parent.key === node) return true;
  if (parent.type === "MemberExpression" && parent.property === node)
    return true;
  if (parent.type === "SwitchCase") return true;
  if (
    parent.type === "BinaryExpression" &&
    ["==", "===", "!=", "!==", "in"].includes(parent.operator)
  )
    return true;
  if (parent.type === "TaggedTemplateExpression") return true;
  // Patterns, errors only a crash shows, and the console.
  if (
    parent.type === "NewExpression" &&
    ["RegExp", "Error", "TypeError", "RangeError"].includes(parent.callee.name)
  )
    return true;
  if (
    parent.type === "CallExpression" &&
    parent.callee.type === "MemberExpression" &&
    parent.callee.object.type === "Identifier" &&
    parent.callee.object.name === "console"
  )
    return true;
  if (
    (parent.type === "CallExpression" || parent.type === "NewExpression") &&
    parent.callee.type === "MemberExpression"
  ) {
    const callee = parent.callee;
    const method = callee.computed ? "" : callee.property.name;
    if (MATCHERS.has(method) && parent.arguments[0] === node) return true;
    let root = callee.object;
    while (root.type === "MemberExpression") root = root.object;
    if (root.type === "Identifier" && ASSET_OWNERS.has(root.name)) return true;
    if (method === "registerCommand" && parent.arguments[1] === node)
      return true;
    if (method === "showPicture" && parent.arguments[1] === node) return true;
    if (method === "loadBitmap") return true;
  }
  if (parent.type === "Property" && parent.value === node && !parent.computed) {
    const key = parent.key.name ?? parent.key.value;
    if (ASSET_KEYS.has(key)) return true;
    // A picture's or a sound's settings, {name, scale, x, y} or
    // {name, volume, pitch, pan}.
    if (
      key === "name" &&
      grand?.type === "ObjectExpression" &&
      grand.properties.some((property) =>
        ASSET_SPEC.has(property.key?.name ?? property.key?.value),
      )
    )
      return true;
  }
  return false;
}

/** Whether a literal is passed straight to a call that draws it. */
function drawn(node, parent) {
  if (parent?.type !== "CallExpression" || !parent.arguments.includes(node))
    return false;
  const callee = parent.callee;
  if (callee.type !== "MemberExpression" || callee.computed) return false;
  const method = callee.property.name;
  if (DRAWING.has(method)) return true;
  return (
    method === "add" &&
    callee.object.type === "Identifier" &&
    callee.object.name === "$gameMessage"
  );
}

function syntaxIssue(source, file) {
  try {
    new vm.Script(source, { filename: file });
    return null;
  } catch (error) {
    if (!(error instanceof SyntaxError)) return null;
    const [where, code = "", marks = ""] = String(error.stack).split("\n");
    const line = Number(/:(\d+)$/.exec(where)?.[1] || 0);
    const column = marks.indexOf("^") + 1;
    return {
      message: error.message,
      line,
      column: column > 0 ? column : 0,
      code: text(code.trim()),
    };
  }
}

function parse(source, locations = false) {
  return acorn.parse(source, {
    ecmaVersion: "latest",
    sourceType: "script",
    allowHashBang: true,
    allowReturnOutsideFunction: true,
    locations,
  });
}

const used = new Set(input.tokens || []);
for (const file of input.core || []) {
  try {
    uses(parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, "")), used);
  } catch {
    // An engine script that can't be read leaves its names out.
  }
}

const plugins = input.plugins.map((plugin) => {
  let source;
  try {
    source = fs.readFileSync(plugin.file, "utf8").replace(/^\uFEFF/, "");
  } catch (error) {
    return { name: plugin.name, missing: String(error.code || error.message) };
  }
  const issue = syntaxIssue(source, plugin.file);
  if (issue) return { name: plugin.name, issue };
  let tree;
  try {
    tree = parse(source, true);
  } catch (error) {
    return { name: plugin.name, unreadable: error.message };
  }
  uses(tree, used);
  return { ...plugin, source, tree };
});

/** Each literal of one plugin holding source text, with its reach. */
function literals(plugin) {
  const constants = new Constants(plugin.tree, plugin);
  const commands = new Set(plugin.commands || []);
  // Folders the plugin's asset paths name, which a string may name alone,
  // and constants code only matches characters against, such as a line
  // breaker's "、。！？".
  const folders = new Set();
  const matched = new Map();
  walk(plugin.tree, (node, parent) => {
    if (
      node.type === "Identifier" &&
      !(parent?.type === "VariableDeclarator" && parent.id === node) &&
      !defines(node, parent)
    )
      matched.set(
        node.name,
        (matched.get(node.name) ?? true) &&
          parent?.type === "MemberExpression" &&
          parent.object === node &&
          (MATCHERS.has(parent.property.name) ||
            parent.property.name === "length"),
      );
    if (
      node.type === "Literal" &&
      typeof node.value === "string" &&
      assetPath(node.value)
    )
      for (const folder of node.value.split("/").slice(0, -1))
        folders.add(folder.trim());
  });
  const found = [];
  // The reasons the code around a node cannot run, innermost last.
  const visit = (node, ancestors, dead) => {
    if (!node || typeof node.type !== "string") return;
    const parent = ancestors.at(-1);
    let reason = dead;
    if (isFunction(node) || node.type === "FunctionDeclaration") {
      const name = functionName(node, parent);
      const grand = ancestors.at(-2);
      if (
        parent?.type === "CallExpression" &&
        parent.callee.type === "MemberExpression" &&
        parent.callee.property?.name === "registerCommand" &&
        parent.arguments[2] === node
      ) {
        const command = constants.value(parent.arguments[1]);
        if (typeof command === "string" && !commands.has(command))
          reason ||= {
            reach: "uncalled",
            evidence: `It is in the command ${command}, which no event calls.`,
          };
      } else if (name && !used.has(name) && !reason) {
        const where = owner(parent) || owner(grand);
        reason = {
          reach: "uncalled",
          evidence: `It is in ${where ? where + "." : ""}${name}, which nothing calls.`,
        };
      }
    }
    if (
      node.type === "VariableDeclarator" &&
      node.id.type === "Identifier" &&
      isData(node.init) &&
      !used.has(node.id.name) &&
      !reason
    )
      reason = {
        reach: "uncalled",
        evidence: `It is in ${node.id.name}, which nothing uses.`,
      };
    const string =
      node.type === "Literal" && typeof node.value === "string"
        ? node.value
        : node.type === "TemplateLiteral"
          ? node.quasis.map((quasi) => quasi.value.cooked ?? "").join("…")
          : null;
    const shown = string?.replace(SPEAKER_TAG, "");
    const characters =
      parent?.type === "VariableDeclarator" &&
      parent.id.type === "Identifier" &&
      matched.get(parent.id.name) === true;
    if (
      string !== null &&
      !characters &&
      ((SOURCE.test(shown) && PHRASE.test(shown)) || PLACEHOLDER.test(shown)) &&
      !named(node, parent, ancestors.at(-2)) &&
      !assetPath(string) &&
      !folders.has(string.trim())
    ) {
      found.push({
        line: node.loc.start.line,
        column: node.loc.start.column + 1,
        text: text(string),
        ...(!SOURCE.test(shown) && { glyph: true }),
        ...(reason ||
          (drawn(node, parent)
            ? { reach: "drawn", evidence: "It is drawn on screen directly." }
            : { reach: "may-show", evidence: "" })),
      });
      if (node.type === "TemplateLiteral") return;
    }
    const next = [...ancestors, node];
    // A branch whose condition is always false never runs, and nor does the
    // rest of a block after a guard that always returns.
    if (node.type === "IfStatement" || node.type === "ConditionalExpression") {
      const value = constants.value(node.test);
      visit(node.test, next, reason);
      const off = (branch) =>
        reason || {
          reach: "disabled",
          evidence: `It runs only ${branch} ${constants.quote(node.test)}, which is always ${branch === "if" ? "false" : "true"}.`,
        };
      visit(
        node.consequent,
        next,
        value !== undefined && !value ? off("if") : reason,
      );
      visit(
        node.alternate,
        next,
        value !== undefined && value ? off("unless") : reason,
      );
      return;
    }
    if (node.type === "LogicalExpression") {
      const value = constants.value(node.left);
      visit(node.left, next, reason);
      const skipped =
        value !== undefined &&
        ((node.operator === "&&" && !value) ||
          (node.operator === "||" && value));
      visit(
        node.right,
        next,
        skipped
          ? reason || {
              reach: "disabled",
              evidence: `It runs only past ${constants.quote(node.left)}, which never lets it.`,
            }
          : reason,
      );
      return;
    }
    if (node.type === "BlockStatement" || node.type === "Program") {
      let after = reason;
      for (const statement of node.body) {
        visit(statement, next, after);
        if (
          !after &&
          statement.type === "IfStatement" &&
          !statement.alternate &&
          exits(statement.consequent) &&
          constants.value(statement.test)
        )
          after = {
            reach: "disabled",
            evidence: `It comes after a return when ${constants.quote(statement.test)}, which is always true.`,
          };
      }
      return;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === "loc" || key === "assigned") continue;
      if (Array.isArray(value))
        for (const child of value) visit(child, next, reason);
      else if (value && typeof value.type === "string")
        visit(value, next, reason);
    }
  };
  visit(plugin.tree, [], null);
  return found;
}

/** Whether a statement always leaves its function. */
function exits(node) {
  if (!node) return false;
  if (node.type === "ReturnStatement" || node.type === "ThrowStatement")
    return true;
  return node.type === "BlockStatement" && node.body.length > 0
    ? exits(node.body.at(-1))
    : false;
}

const results = plugins.map((plugin) =>
  plugin.tree ? { name: plugin.name, literals: literals(plugin) } : plugin,
);
process.stdout.write(JSON.stringify(results));
