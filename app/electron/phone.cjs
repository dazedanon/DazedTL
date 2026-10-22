// Sends DazedTL's notifications to the user's phone through ntfy, whose free
// Android and iPhone apps show what is posted to a topic they subscribe to.
// Scenario apps post to the stand-in provider instead.
const server = process.env.DAZEDTL_TEST_NTFY_SERVER || "https://ntfy.sh/";
const offline =
  "Couldn't reach ntfy.sh to send to your phone. Check your internet connection.";

/**
 * Posts one notification. It goes as JSON to the server's root, since a
 * Title header cannot carry a game's Japanese name.
 *
 * @param {{ topic: unknown; title: unknown; body: unknown }} message
 * @param {typeof fetch} send
 */
async function sendToPhone({ topic, title, body }, send) {
  if (typeof topic !== "string" || !/^[-_A-Za-z0-9]{1,64}$/.test(topic))
    throw new Error(
      "This phone topic can't be used. Turn Send to your phone off and on for a new one.",
    );
  if (
    typeof title !== "string" ||
    typeof body !== "string" ||
    title.length > 200 ||
    body.length > 1000
  )
    throw new Error("Choose a short notification.");
  let response;
  try {
    response = await send(server, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, title, message: body }),
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new Error(offline);
  }
  if (response.status === 429)
    throw new Error(
      "ntfy.sh is limiting notifications from this connection. Try again later.",
    );
  if (!response.ok)
    throw new Error(`ntfy.sh refused the notification (${response.status}).`);
}

module.exports = { sendToPhone };
