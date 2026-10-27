// A local stand-in for an OpenAI-compatible provider, free and offline, for
// the live test and test scenarios. It answers chat completions and OpenAI's
// Batch file API like a model that translates every line, and its behavior
// can change while it runs through <folder>/mode.json:
//
//   { "refuse": ["text"], "decline": ["text"], "fail": ["text"],
//     "failFirst": false, "stall": false, "answer": null, "hold": false,
//     "batchSeconds": 0, "long": ["text"], "reply": { "text": "reply" },
//     "target": null }
//
// - refuse: lines holding the text come back as a refusal note until the
//   app sends its clarification; decline: they always do.
// - fail: requests holding the text get HTTP 400.
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
// - hold: a Batch stays in progress until hold is turned off; otherwise it
//   completes batchSeconds after it was created.
//
// Every request is recorded in <folder>/requests.jsonl; uploaded files and
// Batches are kept in <folder>/batches. It also stands in for ntfy.sh at
// /ntfy.sh/ and keeps each phone notification in <folder>/phone.jsonl.
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

  /** A chat completion for `params`, or an HTTP error. */
  function complete(params) {
    const lines = sourceLines(params);
    if (!lines)
      return {
        status: 400,
        value: { error: { message: "The request carried no LineN payload." } },
      };
    const settings = mode();
    const text = requestText(params);
    if ((settings.fail || []).some((item) => text.includes(item)))
      return {
        status: 400,
        value: { error: { message: "The stand-in fails this request." } },
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
    const content = JSON.stringify({ translations });
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
        },
      },
    };
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
      const reply = (status, value, raw) => {
        record.write(
          JSON.stringify({
            time: new Date().toISOString(),
            method: request.method,
            route,
            status,
          }) + "\n",
        );
        response.writeHead(status, {
          "Content-Type": raw ? "application/octet-stream" : "application/json",
        });
        response.end(raw || JSON.stringify(value));
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
          return reply(answer.status, answer.value);
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
    requests: () =>
      fs
        .readFileSync(path.join(folder, "requests.jsonl"), "utf8")
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line)),
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
