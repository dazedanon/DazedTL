// Saves screens of an RPG Maker MV game the testkit made playable
// (playable.mjs) as PNGs, played offscreen with this checkout's Electron, for
// the README's media (scripts/media.mjs).
//
//   electron scripts/testkit/render.cjs <plan.json>
//
// The plan is { game, shots: [{ map, event, out }] }: for each shot, the game
// starts on map `map` with the title's background drawn over it, since the
// playable game's tiles are placeholders, and runs event `event` until its
// first message shows in full, its speaker in a name box above it as MZ
// draws one.
// The game folder is served read-only, and the game runs muted in a session
// with no network, as rpgmaker_window's launcher runs it.
"use strict";

const { app, BrowserWindow, net, protocol, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const plan = JSON.parse(fs.readFileSync(process.argv.at(-1), "utf8"));
const ORIGIN = "game://game/";
// The screen of an MV game, which the playable game keeps.
const SCREEN = { width: 816, height: 624 };

protocol.registerSchemesAsPrivileged([
  {
    scheme: "game",
    privileges: { standard: true, secure: true, supportFetchAPI: true },
  },
]);
app.commandLine.appendSwitch("force-device-scale-factor", "1");
app.disableHardwareAcceleration();

/** Runs `script`, an async function body, in the page and returns its value. */
const run = (window, script) =>
  window.webContents.executeJavaScript(`(async () => {
    const until = async (check, what, timeout = 30000) => {
      const end = Date.now() + timeout;
      for (;;) {
        const value = check();
        if (value) return value;
        if (Date.now() > end) throw new Error("Timed out waiting for " + what);
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    };
    const frames = (count) => new Promise((resolve) => {
      const step = () => (count-- > 0 ? requestAnimationFrame(step) : resolve());
      step();
    });
    ${script}
  })()`);

/** The game's text in a face that holds Japanese and English alike, where
 * the playable game has no font of its own. */
const font = `
  Window_Base.prototype.standardFontFace = () =>
    '"Noto Sans CJK JP", "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", sans-serif';
`;

/** Plays `shot` up to its message. */
const message = (shot) => `
  ${font}
  await until(() => SceneManager._scene instanceof Scene_Title, "the title screen");
  DataManager.setupNewGame();
  $gamePlayer.reserveTransfer(${shot.map}, $dataSystem.startX, $dataSystem.startY);
  $gamePlayer.setTransparent(true);
  $gamePlayer.hideFollowers();
  SceneManager.goto(Scene_Map);
  const scene = await until(
    () => SceneManager._scene instanceof Scene_Map && SceneManager._scene.isActive() &&
      !$gamePlayer.isTransferring() && !SceneManager._scene._fadeDuration && SceneManager._scene,
    "the map",
  );
  const background = new Sprite(ImageManager.loadTitle1($dataSystem.title1Name));
  scene._spriteset.addChild(background);
  await until(() => background.bitmap.isReady(), "the background");
  $gameMap.event(${shot.event}).start();
  const message = scene._messageWindow;
  await until(() => message.isOpen() && message.pause && !message._textState, "the message", 60000);
  // The message's Show Text command, before the index, which is already
  // past the message's lines.
  const interpreter = $gameMap._interpreter;
  const shown = interpreter._list.slice(0, interpreter._index).reverse()
    .find((command) => command.code === 101);
  const speaker = shown?.parameters[4];
  if (speaker) {
    const box = new Window_Base(0, 0, 0, 0);
    const width = box.textWidth(speaker) + (box.standardPadding() + box.textPadding()) * 2;
    box.move(message.x, message.y - box.fittingHeight(1), width, box.fittingHeight(1));
    box.createContents();
    box.drawText(speaker, 0, 0, box.contentsWidth(), "left");
    scene.addWindow(box);
  }
  await frames(10);
`;

/** Serves the game folder read-only to the game's session. */
function serve(gameSession, folder) {
  gameSession.protocol.handle("game", (request) => {
    const relative = decodeURIComponent(new URL(request.url).pathname);
    const file = path.resolve(folder, `.${relative}`);
    if (!file.startsWith(path.resolve(folder) + path.sep))
      return new Response("Outside the game.", { status: 403 });
    return net.fetch(pathToFileURL(file).href);
  });
  gameSession.webRequest.onBeforeRequest((details, callback) =>
    callback({ cancel: !details.url.startsWith("game:") }),
  );
}

app.whenReady().then(async () => {
  try {
    const gameSession = session.fromPartition("render-game");
    serve(gameSession, plan.game);
    // One window plays the game, loaded afresh for each shot.
    const game = new BrowserWindow({
      show: false,
      useContentSize: true,
      ...SCREEN,
      webPreferences: { offscreen: true, session: gameSession },
    });
    game.webContents.setAudioMuted(true);
    for (const shot of plan.shots) {
      await game.loadURL(`${ORIGIN}index.html`);
      await run(game, message(shot));
      const image = await game.webContents.capturePage();
      fs.mkdirSync(path.dirname(shot.out), { recursive: true });
      fs.writeFileSync(shot.out, image.toPNG());
    }
    app.exit(0);
  } catch (error) {
    console.error(error.stack || error);
    app.exit(1);
  }
});
