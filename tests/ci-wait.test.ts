import assert from "node:assert/strict";
import test from "node:test";
import { githubReader, waitForCI } from "../scripts/ci-wait.mjs";

const run = (
  id: number,
  status: string,
  conclusion: string | null,
  at: number,
) => ({
  id,
  status,
  conclusion,
  path: ".github/workflows/ci.yml",
  head_sha: `${id}`.padStart(40, "a"),
  head_branch: "work",
  html_url: `https://github.test/${id}`,
  created_at: new Date(at).toISOString(),
});

test("a 304 answer reuses the cached body and sends the ETag", async () => {
  const seen: Array<string | undefined> = [];
  const fetchImpl = async (
    _url: string,
    init: { headers: Record<string, string> },
  ) => {
    seen.push(init.headers["If-None-Match"]);
    const headers = new Headers({ "x-ratelimit-remaining": "4000" });
    if (!init.headers["If-None-Match"]) {
      headers.set("etag", '"v1"');
      return new Response('{"a":1}', { status: 200, headers });
    }
    return new Response(null, { status: 304, headers });
  };
  const read = githubReader({ token: "t", fetchImpl: fetchImpl as never });
  assert.deepEqual(await read("x"), { a: 1 });
  assert.deepEqual(await read("x"), { a: 1 });
  assert.deepEqual(seen, [undefined, '"v1"']);
});

test("a run cancelled by a later push hands over to the newer run", async () => {
  const old = run(1, "completed", "cancelled", 1000);
  const next = run(2, "completed", "success", 2000);
  const read = async (route: string) =>
    route.includes("head_sha")
      ? { workflow_runs: [old] }
      : route.includes("branch=work")
        ? { workflow_runs: [next, old] }
        : null;
  const result = await waitForCI({
    sha: "a".repeat(40),
    read,
    wait: async () => {},
  });
  assert.equal(result.ok, true);
  assert.equal(result.run.id, 2);
});

test("after a rerun, the earlier attempt's failure is not taken as the result", async () => {
  const answers = [
    { ...run(1, "completed", "failure", 1000), run_attempt: 1 },
    { ...run(1, "completed", "success", 1000), run_attempt: 2 },
  ];
  const read = async (route: string) =>
    route.includes("head_sha")
      ? { workflow_runs: [answers.shift()] }
      : answers.shift();
  const result = await waitForCI({
    sha: "a".repeat(40),
    read,
    attempt: 2,
    wait: async () => {},
  });
  assert.equal(result.ok, true);
});
