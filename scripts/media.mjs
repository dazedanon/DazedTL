// Captures the README's screenshots and animation into docs/media from the
// showcase game variant: a test scenario's app driven as a user drives it,
// the stand-in answering with the variant's English. See "README media" in
// docs/development.md.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { root } from "./dependencies.mjs";
import { Page, until } from "./testkit/cdp.mjs";
import { electronOf } from "./testkit/app.mjs";
import { applyTask, connect } from "./testkit/journey.mjs";
import { readOptions } from "./testkit/options.mjs";

const usage = `Usage:
  node scripts/media.mjs [--work <empty folder>] [--keep]

Rebuilds docs/media from the showcase game. Needs ffmpeg with libwebp.
--keep leaves the scenario's app running in <work>/app.`;
const { option, flag } = readOptions(usage, {
  "--work": "value",
  "--keep": "flag",
});

const media = path.join(root, "docs/media");
// What GitHub shows for a link to the repository, uploaded by hand in its
// Settings > Social preview.
const socialPreview = path.join(root, "resources/social-preview.jpg");
// The banner's own background, which the cards share.
const background = "0x121b1c";
// The window the stills and animation show, in CSS pixels.
const viewport = { width: 1280, height: 800 };
// The model the showcase connection names. The stand-in answers for it, and
// DazedTL prices it as OpenAI does, so the estimate reads as a real one.
const showcaseModel = "gpt-6-luna";
// How long each stand-in answer takes while the animation records, so the
// run's progress shows.
const answerDelay = 200;
// How much faster the animation plays while the app works, such as while it
// prepares the estimate, than while the pointer moves and the viewer reads.
const waitSpeed = 3;

/** Runs a command to its end, failing with its output. */
function exec(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: "utf8", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0)
    throw new Error(
      `${command} ${args.join(" ")} failed:\n${(result.stderr || result.stdout || "").trim().split("\n").slice(-20).join("\n")}`,
    );
  return result;
}

/** Saves the showcase game's `shots` with render.cjs, on the scenario's
 * display. */
function playGame(state, shots) {
  const file = path.join(
    work,
    `render-${crypto.randomBytes(3).toString("hex")}.json`,
  );
  fs.writeFileSync(file, JSON.stringify({ game: state.game, shots }));
  exec(
    electronOf(root),
    [path.join(root, "scripts/testkit/render.cjs"), file],
    { env: { ...process.env, ...state.display?.env } },
  );
}

/** Lays the window out at the README's size, at `scale` device pixels. */
const emulate = (page, scale) =>
  page.send("Emulation.setDeviceMetricsOverride", {
    ...viewport,
    deviceScaleFactor: scale,
    mobile: false,
  });

/** Saves a still of the window. */
async function still(page, file) {
  // Hover and focus marks would show where the last click landed.
  await page.evaluate(
    "document.activeElement?.blur(); new Promise((resolve) => setTimeout(resolve, 400))",
  );
  await page.shot(file);
}

// A pointer drawn over the window, in the top layer above modal dialogs, so
// the animation shows what each click aims at.
const pointer = `(() => {
  let pointer = document.getElementById("media-pointer");
  if (!pointer) {
    pointer = document.createElement("div");
    pointer.id = "media-pointer";
    pointer.popover = "manual";
    pointer.innerHTML = \`
      <span class="ring"></span>
      <svg width="26" height="30" viewBox="0 0 26 30" aria-hidden="true">
        <path d="M2 2 L2 24 L8 18.5 L12.5 28 L16.5 26.2 L12 17 L20 17 Z"
          fill="#ffffff" stroke="#0b1a22" stroke-width="2" stroke-linejoin="round"/>
      </svg>\`;
    const style = document.createElement("style");
    style.textContent = \`
      #media-pointer { position: fixed; inset: auto; left: 0; top: 0; margin: 0;
        padding: 0; border: 0; background: none; overflow: visible; width: 26px;
        height: 30px; pointer-events: none;
        transition: transform 550ms cubic-bezier(0.3, 0.1, 0.2, 1); }
      #media-pointer svg { position: absolute; left: -2px; top: -2px;
        filter: drop-shadow(0 2px 3px rgb(0 0 0 / 0.45)); }
      #media-pointer .ring { position: absolute; left: -18px; top: -18px;
        width: 36px; height: 36px; border-radius: 50%;
        border: 3px solid #5ee0c4; opacity: 0; transform: scale(0.3); }
      #media-pointer.press .ring { animation: media-press 450ms ease-out; }
      @keyframes media-press { from { opacity: 0.9; transform: scale(0.3); }
        to { opacity: 0; transform: scale(1.2); } }\`;
    pointer.append(style);
    document.body.append(pointer);
    pointer.style.transform = "translate(640px, 520px)";
  }
  return pointer;
})()`;

/** Moves the drawn pointer to `at` above everything on screen. */
const pointTo = (page, at) =>
  page.evaluate(`(async () => {
    const pointer = ${pointer};
    // The newest top-layer element draws on top, such as a dialog opened
    // since the pointer last moved.
    if (pointer.matches(":popover-open")) pointer.hidePopover();
    pointer.showPopover();
    pointer.style.transform = "translate(${at.x}px, ${at.y}px)";
    await new Promise((resolve) => setTimeout(resolve, 650));
  })()`);

/** Moves the pointer to the control named `name` and clicks it. */
async function clickShown(page, name) {
  const at = await until(`an enabled "${name}" control`, () =>
    page.locate(name),
  );
  await pointTo(page, at);
  await page.evaluate(`(() => {
    const pointer = document.getElementById("media-pointer");
    pointer.classList.remove("press");
    void pointer.offsetWidth;
    pointer.classList.add("press");
  })()`);
  await page.click(name);
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Records the window while `act` runs, as the frames the window drew and
 * when; returns them with the time recording ended and the spans `act`
 * spent waiting on the app, through the `wait` it is given.
 */
async function record(page, folder, act) {
  fs.mkdirSync(folder, { recursive: true });
  const frames = [];
  const waits = [];
  const wait = async (until) => {
    const from = Date.now() / 1000;
    await until;
    waits.push({ from, to: Date.now() / 1000 });
  };
  const listener = (event) => {
    const message = JSON.parse(String(event.data));
    if (message.method !== "Page.screencastFrame") return;
    const { data, metadata, sessionId } = message.params;
    const file = path.join(
      folder,
      `${String(frames.length).padStart(5, "0")}.png`,
    );
    fs.writeFileSync(file, Buffer.from(data, "base64"));
    frames.push({ file, time: metadata.timestamp });
    void page.send("Page.screencastFrameAck", { sessionId });
  };
  page.socket.addEventListener("message", listener);
  await page.send("Page.startScreencast", { format: "png", everyNthFrame: 1 });
  try {
    await act(wait);
  } finally {
    await page.send("Page.stopScreencast");
    page.socket.removeEventListener("message", listener);
  }
  return { frames, waits, end: Date.now() / 1000 };
}

/** Encodes recorded frames as a looping animated WebP. */
function animate({ frames, waits, end }, out) {
  if (frames.length < 2) throw new Error("The recording caught no motion.");
  // A frame shows for as long as the window kept it, less the part of that
  // spent waiting on the app, which plays waitSpeed times faster.
  const shown = (from, to) =>
    waits.reduce(
      (time, span) =>
        time -
        Math.max(0, Math.min(to, span.to) - Math.max(from, span.from)) *
          (1 - 1 / waitSpeed),
      to - from,
    );
  const list = frames.flatMap((frame, index) => [
    `file '${frame.file}'`,
    `duration ${shown(frame.time, frames[index + 1]?.time ?? end).toFixed(3)}`,
  ]);
  // The concat demuxer takes the last frame's duration only when it repeats.
  list.push(`file '${frames.at(-1).file}'`);
  const file = path.join(work, "frames.txt");
  fs.writeFileSync(file, `${list.join("\n")}\n`);
  exec("ffmpeg", [
    "-y",
    "-loglevel",
    "error",
    "-f",
    "concat",
    "-safe",
    "0",
    "-i",
    file,
    "-vf",
    `fps=12,scale=${viewport.width}:-1:flags=lanczos`,
    "-c:v",
    "libwebp_anim",
    "-lossless",
    "0",
    "-quality",
    "82",
    "-compression_level",
    "6",
    "-loop",
    "0",
    out,
  ]);
}

/** Encodes a PNG as WebP, `width` pixels wide when given. */
function webp(png, out, width) {
  exec("ffmpeg", [
    "-y",
    "-loglevel",
    "error",
    "-i",
    png,
    ...(width ? ["-vf", `scale=${width}:-1:flags=lanczos`] : []),
    "-c:v",
    "libwebp",
    "-quality",
    "88",
    "-compression_level",
    "6",
    out,
  ]);
}

/** Lays the game's screens side by side, labeled, as one PNG. */
function gameCard(before, after, out) {
  const font = path.join(root, "app/src/assets/fonts/InterVariable.woff2");
  const text = (value, size, color, x, y, box = "") =>
    `drawtext=fontfile=${font}:text=${value}:fontsize=${size}:fontcolor=${color}:x=${x}:y=${y}${box}`;
  const label = (value) =>
    text(
      value,
      20,
      "0xe8f1f0",
      "w-tw-28",
      28,
      ":box=1:boxcolor=0x0b1a22@0.85:boxborderw=10",
    );
  exec("ffmpeg", [
    "-y",
    "-loglevel",
    "error",
    "-i",
    before,
    "-i",
    after,
    "-filter_complex",
    [
      `[0]${label("Japanese")}[before]`,
      `[1]${label("English")}[after]`,
      `[before]pad=w=iw+64:h=ih:color=${background},${text("→", 40, "0x5ee0c4", "w-64+(64-tw)/2", "(h-th)/2")}[left]`,
      `[left][after]hstack,pad=w=iw+40:h=ih+40:x=20:y=20:color=${background}`,
    ].join(";"),
    out,
  ]);
}

/** The link card: the banner over the game's before and after. */
function socialCard(card, out) {
  exec("ffmpeg", [
    "-y",
    "-loglevel",
    "error",
    "-i",
    path.join(root, "resources/forum-banner.gif"),
    "-i",
    card,
    "-filter_complex",
    [
      `color=c=${background}:s=1280x640[canvas]`,
      // The banner's first frame, inside its border.
      "[0]trim=end_frame=1,crop=iw-8:ih-8:4:4,scale=760:-1:flags=lanczos[banner]",
      "[1]scale=1120:-1:flags=lanczos[card]",
      "[canvas][banner]overlay=x=(W-w)/2:y=24[top]",
      "[top][card]overlay=x=(W-w)/2:y=H-h-20",
    ].join(";"),
    "-frames:v",
    "1",
    "-q:v",
    "2",
    out,
  ]);
}

const work = path.resolve(
  option("--work") ||
    path.join(
      os.tmpdir(),
      `dazedtl-media-${crypto.randomBytes(3).toString("hex")}`,
    ),
);
fs.mkdirSync(work, { recursive: true });
if (fs.readdirSync(work).length)
  throw new Error(`Choose an empty folder; ${work} has files.`);
if (
  !exec("ffmpeg", ["-hide_banner", "-encoders"]).stdout.includes("libwebp_anim")
)
  throw new Error("ffmpeg lacks libwebp_anim, which the animation needs.");

const appWork = path.join(work, "app");
const shots = path.join(work, "shots");
fs.mkdirSync(shots, { recursive: true });
console.log("Building the showcase game in Guided steps…");
exec(
  process.execPath,
  [
    path.join(root, "scripts/scenario.mjs"),
    "set-up",
    "--game",
    "showcase+playable",
    "--app",
    "--work",
    appWork,
  ],
  { stdio: "inherit" },
);
const state = JSON.parse(
  fs.readFileSync(path.join(appWork, "scenario.json"), "utf8"),
);
const modeFile = path.join(appWork, "provider/mode.json");
const setMode = (change) =>
  fs.writeFileSync(
    modeFile,
    JSON.stringify({
      ...JSON.parse(fs.readFileSync(modeFile, "utf8")),
      ...change,
    }),
  );
const page = await Page.connect(state.app.debug, { root: state.root });
try {
  console.log("Playing the game in Japanese…");
  // The village chief's first line.
  const scene = { map: 1, event: 1 };
  playGame(state, [{ ...scene, out: path.join(shots, "game-ja.png") }]);

  console.log("Translating the database…");
  await connect(page, "", "openai");
  const saved = await page.call("settings_get");
  await page.call("settings_save", {
    revision: saved.revision,
    connection_id: saved.activeConnectionId,
    values: { ...saved.values, model: showcaseModel },
    model_options: {},
  });
  await emulate(page, 2);
  await page.click("3Translate");
  await page.click("Database files");
  await page.click("Live");
  await page.click("Translate");
  await until(
    "the estimate",
    () => page.locate("Start Live translation"),
    5 * 60_000,
  );
  await still(page, path.join(shots, "estimate.png"));
  await page.click("Start Live translation");
  await page.waitText("Run finished.", 5 * 60_000);
  await applyTask(page, "Database files");

  console.log("Recording Maps & events…");
  await page.click("Maps & events");
  await page.click("Live");
  await emulate(page, 1);
  setMode({ delay: answerDelay });
  const recording = await record(
    page,
    path.join(work, "frames"),
    async (wait) => {
      await page.evaluate(`void ${pointer}`);
      await pointTo(page, { x: 760, y: 560 });
      await clickShown(page, "Translate");
      await wait(
        until(
          "the estimate",
          () => page.locate("Start Live translation"),
          5 * 60_000,
        ),
      );
      await pause(1600);
      await clickShown(page, "Start Live translation");
      await wait(page.waitText("Run finished.", 5 * 60_000));
      await pause(700);
      await clickShown(page, /^Apply \(\d+\)$/);
      await clickShown(page, "Apply reviewed files");
      await wait(page.waitText("Saved translations applied."));
      await pointTo(page, { x: 900, y: 600 });
      await pause(1500);
    },
  );
  setMode({ delay: 0 });
  await page.idle();
  await page.evaluate(`document.getElementById("media-pointer")?.remove()`);

  console.log("Playing the game in English…");
  playGame(state, [{ ...scene, out: path.join(shots, "game-en.png") }]);

  console.log("Taking the stills…");
  await emulate(page, 2);
  await page.click("Project");
  await page.waitText("lines translated");
  await still(page, path.join(shots, "project.png"));
  await page.click("Translation");
  await page.click(/^5Release/);
  await page.waitText("Build release ZIP");
  await still(page, path.join(shots, "release.png"));

  console.log("Encoding…");
  gameCard(
    path.join(shots, "game-ja.png"),
    path.join(shots, "game-en.png"),
    path.join(shots, "game.png"),
  );
  fs.mkdirSync(media, { recursive: true });
  animate(recording, path.join(media, "translate.webp"));
  webp(path.join(shots, "game.png"), path.join(media, "game.webp"));
  socialCard(path.join(shots, "game.png"), socialPreview);
  for (const name of ["estimate", "project", "release"])
    webp(
      path.join(shots, `${name}.png`),
      path.join(media, `${name}.webp`),
      1760,
    );
  for (const file of [
    ...fs
      .readdirSync(media)
      .sort()
      .map((name) => path.join(media, name)),
    socialPreview,
  ])
    console.log(
      `  ${path.relative(root, file).padEnd(30)} ${(fs.statSync(file).size / 1024).toFixed(0).padStart(5)} KB`,
    );
} finally {
  page.close();
  if (!flag("--keep")) {
    exec(process.execPath, [
      path.join(root, "scripts/scenario.mjs"),
      "clean",
      "--work",
      appWork,
    ]);
    fs.rmSync(work, { recursive: true, force: true });
  } else
    console.log(
      `The app keeps running: node scripts/scenario.mjs clean --work ${appWork}`,
    );
}
