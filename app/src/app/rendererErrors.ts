import type { RendererFailure } from "../api/errors";

/** Only fixed error types and bundled code locations cross the diagnostics bridge. */
export function rendererFailure(error: unknown, reason: RendererFailure["reason"]): RendererFailure {
  const value = error instanceof Error ? error : null;
  const type = value && ["Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "EvalError"].includes(value.name) ? value.name : "Error";
  const header = value ? `${value.name}: ${value.message}` : "";
  const stack = header && value?.stack?.startsWith(header) ? value.stack.slice(header.length) : "";
  const frames: RendererFailure["causes"][number]["frames"] = [];
  for (const line of stack.split("\n").slice(0, 30)) {
    const match = /\bat .*\/(assets\/[\w.-]+\.js|src\/[\w./-]+\.[tj]sx?):(\d+):(\d+)\)?$/.exec(line);
    if (match && !match[1].split("/").includes("..")) frames.push({
      file: "app/renderer/" + match[1], line: Number(match[2]), column: Number(match[3]), function: "unknown",
    });
  }
  return { reason, causes: [{ type, frames: frames.slice(0, 8) }] };
}

let reported = 0;
const seen = new WeakSet<object>();
export function reportRendererFailure(error: unknown, reason: RendererFailure["reason"] = "render") {
  if (reported >= 20 || error && typeof error === "object" && seen.has(error)) return;
  if (error && typeof error === "object") seen.add(error);
  reported++;
  try { void window.dazedtl.reportRendererError(rendererFailure(error, reason)).catch(() => {}); }
  catch { /* Recovery must work even if the desktop bridge failed. */ }
}
