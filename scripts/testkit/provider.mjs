// A local stand-in for an OpenAI-compatible provider, free and offline, for
// the live test and test scenarios. It answers chat completions and OpenAI's
// Batch file API like a model that translates every line, Guided's LineN
// requests and Assistant-led's numbered ones, and its behavior can change
// while it runs through <folder>/mode.json:
//
//   { "refuse": ["text"], "decline": ["text"], "fail": ["text"],
//     "failStatus": 400, "failError": null, "failFirst": false, "stall": false, "answer": null,
//     "delay": 0, "hold": false,
//     "batchSeconds": 0, "long": ["text"], "reply": { "text": "reply" },
//     "target": null, "effort": null, "lists": true,
//     "listSeconds": 0, "listBytes": 0 }
//
// - refuse: lines holding the text come back as a refusal note until the
//   app sends its clarification; decline: they always do.
// - fail: requests holding the text get HTTP 400, or failStatus, such as 500,
//   with an error saying the stand-in fails them, or the error object
//   failError, such as {} for one without a message.
// - failFirst: each request's first attempt keeps its Japanese, so the app's
//   validation retries it.
// - target: "Japanese" answers an English game's lines in Japanese, and
//   "Chinese" a Japanese game's in Chinese.
// - long: lines holding the text come back as a long English message, the
//   same sentences for every line, so a game can page one at narrow widths.
// - reply: lines holding a key come back as its reply on every attempt, such
//   as a kaomoji a model keeps or a line it leaves in Japanese.
// - stall: chat requests get no answer until stall is turned off; with
//   answer: N, the first N requests are still answered.
// - delay: each chat answer waits that many milliseconds, as a slower model
//   does, so a Live run's progress shows while it runs.
// - hold: a Batch stays in progress until hold is turned off; otherwise it
//   completes batchSeconds after it was created.
// - effort: "refuse" answers a request carrying `reasoning_effort` with
//   HTTP 400 naming the field, "unsupported" with HTTP 422 saying the model
//   takes no reasoning, and "accept" reports the reasoning tokens it spent;
//   otherwise the field is ignored, as many servers do. Settings' effort
//   check, which asks "Reply with OK.", is answered "OK".
// - lists: false answers every GET to the Anthropic and OpenRouter presets,
//   their model lists and OpenRouter's Batch endpoints, with HTTP 503, as
//   in an outage, so their connection checks fail and a model's Batch
//   can't be read.
// - listSeconds: every model list arrives over that many seconds, its
//   headers after a third and each half of its body a third later, as on
//   a slow route; listBytes: every model list is padded with spaces to
//   that many bytes.
//
// A request naming a PLaMo 3 Translate model, such as plamo-3-translate-8b,
// is answered as LM Studio answers one with that model's chat template: HTTP
// 400 for what the template refuses (tools, an unknown setting in its
// [plamo-translate] block, messages that don't alternate user and assistant
// ending with a user message, blank text or its <|plamo: tokens), and also
// for a response_format, which LM Studio would take but DazedTL must not
// send it; otherwise the last user message's translation into the block's
// target_lang, as plain text. The `reply` and `delay` modes apply to it.
// Its model list stands in for the LM Studio preset's under /lmstudio.
//
// Every request is recorded in <folder>/requests.jsonl as its time, method,
// route, status, its User-Agent and OpenCode session header, and for a JSON
// body that body, so a check can confirm a field such as `reasoning_effort`
// reached the server (`recordedRequests` reads it); no other header, and
// with them no credential, is ever recorded.
// Uploaded files and Batches are kept in <folder>/batches. It also stands in
// for ntfy.sh at /ntfy.sh/ and keeps each phone notification, whose body the
// record leaves out, in <folder>/phone.jsonl.
//
// Its model lists stand in for the Anthropic and OpenRouter presets' too,
// under /api.anthropic.com and /openrouter.ai/api, with the effort data
// each provider's own list carries (`claudeModels`, `routedModels`), and
// GLM 6 runs OpenRouter's Batch at half its Live price on one endpoint.
// Under /opencode.ai/ it answers as OpenCode's gateway does:
// /opencode.ai/inference/go/v1/models lists Go's model rows (`goModels`)
// and /opencode.ai/inference/v1/models pay-as-you-go's (`paidModels`), with
// or without a session, any other model list is not found, and any other
// Go request without an `x-opencode-session` header gets OpenCode's HTTP
// 400; pay-as-you-go takes requests without one.
//
//   node scripts/testkit/provider.mjs --folder <dir> [--port <n>]
//
// runs one on its own and prints its address. The address may carry a
// prefix such as /api.openai.com/v1; the stand-in reads only what follows
// /v1/.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";

export const model = "stand-in";
/** The one short request Settings sends to check a thinking effort. */
const checkPrompt = "Reply with OK.";

/**
 * Anthropic's GET /v1/models rows: Opus 5.5 never turns thinking off,
 * Sonnet 5.5 turns it off with `between_tools`, and Opus 4.5, which
 * DazedTL's own notes don't hold, takes three levels without adaptive
 * thinking.
 */
const efforts = ["low", "medium", "high", "xhigh", "max"];
const claude = (id, levels, types) => ({
  type: "model",
  id,
  display_name: id,
  capabilities: {
    effort: {
      supported: true,
      ...Object.fromEntries(
        efforts.map((level) => [level, { supported: levels.includes(level) }]),
      ),
    },
    thinking: {
      supported: true,
      types: Object.fromEntries(
        ["adaptive", "disabled", "between_tools", "enabled"].map((kind) => [
          kind,
          { supported: types.includes(kind) },
        ]),
      ),
    },
  },
});
export const claudeModels = [
  claude("claude-opus-5-5", efforts, ["adaptive"]),
  claude("claude-sonnet-5-5", efforts, ["adaptive", "between_tools"]),
  claude("claude-opus-4-5", ["low", "medium", "high"], ["enabled", "disabled"]),
];

/**
 * OpenRouter's GET /models/user rows: Opus 5.5 lists four levels and a
 * default, and GLM 6, which DazedTL's notes don't hold, three and reasoning
 * off unless asked.
 */
const routed = (id, reasoning) => ({
  id,
  pricing: { prompt: "0.000001", completion: "0.000004" },
  architecture: { input_modalities: ["text"], output_modalities: ["text"] },
  context_length: 200000,
  top_provider: { max_completion_tokens: 32768 },
  supported_parameters: ["response_format", "structured_outputs", "reasoning"],
  reasoning,
});
const glm = {
  supported_efforts: ["high", "low", "none"],
  default_enabled: false,
};
export const routedModels = [
  routed("anthropic/claude-opus-5.5", {
    supported_efforts: ["max", "high", "medium", "low"],
    default_effort: "high",
    mandatory: true,
  }),
  routed("z-ai/glm-6", glm),
  // OpenRouter lists a model that runs Batch again, as `<id>:batch`.
  {
    ...routed("z-ai/glm-6:batch", glm),
    pricing: { prompt: "0.0000005", completion: "0.000002" },
  },
];
/** OpenRouter's GET /models/<id>:batch/endpoints rows for GLM 6's Batch. */
const batchEndpoints = [
  {
    tag: "deepinfra",
    pricing: { prompt: "0.0000005", completion: "0.000002" },
    max_completion_tokens: 32768,
    supported_parameters: ["response_format", "structured_outputs"],
  },
];
/**
 * OpenCode Go's GET /inference/go/v1/models rows, as its real list writes
 * them: DeepSeek V4.1 Flash costs twice its listed price in DeepSeek's peak
 * hours, Gemini 4 Argon twice from a date on, and GLM 5.3 Flash lists its
 * efforts without a multiplier.
 */
const goModel = (
  id,
  [input, cache, output],
  effort,
  more = {},
  base = "https://opencode.ai/inference/go/openai/v1",
) => ({
  id,
  object: "model",
  owned_by: "opencode",
  name: id,
  capabilities: {
    reasoning: { supported: true, effort },
    structured_output: true,
    temperature: true,
  },
  limit: { context: 1000000, output: more.output || 131072 },
  cost: {
    text: {
      input: { price: input, cache: { read: cache } },
      output: { price: output },
    },
    ...(more.multipliers && { multipliers: more.multipliers }),
  },
  api: {
    "chat-completions": { base_url: base },
  },
});
const hours = (gte, lt) => ({
  all: [{ utc_hours: { gte } }, { utc_hours: { lt } }],
});
export const goModels = [
  goModel("deepseek-v4.1-flash", [0.15, 0.003, 0.6], ["low", "high", "max"], {
    output: 384000,
    multipliers: [
      {
        when: {
          utc_days: { in: ["mon", "tue", "wed", "thu", "fri"] },
          any: [hours("01:00", "04:00"), hours("06:00", "10:00")],
        },
        factor: 2,
      },
    ],
  }),
  goModel("glm-5.3-flash", [0.15, 0.03, 0.5], ["low", "high", "max"]),
  goModel("gemini-4-argon", [2, 0.1, 10], ["low", "medium", "high"], {
    multipliers: [{ when: { date: { gte: "2026-12-01" } }, factor: 2 }],
  }),
];
/**
 * OpenCode pay-as-you-go's GET /inference/v1/models rows: the same models at
 * flat prices, and a free one, which serves only OpenCode's own app.
 */
export const paidModels = [
  ["deepseek-v4.1-flash", [0.3, 0.006, 1.2], ["low", "high", "max"]],
  ["glm-5.3-flash", [0.15, 0.03, 0.5], ["low", "high", "max"]],
  ["deepseek-v4.1-flash-free", [0, 0, 0], ["low", "high", "max"]],
].map(([id, prices, effort]) =>
  goModel(id, prices, effort, {}, "https://opencode.ai/inference/openai/v1"),
);
/** OpenCode Go's answer to a request without a session. */
const missingSession = {
  type: "error",
  error: {
    type: "MissingSessionID",
    message:
      "Request is missing x-opencode-session and cannot be routed efficiently. Please see https://opencode.ai/v2/docs/console/go/#where-can-i-use-it",
  },
};
/** What the app sends when it asks again after a refusal. */
const clarification = "Context clarification from the project owner";

/** The balanced JSON objects in `text`, outermost first. */
function* objects(text) {
  for (
    let start = text.indexOf("{");
    start >= 0;
    start = text.indexOf("{", start + 1)
  ) {
    let depth = 0;
    let quoted = false;
    for (let i = start; i < text.length; i++) {
      const character = text[i];
      if (quoted) {
        if (character === "\\") i++;
        else if (character === '"') quoted = false;
      } else if (character === '"') quoted = true;
      else if (character === "{") depth++;
      else if (character === "}" && --depth === 0) {
        try {
          yield JSON.parse(text.slice(start, i + 1));
        } catch {
          // Not JSON; keep scanning.
        }
        break;
      }
    }
  }
}

export const japanese = /[　-〿぀-ヿ㐀-鿿＀-￯]/g;

/** Codes and placeholders an English line keeps in its translation. */
const codes = /(__PROTECTED_\d+__|\\+[A-Za-z]+(?:\[[^\]]*\])?|%\d)/;

/**
 * Answers like a model that translates every line: the source's words become
 * a marker unique to the line, while speaker prefixes, placeholders and
 * numbers stay. An English line, for a Japanese `target`, gets a Japanese
 * marker in place of its Latin words. The marker is a hash read as katakana,
 * so these replies are not sensible Japanese: they only have to be unique per
 * line and read as Japanese. A Japanese line, for a Chinese `target`, gets a
 * marker of hanzi, which read as Japanese left unless read as Chinese. A game
 * variant's `reply` supplies readable ones.
 */
export function translate(value, target) {
  const text = String(value);
  const speaker = /^(\[[^\n]*?\]:\s*)([\s\S]*)$/.exec(text);
  const [prefix, body] = speaker ? [speaker[1], speaker[2]] : ["", text];
  const hash = crypto.createHash("sha256").update(text).digest("hex");
  if (target === "Chinese") {
    const kept = body.replace(japanese, " ").replace(/\s+/g, " ").trim();
    const marker = hash
      .slice(0, 8)
      .replace(
        /./g,
        (digit) => "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳"[parseInt(digit, 16)],
      );
    return `${prefix}测试${marker}${kept ? ` ${kept}` : ""}`;
  }
  if (target === "Japanese") {
    const kept = body
      .split(codes)
      .map((part, index) =>
        index % 2 ? part : part.replace(/[A-Za-z]+/g, " "),
      )
      .join("")
      .replace(/\s+/g, " ")
      .trim();
    const marker = hash
      .slice(0, 8)
      .replace(
        /./g,
        (digit) => "アイウエオカキクケコサシスセソタ"[parseInt(digit, 16)],
      );
    return `${prefix}テスト${marker}${kept ? ` ${kept}` : ""}`;
  }
  const kept = body.replace(japanese, " ").replace(/\s+/g, " ").trim();
  const marker = hash
    .slice(0, 8)
    .replace(/\d/g, (digit) => "ghijklmnop"[Number(digit)]);
  return `${prefix}Tested ${marker}${kept ? ` ${kept}` : ""}`;
}

/** What the `long` mode adds to a translation: fixed, so runs repeat. */
export const longText =
  "The road through the forest is long and the nights are cold, so pack warm clothes and bring plenty of food. Keep to the trail, never wander off alone, and send word to the village as soon as you reach the old shrine.";

/** Whether a game value is one the stand-in translated. */
export const translated = (value) =>
  typeof value === "string" &&
  (value.startsWith("Tested ") ||
    value.startsWith("テスト") ||
    value.startsWith("测试"));

/** Whether a model ID names PLaMo 3 Translate, as DazedTL decides it. */
const plamo = (id) => /(^|\/)plamo-3-translate([-_.@:]|$)/i.test(String(id));

/**
 * What PLaMo 3 Translate's chat template refuses in `params`, as LM Studio
 * renders it, or null; and the target language its settings block names.
 */
function plamoRequest(params) {
  if (params.tools)
    return { error: "Tool calls and documents are not supported." };
  if (params.response_format)
    return { error: "PLaMo 3 Translate takes no response_format." };
  const messages = params.messages || [];
  const text = (message) =>
    typeof message.content === "string" ? message.content : null;
  let target = "en";
  let first = 0;
  if (messages[0]?.role === "system") {
    const lines = String(text(messages[0]) ?? "").split("\n");
    first = 1;
    if (lines[0].trim().toLowerCase().startsWith("[plamo-translate")) {
      if (lines[0].trim() !== "[plamo-translate]")
        return { error: "Put the settings below [plamo-translate]." };
      for (const line of lines.slice(1)) {
        if (line.trim() === "---") break;
        if (!line.trim()) continue;
        const [key, ...rest] = line.split("=");
        const value = rest.join("=").trim();
        if (key.trim() === "glossary") {
          if (value.split("=>").length !== 2)
            return {
              error: `Each glossary line must be glossary=source => target: ${line}`,
            };
        } else if (
          !["target_lang", "source_lang", "form"].includes(key.trim()) ||
          !value
        )
          return {
            error: `Each line of the [plamo-translate] block must be key=value: ${line}`,
          };
        if (key.trim() === "target_lang") target = value.toLowerCase();
      }
    }
  }
  const rest = messages.slice(first);
  if (!rest.length || rest.length % 2 !== 1)
    return {
      error: "Provide source/translation pairs followed by one user message.",
    };
  for (const [index, message] of rest.entries()) {
    if (message.role !== (index % 2 ? "assistant" : "user"))
      return {
        error:
          "Alternate user source text and assistant translation; end with user.",
      };
    const content = text(message);
    if (content === null || !content.trim())
      return { error: "message content must not be empty." };
    if (content.includes("<|plamo:"))
      return {
        error:
          "message content must not contain reserved PFML tokens (<|plamo:...).",
      };
  }
  return { target, source: text(rest.at(-1)) };
}

/** The request's text, all messages joined. */
function requestText(params) {
  return (params.messages || [])
    .map((message) =>
      Array.isArray(message.content)
        ? message.content.map((part) => part.text || "").join("\n")
        : String(message.content ?? ""),
    )
    .join("\n");
}

/** The LineN object the last message carries, which the reply translates. */
function sourceLines(params) {
  const last = params.messages?.at(-1)?.content;
  const text = Array.isArray(last)
    ? last.map((part) => part.text || "").join("\n")
    : String(last ?? "");
  // A clarification repeats the request, so look through every message.
  for (const candidate of [text, requestText(params)]) {
    const found = [...objects(candidate)].find(
      (value) =>
        value &&
        typeof value === "object" &&
        Object.keys(value).length &&
        Object.keys(value).every((key) => /^Line\d+$/.test(key)),
    );
    if (found) return found;
  }
  return null;
}

/**
 * The lines an Assistant-led API request carries under numbered keys, which
 * its output schema asks for again, or null for a Guided request. JSON mode,
 * which DeepSeek's models get, names no keys: there the lines are the last
 * object of numbered lines the request carries.
 */
function keyedLines(params) {
  const keys = Object.keys(
    params.response_format?.json_schema?.schema?.properties || {},
  );
  const jsonMode = params.response_format?.type === "json_object";
  if (!jsonMode && (!keys.length || !keys.every((key) => /^\d+$/.test(key))))
    return null;
  // The lines to translate come last, after any earlier lines as context.
  return (
    [...objects(requestText(params))]
      .reverse()
      .find(
        (value) =>
          value &&
          typeof value === "object" &&
          !Array.isArray(value) &&
          (jsonMode
            ? Object.keys(value).length > 0 &&
              Object.entries(value).every(
                ([key, line]) => /^\d+$/.test(key) && typeof line === "string",
              )
            : Object.keys(value).length === keys.length &&
              keys.every((key) => typeof value[key] === "string")),
      ) || null
  );
}

/**
 * Every request the stand-in in `folder` recorded so far, leaving out a last
 * line it is still writing.
 * @param {string} folder
 */
export function recordedRequests(folder) {
  const lines = fs
    .readFileSync(path.join(folder, "requests.jsonl"), "utf8")
    .split("\n");
  return lines.slice(0, -1).map((line) => JSON.parse(line));
}

/**
 * Starts the stand-in. `folder` holds its mode file and records.
 * @param {{ folder: string, port?: number }} options
 */
export async function startProvider({ folder, port = 0 }) {
  fs.mkdirSync(path.join(folder, "batches"), { recursive: true });
  const record = fs.createWriteStream(path.join(folder, "requests.jsonl"), {
    flags: "a",
  });
  const modeFile = path.join(folder, "mode.json");
  const mode = () => {
    try {
      return JSON.parse(fs.readFileSync(modeFile, "utf8"));
    } catch {
      return {};
    }
  };
  /** How often each request was asked, for failFirst. */
  const attempts = new Map();
  let answered = 0;
  const held = new Set();
  // Uploaded files and Batches stay on disk, so a held Batch outlives a
  // restart of the stand-in, as one at a real provider outlives the app.
  const store = path.join(folder, "batches");
  const files = new Map();
  const batches = new Map();
  for (const name of fs.readdirSync(store)) {
    if (name.endsWith(".jsonl"))
      files.set(name.slice(0, -6), fs.readFileSync(path.join(store, name)));
    if (name.endsWith(".batch.json")) {
      const batch = JSON.parse(fs.readFileSync(path.join(store, name), "utf8"));
      batches.set(batch.id, batch);
    }
  }
  const keep = (batch) =>
    fs.writeFileSync(
      path.join(store, `${batch.id}.batch.json`),
      JSON.stringify(batch),
    );
  const upload = (id, content) => {
    files.set(id, content);
    fs.writeFileSync(path.join(store, `${id}.jsonl`), content);
  };

  /** A chat completion carrying `content`, as `params` asked for it. */
  function completion(params, content, usage = {}) {
    const body = JSON.stringify(params);
    return {
      status: 200,
      value: {
        id: `chatcmpl-${crypto.randomUUID()}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: params.model || model,
        choices: [
          {
            index: 0,
            message: { role: "assistant", content },
            finish_reason: "stop",
          },
        ],
        usage: {
          prompt_tokens: body.length,
          completion_tokens: content.length,
          total_tokens: body.length + content.length,
          ...usage,
        },
      },
    };
  }

  /** A chat completion for `params`, or an HTTP error. */
  function complete(params) {
    const settings = mode();
    if (plamo(params.model)) {
      const found = plamoRequest(params);
      if (found.error)
        return {
          status: 400,
          value: {
            error: {
              message: `Error rendering prompt with jinja template: ${found.error}`,
            },
          },
        };
      const reply = Object.entries(settings.reply || {}).find(([item]) =>
        found.source.includes(item),
      );
      const target = found.target.startsWith("ja")
        ? "Japanese"
        : found.target.startsWith("zh")
          ? "Chinese"
          : undefined;
      return completion(
        params,
        reply ? reply[1] : translate(found.source, target),
      );
    }
    // A server that refuses the effort field, or takes it and reports the
    // reasoning tokens it spent; by default it ignores it.
    const level = params.reasoning_effort;
    if (level !== undefined && settings.effort === "refuse")
      return {
        status: 400,
        value: {
          error: {
            message: "Unrecognized request argument supplied: reasoning_effort",
          },
        },
      };
    if (level !== undefined && settings.effort === "unsupported")
      return {
        status: 422,
        value: {
          error: { message: "Reasoning is not supported for this model." },
        },
      };
    const usage =
      level !== undefined && settings.effort === "accept"
        ? {
            completion_tokens_details: {
              reasoning_tokens: level === "none" ? 0 : 12,
            },
          }
        : {};
    if (requestText(params) === checkPrompt)
      return completion(params, "OK", usage);
    const keyed = keyedLines(params);
    const lines = keyed || sourceLines(params);
    if (!lines)
      return {
        status: 400,
        value: { error: { message: "The request carried no LineN payload." } },
      };
    const text = requestText(params);
    if ((settings.fail || []).some((item) => text.includes(item)))
      return {
        status: settings.failStatus || 400,
        value: {
          error: settings.failError ?? {
            message: "The stand-in fails this request.",
          },
        },
      };
    const clarified = text.includes(clarification);
    const key = crypto
      .createHash("sha256")
      .update(JSON.stringify(lines))
      .digest("hex");
    const attempt = (attempts.get(key) || 0) + 1;
    attempts.set(key, attempt);
    const translations = Object.values(lines).map((line) => {
      const source = String(line);
      const reply = Object.entries(settings.reply || {}).find(([item]) =>
        source.includes(item),
      );
      if (reply) return reply[1];
      if ((settings.decline || []).some((item) => source.includes(item)))
        return "Translation declined.";
      if (
        !clarified &&
        (settings.refuse || []).some((item) => source.includes(item))
      )
        return "[Not translated: explicit content]";
      if (settings.failFirst && attempt === 1) return source;
      const english = translate(source, settings.target);
      return (settings.long || []).some((item) => source.includes(item))
        ? `${english} ${longText}`
        : english;
    });
    const content = JSON.stringify(
      keyed
        ? Object.fromEntries(
            Object.keys(keyed).map((key, index) => [key, translations[index]]),
          )
        : { translations },
    );
    return completion(params, content, usage);
  }

  /** A Batch as OpenAI shows it, finishing it once its time is up. */
  function batchView(batch) {
    const settings = mode();
    const due =
      Date.now() - batch.created >= (settings.batchSeconds || 0) * 1000;
    if (batch.status === "in_progress" && !settings.hold && due) {
      const rows = files
        .get(batch.input)
        .toString("utf8")
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          const row = JSON.parse(line);
          const answer = complete(row.body);
          return {
            id: `response-${row.custom_id}`,
            custom_id: row.custom_id,
            response:
              answer.status === 200
                ? {
                    status_code: 200,
                    request_id: row.custom_id,
                    body: answer.value,
                  }
                : null,
            error:
              answer.status === 200
                ? null
                : {
                    code: "invalid_request",
                    message: answer.value.error.message,
                  },
          };
        });
      const output = `file-output-${batch.id}`;
      upload(
        output,
        Buffer.from(rows.map((row) => JSON.stringify(row) + "\n").join("")),
      );
      Object.assign(batch, {
        status: "completed",
        output,
        total: rows.length,
        failed: rows.filter((row) => row.error).length,
      });
      keep(batch);
    }
    if (batch.status === "cancelling" && Date.now() - batch.cancelled > 1000) {
      batch.status = "cancelled";
      keep(batch);
    }
    return {
      id: batch.id,
      object: "batch",
      endpoint: "/v1/chat/completions",
      errors: null,
      input_file_id: batch.input,
      completion_window: "24h",
      status: batch.status,
      output_file_id: batch.output || null,
      error_file_id: null,
      created_at: Math.floor(batch.created / 1000),
      request_counts: {
        total: batch.total || 0,
        completed: (batch.total || 0) - (batch.failed || 0),
        failed: batch.failed || 0,
      },
    };
  }

  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      const body = Buffer.concat(chunks);
      const url = (request.url || "").split("?")[0];
      const at = url.indexOf("/v1/");
      const route = at >= 0 ? url.slice(at + 3) : url;
      // A file upload is multipart and stays out of the record, and a phone
      // notification's topic stays in phone.jsonl alone.
      let sent;
      try {
        if (body.length && route !== "/ntfy.sh/")
          sent = JSON.parse(body.toString("utf8"));
      } catch {
        sent = undefined;
      }
      const session = request.headers["x-opencode-session"];
      const reply = (status, value, raw) => {
        record.write(
          JSON.stringify({
            time: new Date().toISOString(),
            method: request.method,
            route,
            status,
            userAgent: request.headers["user-agent"],
            ...(session !== undefined && { session }),
            body: sent,
          }) + "\n",
        );
        const settings = mode();
        const list = request.method === "GET" && /\/models(\/user)?$/.test(url);
        let content = raw || Buffer.from(JSON.stringify(value));
        if (list && settings.listBytes > content.length)
          content = Buffer.concat([
            content,
            Buffer.alloc(settings.listBytes - content.length, " "),
          ]);
        const head = () =>
          response.writeHead(status, {
            "Content-Type": raw
              ? "application/octet-stream"
              : "application/json",
            "Content-Length": content.length,
          });
        if (!list || !settings.listSeconds) {
          head();
          return response.end(content);
        }
        const step = (settings.listSeconds * 1000) / 3;
        const half = Math.floor(content.length / 2);
        setTimeout(head, step);
        setTimeout(() => response.write(content.subarray(0, half)), step * 2);
        setTimeout(() => response.end(content.subarray(half)), step * 3);
      };
      try {
        if (request.method === "POST" && route === "/ntfy.sh/") {
          const { topic, title, message } = JSON.parse(body.toString("utf8"));
          fs.appendFileSync(
            path.join(folder, "phone.jsonl"),
            JSON.stringify({ topic, title, message }) + "\n",
          );
          return reply(200, { id: crypto.randomUUID(), event: "message" });
        }
        // OpenCode lists each route's models only beside its
        // OpenAI-compatible API, and without a session, which only Go's
        // other requests need.
        if (url.includes("/opencode.ai/")) {
          if (
            request.method === "GET" &&
            url.endsWith("/opencode.ai/inference/go/v1/models")
          )
            return reply(200, { object: "list", data: goModels });
          if (
            request.method === "GET" &&
            url.endsWith("/opencode.ai/inference/v1/models")
          )
            return reply(200, { object: "list", data: paidModels });
          if (route === "/models")
            return reply(404, { error: { message: "Not in the stand-in." } });
          if (!session && url.includes("/opencode.ai/inference/go/"))
            return reply(400, missingSession);
        }
        if (
          request.method === "GET" &&
          /\/(api\.anthropic\.com|openrouter\.ai\/api)\//.test(url) &&
          mode().lists === false
        )
          return reply(503, { error: { message: "The stand-in is down." } });
        if (request.method === "GET" && url.includes("/api.anthropic.com/"))
          return reply(200, {
            data: claudeModels,
            has_more: false,
            first_id: claudeModels[0].id,
            last_id: claudeModels.at(-1).id,
          });
        if (request.method === "GET" && url.includes("/openrouter.ai/api/"))
          return route === "/models/user"
            ? reply(200, { data: routedModels })
            : route === "/models/z-ai/glm-6:batch/endpoints"
              ? reply(200, {
                  data: { id: "z-ai/glm-6:batch", endpoints: batchEndpoints },
                })
              : reply(404, { error: { message: "Not in the stand-in." } });
        if (request.method === "GET" && url.includes("/lmstudio/"))
          return route === "/models"
            ? reply(200, {
                object: "list",
                data: [
                  { id: "plamo-3-translate-8b", object: "model" },
                  {
                    id: "text-embedding-nomic-embed-text-v1.5",
                    object: "model",
                  },
                ],
              })
            : reply(404, { error: { message: "Not in the stand-in." } });
        if (request.method === "GET" && route === "/models")
          return reply(200, {
            object: "list",
            data: [{ id: model, object: "model" }],
          });
        if (request.method === "POST" && route === "/chat/completions") {
          const params = JSON.parse(body.toString("utf8"));
          const settings = mode();
          if (
            settings.stall &&
            !(settings.answer != null && answered < settings.answer)
          ) {
            // Answered once stall is turned off, as a slow provider would.
            const wait = setInterval(() => {
              if (response.destroyed) {
                clearInterval(wait);
                held.delete(wait);
              } else if (!mode().stall) {
                clearInterval(wait);
                held.delete(wait);
                const answer = complete(params);
                reply(answer.status, answer.value);
              }
            }, 250);
            held.add(wait);
            return;
          }
          answered++;
          const answer = complete(params);
          if (!settings.delay) return reply(answer.status, answer.value);
          const wait = setTimeout(() => {
            held.delete(wait);
            reply(answer.status, answer.value);
          }, settings.delay);
          held.add(wait);
          return;
        }
        if (request.method === "POST" && route === "/files") {
          const boundary = /boundary=(.+)$/.exec(
            request.headers["content-type"] || "",
          )?.[1];
          const text = body.toString("latin1");
          const part = boundary?.replace(/^"|"$/g, "").split(/\r?\n/)[0];
          const section = text
            .split(`--${part}`)
            .find((item) => /name="file"/.test(item));
          if (!section) return reply(400, { error: { message: "No file." } });
          const content = Buffer.from(
            section.slice(section.indexOf("\r\n\r\n") + 4).replace(/\r\n$/, ""),
            "latin1",
          );
          const id = `file-${crypto.randomUUID().replaceAll("-", "")}`;
          upload(id, content);
          return reply(200, {
            id,
            object: "file",
            bytes: content.length,
            created_at: Math.floor(Date.now() / 1000),
            filename: "batch.jsonl",
            purpose: "batch",
            status: "processed",
          });
        }
        if (request.method === "POST" && route === "/batches") {
          const params = JSON.parse(body.toString("utf8"));
          if (!files.has(params.input_file_id))
            return reply(404, { error: { message: "No such file." } });
          const id = `batch_${crypto.randomUUID().replaceAll("-", "")}`;
          const batch = {
            id,
            input: params.input_file_id,
            created: Date.now(),
            status: "in_progress",
          };
          batches.set(id, batch);
          keep(batch);
          return reply(200, batchView(batch));
        }
        const batchRoute = /^\/batches\/([^/]+)(\/cancel)?$/.exec(route);
        if (batchRoute && batches.has(batchRoute[1])) {
          const batch = batches.get(batchRoute[1]);
          if (request.method === "GET") return reply(200, batchView(batch));
          if (request.method === "POST" && batchRoute[2]) {
            if (batchView(batch).status !== "in_progress")
              return reply(409, {
                error: {
                  message: `Cannot cancel a batch with status '${batch.status}'.`,
                  type: "invalid_request_error",
                },
              });
            Object.assign(batch, {
              status: "cancelling",
              cancelled: Date.now(),
            });
            keep(batch);
            return reply(200, batchView(batch));
          }
        }
        const content = /^\/files\/([^/]+)\/content$/.exec(route);
        if (request.method === "GET" && content && files.has(content[1]))
          return reply(200, null, files.get(content[1]));
        return reply(404, { error: { message: "Not found" } });
      } catch (error) {
        return reply(500, {
          error: {
            message: error instanceof Error ? error.message : String(error),
          },
        });
      }
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(undefined));
  });
  const { port: bound } = /** @type {import("node:net").AddressInfo} */ (
    server.address()
  );
  return {
    port: bound,
    url: `http://127.0.0.1:${bound}/v1`,
    /** Every request so far, from the record. */
    requests: () => recordedRequests(folder),
    close: () =>
      new Promise((resolve) => {
        for (const wait of held) clearInterval(wait);
        server.closeAllConnections();
        server.close(() => record.end(resolve));
      }),
  };
}

if (import.meta.main) {
  const option = (name) => {
    const index = process.argv.indexOf(name);
    return index >= 0 ? process.argv[index + 1] : undefined;
  };
  const folder = path.resolve(option("--folder") || "provider");
  const provider = await startProvider({
    folder,
    port: Number(option("--port") || 0),
  });
  console.log(provider.url);
}
