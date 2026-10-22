// Turns the MZ fixture game into one the release playtest can play: RPG
// Maker MV's engine from its open-source corescript (MIT), placeholder images
// drawn here for every image the data names, complete database defaults and
// a plugin that keeps it silent. Nothing from a commercial game is used, so
// the engine downloads once into .runtime instead of living in the repository.
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { runtime } from "../dependencies.mjs";
import { download } from "../setup.mjs";
import { entries, relative } from "../tar.mjs";

const commit = "182e31449707ba7e406db0485c44c2a9d11e2dcd";
const corescript = {
  url: `https://codeload.github.com/rpgtkoolmv/corescript/tar.gz/${commit}`,
  hash: "51edffd5dbe3ce377452cd1df36dc2168e3b3da95b17667ec20fc77fa304203c",
};
const modules = [
  "rpg_core",
  "rpg_managers",
  "rpg_objects",
  "rpg_scenes",
  "rpg_sprites",
  "rpg_windows",
];
const libraries = [
  "pixi.js",
  "pixi-tilemap.js",
  "pixi-picture.js",
  "fpsmeter.js",
  "lz-string.js",
  "iphone-inline-video.browser.js",
];

/** The engine's js folder, built once from the pinned corescript. */
async function engine() {
  const folder = path.join(runtime, `mv-corescript-${commit.slice(0, 12)}`);
  if (fs.existsSync(path.join(folder, "main.js"))) return folder;
  const archive = await download(corescript, "RPG Maker MV corescript");
  const files = new Map();
  for (const entry of entries(archive))
    if (entry.type === "file") files.set(relative(entry.path, 1), entry.data);
  const partial = `${folder}.partial`;
  fs.rmSync(partial, { recursive: true, force: true });
  fs.mkdirSync(path.join(partial, "libs"), { recursive: true });
  for (const name of modules) {
    const order = JSON.parse(files.get(`${name}.json`).toString("utf8"));
    fs.writeFileSync(
      path.join(partial, `${name}.js`),
      order.map((file) => files.get(file).toString("utf8")).join("\n"),
    );
  }
  for (const name of libraries)
    fs.writeFileSync(
      path.join(partial, "libs", name),
      files.get(`js/libs/${name}`),
    );
  fs.writeFileSync(path.join(partial, "main.js"), files.get("js/main.js"));
  fs.writeFileSync(path.join(partial, "LICENSE"), files.get("LICENSE"));
  fs.renameSync(partial, folder);
  return folder;
}

// ------------------------------------------------------------------ images

/** A PNG whose pixel at (x, y) is `color(x, y)` as [r, g, b, a]. */
function png(width, height, color) {
  const rows = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++)
      Buffer.from(color(x, y)).copy(rows, y * (width * 4 + 1) + 1 + x * 4);
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const check = Buffer.alloc(4);
    check.writeUInt32BE(zlib.crc32(body));
    return Buffer.concat([length, body, check]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 6, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", zlib.deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const solid = (rgba) => () => rgba;
/** A window skin: a dark frame and background, white text in every color. */
const windowSkin = (x, y) =>
  x >= 96 && y >= 144
    ? [255, 255, 255, 255]
    : x >= 96 && y < 96
      ? [200, 200, 220, 255]
      : [30, 40, 80, 230];
/** Sizes of the placeholder for each image folder. */
const sizes = {
  animations: [192, 192],
  battlebacks1: [1000, 740],
  battlebacks2: [1000, 740],
  characters: [576, 384],
  enemies: [128, 128],
  faces: [576, 288],
  parallaxes: [816, 624],
  pictures: [64, 64],
  sv_actors: [576, 384],
  sv_enemies: [128, 128],
  tilesets: [768, 768],
  titles1: [816, 624],
  titles2: [816, 624],
};
const system = {
  Window: [192, 192, windowSkin],
  IconSet: [512, 640],
  Balloon: [480, 480],
  ButtonSet: [168, 48],
  Damage: [120, 96],
  GameOver: [816, 624],
  Loading: [300, 60],
  Shadow1: [48, 48],
  Shadow2: [48, 48],
  States: [96, 96],
  Weapons1: [576, 384],
  Weapons2: [576, 384],
  Weapons3: [576, 384],
};

/** Every image the game's data names, as [folder, name] pairs. */
function namedImages(data) {
  const found = new Set();
  const add = (folder, name) => {
    if (typeof name === "string" && name) found.add(`${folder}/${name}`);
  };
  const read = (name) => data[name] || [];
  for (const actor of read("Actors").filter(Boolean)) {
    add("characters", actor.characterName);
    add("faces", actor.faceName);
    add("sv_actors", actor.battlerName);
  }
  for (const enemy of read("Enemies").filter(Boolean)) {
    add("enemies", enemy.battlerName);
    add("sv_enemies", enemy.battlerName);
  }
  for (const tileset of read("Tilesets").filter(Boolean))
    for (const name of tileset.tilesetNames) add("tilesets", name);
  const commands = (list) => {
    for (const command of list || []) {
      if (command.code === 101) add("faces", command.parameters[0]);
      if (command.code === 231) add("pictures", command.parameters[1]);
      if (command.code === 322) {
        add("characters", command.parameters[1]);
        add("faces", command.parameters[3]);
        add("sv_actors", command.parameters[5]);
      }
    }
  };
  for (const event of read("CommonEvents").filter(Boolean))
    commands(event.list);
  for (const troop of read("Troops").filter(Boolean))
    for (const page of troop.pages) commands(page.list);
  for (const [name, map] of Object.entries(data))
    if (/^Map\d+$/.test(name)) {
      add("parallaxes", map.parallaxName);
      add("battlebacks1", map.battleback1Name);
      add("battlebacks2", map.battleback2Name);
      for (const event of map.events.filter(Boolean))
        for (const page of event.pages) {
          add("characters", page.image.characterName);
          commands(page.list);
        }
    }
  const settings = data.System;
  add("titles1", settings.title1Name);
  add("titles2", settings.title2Name);
  add("battlebacks1", settings.battleback1Name);
  add("battlebacks2", settings.battleback2Name);
  add("sv_enemies", settings.battlerName);
  add("enemies", settings.battlerName);
  for (const vehicle of ["boat", "ship", "airship"])
    add("characters", settings[vehicle].characterName);
  return [...found].map((item) => item.split("/"));
}

// ---------------------------------------------------------------- database

const audio = { name: "", pan: 0, pitch: 100, volume: 90 };
const vehicle = (index) => ({
  bgm: audio,
  characterIndex: index,
  characterName: "Vehicle",
  startMapId: 0,
  startX: 0,
  startY: 0,
});
/** The messages a new MV project's System holds, which battles and options read. */
const messages = {
  actionFailure: "There was no effect on %1!",
  actorDamage: "%1 took %2 damage!",
  actorDrain: "%1 was drained of %2 %3!",
  actorGain: "%1 gained %2 %3!",
  actorLoss: "%1 lost %2 %3!",
  actorNoDamage: "%1 took no damage!",
  actorNoHit: "Miss! %1 took no damage!",
  actorRecovery: "%1 recovered %2 %3!",
  alwaysDash: "Always Dash",
  bgmVolume: "BGM Volume",
  bgsVolume: "BGS Volume",
  buffAdd: "%1's %2 went up!",
  buffRemove: "%1's %2 returned to normal!",
  commandRemember: "Command Remember",
  counterAttack: "%1 counterattacked!",
  criticalToActor: "A painful blow!!",
  criticalToEnemy: "An excellent hit!!",
  debuffAdd: "%1's %2 went down!",
  defeat: "%1 was defeated.",
  emerge: "%1 emerged!",
  enemyDamage: "%1 took %2 damage!",
  enemyDrain: "%1 was drained of %2 %3!",
  enemyGain: "%1 gained %2 %3!",
  enemyLoss: "%1 lost %2 %3!",
  enemyNoDamage: "%1 took no damage!",
  enemyNoHit: "Miss! %1 took no damage!",
  enemyRecovery: "%1 recovered %2 %3!",
  escapeFailure: "However, it was unable to escape!",
  escapeStart: "%1 has started to escape!",
  evasion: "%1 evaded the attack!",
  expNext: "To Next %1",
  expTotal: "Current %1",
  file: "File",
  levelUp: "%1 is now %2 %3!",
  loadMessage: "Load which file?",
  magicEvasion: "%1 nullified the magic!",
  magicReflection: "%1 reflected the magic!",
  meVolume: "ME Volume",
  obtainExp: "%1 %2 received!",
  obtainGold: "%1\\G found!",
  obtainItem: "%1 found!",
  obtainSkill: "%1 learned!",
  partyName: "%1's Party",
  possession: "Possession",
  preemptive: "%1 got the upper hand!",
  saveMessage: "Save to which file?",
  seVolume: "SE Volume",
  substitute: "%1 protected %2!",
  surprise: "%1 was surprised!",
  useItem: "%1 uses %2!",
  victory: "%1 was victorious!",
};

/** Fills what the MV engine reads and the small fixture leaves out. */
function complete(data) {
  const settings = data.System;
  data.System = {
    airship: vehicle(3),
    armorTypes: ["", "General Armor"],
    attackMotions: Array.from({ length: 13 }, () => ({
      type: 0,
      weaponImageId: 0,
    })),
    battleBgm: audio,
    battleback1Name: "",
    battleback2Name: "",
    battlerHue: 0,
    battlerName: "",
    boat: vehicle(0),
    defeatMe: audio,
    editMapId: 1,
    gameoverMe: audio,
    magicSkills: [1],
    menuCommands: [true, true, true, true, true, true],
    optDisplayTp: true,
    optDrawTitle: true,
    optExtraExp: false,
    optFloorDeath: false,
    optFollowers: true,
    optSideView: false,
    optSlipDeath: false,
    optTransparent: false,
    ship: vehicle(1),
    sounds: Array.from({ length: 24 }, () => audio),
    testBattlers: [{ actorId: 1, equips: [0, 0, 0, 0, 0], level: 1 }],
    testTroopId: 1,
    title1Name: "",
    title2Name: "",
    titleBgm: audio,
    versionId: 1,
    victoryMe: audio,
    windowTone: [0, 0, 0, 0],
    ...settings,
    terms: {
      ...settings.terms,
      messages: { ...messages, ...settings.terms.messages },
    },
  };
  for (const row of data.Classes.filter(Boolean))
    if (!row.params.length)
      row.params = [500, 100, 20, 20, 20, 20, 20, 20].map((base) =>
        Array.from({ length: 100 }, (_, level) => base + level * 5),
      );
  // Skill 1 is the attack, which the fixture's deals no damage.
  const attack = data.Skills[1];
  if (attack && attack.damage.type === 0)
    attack.damage = { ...attack.damage, type: 1, formula: "100" };
  // State 1 is the engine's knockout. The fixture's wears off on damage, so
  // the hit that knocked the enemy out revived it at 1 HP and the playtest's
  // battle ran to its time limit.
  const knockout = data.States[1];
  if (knockout)
    Object.assign(knockout, {
      autoRemovalTiming: 0,
      removeAtBattleEnd: true,
      removeByDamage: false,
      removeByRestriction: false,
      removeByWalking: false,
      restriction: 4,
    });
  if (!data.Tilesets[1])
    data.Tilesets[1] = {
      id: 1,
      flags: Array.from({ length: 8192 }, () => 0),
      mode: 1,
      name: "",
      note: "",
      tilesetNames: Array.from({ length: 9 }, () => ""),
    };
  // An enemy and a troop, so the playtest's battle stop has one to fight.
  if (!data.Enemies[1])
    data.Enemies[1] = {
      id: 1,
      actions: [
        {
          conditionParam1: 0,
          conditionParam2: 0,
          conditionType: 0,
          rating: 5,
          skillId: 1,
        },
      ],
      battlerHue: 0,
      battlerName: "Slime",
      dropItems: Array.from({ length: 3 }, () => ({
        dataId: 1,
        denominator: 1,
        kind: 0,
      })),
      exp: 10,
      traits: [],
      gold: 10,
      name: "スライム",
      note: "",
      // One hit ends the battle, so the playtest moves on at once.
      params: [1, 0, 1, 1, 1, 1, 1, 1],
    };
  if (!data.Troops[1])
    data.Troops[1] = {
      id: 1,
      members: [{ enemyId: 1, x: 408, y: 300, hidden: false }],
      name: "スライム",
      pages: [
        {
          conditions: {
            actorHp: 50,
            actorId: 1,
            actorValid: false,
            enemyHp: 50,
            enemyIndex: 0,
            enemyValid: false,
            switchId: 1,
            switchValid: false,
            turnA: 0,
            turnB: 0,
            turnEnding: false,
            turnValid: false,
          },
          list: [{ code: 0, indent: 0, parameters: [] }],
          span: 0,
        },
      ],
    };
}

/** No sound, and no wait for a font the placeholder game lacks: it has one
 * only when a variant bundles it through fonts/gamefont.css. */
const plugin = `/*:
 * @plugindesc Test game runtime: plays silently, starts without a font it lacks
 * and selects like MZ.
 */
(function() {
  var silent = function() {};
  ["playBgm", "playBgs", "playMe", "playSe", "playStaticSe", "loadStaticSe",
   "replayBgm", "replayBgs"].forEach(function(name) {
    AudioManager[name] = silent;
  });
  AudioManager.checkErrors = silent;
  if (!document.querySelector('link[href="fonts/gamefont.css"]'))
    Scene_Boot.prototype.isGameFontLoaded = function() { return true; };
  // MZ selects a list's cursor again as the list activates, which plugins
  // written for MZ rely on, such as MPP_ChoiceEX showing the first choice's
  // help at once.
  var activate = Window_Selectable.prototype.activate;
  Window_Selectable.prototype.activate = function() {
    activate.call(this);
    this.reselect();
  };
})();
`;

/** Makes the MZ fixture game at `game` playable. */
export async function makePlayable(game) {
  const js = await engine();
  for (const name of [...modules.map((item) => `${item}.js`), "main.js"])
    fs.copyFileSync(path.join(js, name), path.join(game, "js", name));
  fs.cpSync(path.join(js, "libs"), path.join(game, "js/libs"), {
    recursive: true,
  });
  fs.mkdirSync(path.join(game, "js/plugins"), { recursive: true });
  fs.writeFileSync(path.join(game, "js/plugins/TestGameRuntime.js"), plugin);
  const pluginsFile = path.join(game, "js/plugins.js");
  const text = fs.readFileSync(pluginsFile, "utf8");
  fs.writeFileSync(
    pluginsFile,
    text.replace(
      /\]\s*;?\s*$/,
      `,\n${JSON.stringify({ name: "TestGameRuntime", status: true, description: "", parameters: {} })}\n];\n`,
    ),
  );
  fs.rmSync(path.join(game, "game.rmmzproject"), { force: true });
  fs.writeFileSync(path.join(game, "Game.rpgproject"), "RPGMV 1.6.2");
  const title = JSON.parse(
    fs.readFileSync(path.join(game, "data/System.json"), "utf8"),
  ).gameTitle;
  fs.writeFileSync(
    path.join(game, "index.html"),
    `<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="user-scalable=no">
    <title>${title}</title>${
      // A variant's bundled font, which MV's engine draws text in.
      fs.existsSync(path.join(game, "fonts/gamefont.css"))
        ? '\n    <link rel="stylesheet" type="text/css" href="fonts/gamefont.css">'
        : ""
    }
  </head>
  <body style="background-color: black">
${[
  ...libraries.map((name) => `libs/${name}`),
  ...modules.map((name) => `${name}.js`),
  "plugins.js",
  "main.js",
]
  .map(
    (name) => `    <script type="text/javascript" src="js/${name}"></script>`,
  )
  .join("\n")}
  </body>
</html>
`,
  );
  const folder = path.join(game, "data");
  const data = Object.fromEntries(
    fs
      .readdirSync(folder)
      .filter((name) => name.endsWith(".json"))
      .map((name) => [
        path.basename(name, ".json"),
        JSON.parse(fs.readFileSync(path.join(folder, name), "utf8")),
      ]),
  );
  complete(data);
  for (const name of [
    "System",
    "Classes",
    "Skills",
    "States",
    "Tilesets",
    "Enemies",
    "Troops",
  ])
    fs.writeFileSync(
      path.join(folder, `${name}.json`),
      JSON.stringify(data[name]),
    );
  const write = (
    folder,
    name,
    [width, height, color = solid([90, 140, 200, 255])],
  ) => {
    const file = path.join(game, "img", folder, `${name}.png`);
    if (fs.existsSync(file)) return;
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, png(width, height, color));
  };
  for (const [name, size] of Object.entries(system))
    write("system", name, size);
  for (const [folder, name] of namedImages(data))
    write(folder, name, sizes[folder] || [64, 64]);
}
