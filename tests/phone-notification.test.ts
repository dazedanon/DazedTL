import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const { sendToPhone } = createRequire(import.meta.url)(
  "../app/electron/phone.cjs",
);

test("a phone notification keeps a Japanese title and reports what ntfy refuses", async () => {
  const posts: { url: string; body: unknown }[] = [];
  let status = 200;
  const send = async (url: string, init: { body: string }) => {
    posts.push({ url, body: JSON.parse(init.body) });
    return new Response(null, { status });
  };
  const message = {
    topic: "dazedtl-k3m9x2q7wp",
    title: "異世界にゆっくり染まる君",
    body: "Translate · Finished",
  };
  await sendToPhone(message, send);
  // Fetch refuses a header holding Japanese, so the title travels as JSON.
  assert.deepEqual(posts, [
    {
      url: "https://ntfy.sh/",
      body: {
        topic: message.topic,
        title: message.title,
        message: message.body,
      },
    },
  ]);
  // The topic is the whole address, so nothing else may stand in for it.
  for (const topic of ["", "../x", "a b", "x".repeat(65), undefined])
    await assert.rejects(sendToPhone({ ...message, topic }, send));
  assert.equal(posts.length, 1);
  status = 429;
  await assert.rejects(sendToPhone(message, send), /limiting/);
  await assert.rejects(
    sendToPhone(message, async () => {
      throw new TypeError("fetch failed");
    }),
    /internet connection/,
  );
});
