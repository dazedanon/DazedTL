// The command-line check the scripts that start apps, displays or long checks
// share: an option a script does not know, or one missing its value, stops it
// with its usage before it starts anything, and --help prints that usage.
import fs from "node:fs";

/**
 * Reads `args` (the words after the script's name) against `known`, each
 * option's kind: "value" takes the word after it, "flag" stands alone.
 * Throws a usage error for an unknown option, a value option without its
 * value, or a word that is no option when `positionals` is false.
 * @param {string[]} args
 * @param {Record<string, "value" | "flag">} known
 * @param {{ positionals?: boolean }} [rules]
 * @returns {{ help: boolean, values: Map<string, string | true>, positional: string[] }}
 */
function parseOptions(args, known, { positionals = false } = {}) {
  const values = new Map();
  const positional = [];
  for (let index = 0; index < args.length; index++) {
    const word = args[index];
    if (word === "--help" || word === "-h")
      return { help: true, values, positional };
    if (word.startsWith("-")) {
      const kind = known[word];
      if (!kind) throw new UsageError(`Unknown option ${word}.`);
      if (kind === "flag") values.set(word, true);
      else {
        const value = args[++index];
        if (value === undefined || value.startsWith("--"))
          throw new UsageError(`${word} needs a value.`);
        values.set(word, value);
      }
    } else if (positionals) positional.push(word);
    else throw new UsageError(`Unexpected argument ${word}.`);
  }
  return { help: false, values, positional };
}

class UsageError extends Error {}

/**
 * This process's options, read with parseOptions. Prints `usage` and exits:
 * with 0 for --help, and with 2 and the reason for a usage error.
 * @param {string} usage
 * @param {Record<string, "value" | "flag">} known
 * @param {{ positionals?: boolean }} [rules]
 */
export function readOptions(usage, known, rules) {
  try {
    const parsed = parseOptions(process.argv.slice(2), known, rules);
    if (parsed.help) {
      // Written at once, since the process exits before a pipe would drain.
      fs.writeSync(1, `${usage}\n`);
      process.exit(0);
    }
    const option = (/** @type {string} */ name) => {
      const value = parsed.values.get(name);
      return typeof value === "string" ? value : undefined;
    };
    return {
      option,
      flag: (/** @type {string} */ name) => parsed.values.has(name),
      given: [...parsed.values.keys()],
      positional: parsed.positional,
      /** Stops with `reason` and the usage, before anything starts. */
      refuse: (/** @type {string} */ reason) => refuse(usage, reason),
    };
  } catch (error) {
    if (error instanceof UsageError) refuse(usage, error.message);
    throw error;
  }
}

/** @returns {never} */
function refuse(/** @type {string} */ usage, /** @type {string} */ reason) {
  fs.writeSync(2, `${reason}\n\n${usage}\n`);
  process.exit(2);
}

/** The live test's options, which `scenario.mjs live` passes on to it. */
export const e2eOptions = Object.freeze({
  "--work": "value",
  "--upgrade-from": "value",
});
