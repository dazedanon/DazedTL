import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { root } from "../scripts/dependencies.mjs";

const page = fs.readFileSync(
  path.join(root, "backend/dazedtl/engine/util/playtest/harness/page.js"),
  "utf8",
);

/** The release playtest's page script in a game made of the few engine
 * classes its hooks change, with one help window on screen and the game's
 * own `globals`, such as its map and message. */
function game(
  globals: Record<string, unknown> = {},
  blocks: Record<string, unknown> = {},
) {
  const listeners: Record<string, ((event: unknown) => void)[]> = {};
  let frame = 0;
  // Glyphs of 26-pixel text reach 6 pixels below their baseline.
  class Bitmap {
    height = 72;
    fontSize = 26;
    outlineWidth = 3;
    context = {
      save() {},
      restore() {},
      measureText: () => ({ actualBoundingBoxDescent: 6 }),
    };
    _makeFontNameText() {
      return "26px GameFont";
    }
    drawText(_text: string) {}
  }
  class Sprite {
    visible = true;
    worldVisible = true;
    worldAlpha = 1;
    children: Sprite[] = [];
    bitmap: Bitmap | null;
    constructor(bitmap: Bitmap | null = null) {
      this.bitmap = bitmap;
    }
    getBounds() {
      return { x: 0, y: 0, width: 100, height: 72 };
    }
  }
  class Window_Base {
    contents = new Bitmap();
    lines: string[] = [];
    contentsWidth() {
      return 400;
    }
    contentsHeight() {
      return 72;
    }
    // Draws each line 36 pixels below the last, as MZ does once it reads
    // the line's end.
    drawTextEx(text: string, x: number, y: number) {
      const state = {
        x,
        y,
        height: 36,
        drawing: true,
        text,
        index: 0,
        buffer: "",
      };
      for (const line of text.split("\n")) {
        this.contents.drawText(line);
        state.buffer = line;
        state.x = x + line.length * 10;
        state.index += line.length + 1;
        this.flushTextState(state);
        state.buffer = "";
        state.y += 36;
      }
    }
    convertEscapeCharacters(text: string) {
      return text;
    }
    flushTextState(_state: object) {}
    processNewLine() {}
  }
  class Window_Selectable extends Window_Base {}
  class Window_Help extends Window_Base {
    // Gear help as a plugin may draw it, as Arina's does: the description's
    // first line, then a line of the plugin's own.
    setItem(item: { id: number; description: string; stats?: string }) {
      this.setText(
        item.stats
          ? `${item.description.split("\n")[0]}\n${item.stats}`
          : item.description,
      );
    }
    setText(text: string) {
      this.drawTextEx(text, 0, 0);
    }
  }
  // A window whose contents fit its glyphs rather than its line, as
  // Keke_PredictionSystem's action view sizes them.
  class Window_ActView extends Window_Base {
    contentsHeight() {
      return 33;
    }
  }
  class Window_Message extends Window_Base {
    startMessage() {}
    newPage(_state: object) {}
  }
  class Window_ChoiceList extends Window_Selectable {
    start() {}
  }
  class Window_BattleLog extends Window_Base {
    addText() {}
  }
  const help = new Window_Help();
  const hidden = new Window_Help();
  const action = new Window_ActView();
  const message = new Window_Message();
  const shown = new Sprite(help.contents);
  const unseen = new Sprite(hidden.contents);
  unseen.worldVisible = false;
  const scene = Object.assign(new Sprite(), {
    constructor: { name: "Scene_Item" },
    children: [
      shown,
      unseen,
      new Sprite(action.contents),
      new Sprite(message.contents),
    ],
  });
  // A choice open with help (MPP_ChoiceEX), which the message window shows.
  const $gameMessage = { isBusy: () => false, isChoiceHelp: () => true };
  // What the page sends the main process, as plain data the way IPC copies
  // it; a plan without stops leaves only the hooks running.
  const sent: { type: string; value: Record<string, unknown> }[] = [];
  const context: Record<string, unknown> = {
    dazedtlHarness: {
      plan: () => ({ stops: [], blocks }),
      send: (type: string, value: Record<string, unknown>) =>
        sent.push({ type, value: structuredClone(value) }),
    },
    console: { ...console, error() {} },
    document: {},
    KeyboardEvent: class {},
    Element: class {},
    Bitmap,
    Window_Base,
    Window_Selectable,
    Window_Help,
    Window_Message,
    Window_ChoiceList,
    Window_BattleLog,
    $gameMessage,
    Spriteset_Battle: class {},
    SceneManager: {
      _scene: scene,
      isSceneChanging: () => false,
      snap: () => ({
        canvas: { toDataURL: () => "data:image/jpeg;base64,AA==" },
      }),
    },
    Graphics: {
      width: 816,
      height: 624,
      // Each look at the clock is a new frame.
      get frameCount() {
        return frame++;
      },
    },
    DataManager: {
      isSkill: () => false,
      isItem: () => true,
      isWeapon: () => false,
      isArmor: () => false,
    },
    addEventListener(type: string, listener: (event: unknown) => void) {
      (listeners[type] ||= []).push(listener);
    },
    setTimeout,
    ...globals,
  };
  context.window = context;
  vm.runInNewContext(page, context);
  for (const listener of listeners.load) listener({});
  const playtest = context.__playtest as { look(): Promise<void> };
  /** A window the player sees. */
  const show = <T extends Window_Base>(window_: T) => {
    scene.children.push(new Sprite(window_.contents));
    return window_;
  };
  return {
    playtest,
    sent,
    help,
    hidden,
    action,
    message,
    show,
    Window_Base,
    Window_Message,
    Window_ChoiceList,
  };
}

test("the playtest records text that runs past a window players see", async () => {
  const { playtest, sent, help, hidden, action, message, Window_Base } = game();
  // A three-line description in a two-line help window, attributed to its
  // database entry, and a sentence too wide for it.
  help.setItem({
    id: 21,
    description: "Blocks one attack.\nThen it\nshatters.",
  });
  help.setText("x".repeat(45));
  // Gear help whose description fits, beside a line of stats too wide for
  // the window: shortening the description would not fix those.
  help.setItem({
    id: 22,
    description: "A black collar.\nHP never runs out.\nA reward.",
    stats: "Effect: " + "y".repeat(40),
  });
  // A hidden window, a pass that only measures, and Japanese drawn on it.
  hidden.setText("One\nTwo\nThree 呪い");
  const measure = new Window_Base();
  measure.drawTextEx("One\nTwo\nThree", 0, 72);
  // Glyphs that fit a window sized to them, and the empty line after them.
  action.drawTextEx("Attack\n", 0, 0);
  // A choice's help starts its first page, then needs another: its first
  // rows are gone before the player reads them.
  const helpText = "Row one\nRow two\nRow three";
  message.newPage({ index: 0, x: 0, y: 0, height: 36, text: helpText });
  message.newPage({ index: 16, x: 0, y: 72, height: 36, text: helpText });
  await playtest.look();
  const events = (type: string) =>
    sent.filter((event) => event.type === type).map((event) => event.value);
  assert.deepEqual(
    events("overflow").map((event) => [
      event.edge,
      event.data ?? null,
      event.capture,
    ]),
    [
      [
        "bottom",
        { file: "Items.json", pointer: "/21/description" },
        "001-overflow",
      ],
      ["right", null, "001-overflow"],
      ["right", null, "001-overflow"],
      ["bottom", null, "001-overflow"],
    ],
  );
  // Which entries a help window showed, for the static line count; routine,
  // so it takes no capture of its own.
  assert.deepEqual(
    events("help").map((event) => event.data),
    [
      { file: "Items.json", pointer: "/21/description" },
      { file: "Items.json", pointer: "/22/description" },
    ],
  );
  assert.equal(events("japanese").length, 0);
  assert.equal(events("capture").length, 1);
});

test("the playtest names the event command whose text a window draws", async () => {
  // A translated message and its choices, then the help a plugin shows in
  // the message window for each choice, as MPP_ChoiceEX does, from an
  // event comment the engine never translated.
  const list = [
    { code: 101, parameters: ["", 0, 0, 2, ""] },
    { code: 401, parameters: ["Pick one."], _original: "選んで。" },
    {
      code: 102,
      parameters: [["見る", "Skip"], -1, 0, 1, 0],
      _original: ["見る", "飛ばす"],
    },
    { code: 402, parameters: [0, "見る"] },
    { code: 108, parameters: ["選択肢ヘルプ"] },
    { code: 408, parameters: ["\\>所要時間:20分"] },
    { code: 408, parameters: ["初回は\\c[3]推奨\\C[0]します。"] },
  ];
  let texts = ["Pick one."];
  const interpreter = { _list: list, _index: 2, isRunning: () => true };
  const {
    playtest,
    sent,
    show,
    Window_Base,
    Window_Message,
    Window_ChoiceList,
  } = game(
    {
      $dataMap: { events: [null, { id: 1, pages: [{ list }] }] },
      $gameMap: {
        mapId: () => 1,
        _interpreter: interpreter,
        events: () => [],
        _commonEvents: [],
      },
      $gameParty: { inBattle: () => false },
      $gameTroop: {},
      $gameMessage: {
        allText: () => texts.join("\n"),
        isBusy: () => true,
        speakerName: () => "",
        choices: () => ["見る", "Skip"],
      },
    },
    // The list's text blocks, as the playtest reads them before it plays.
    {
      "Map001.json": {
        "/events/1/pages/0/list": [
          ["message", 0, 1, 1, 0, "", 1],
          ["help", 4, 5, 6, 1, "選択肢ヘルプ", 1],
        ],
      },
    },
  );
  const message = show(new Window_Message());
  const choices = show(new Window_ChoiceList());
  // A map's HUD draws its own text while the message is open.
  const hud = show(new Window_Base());
  message.startMessage();
  choices.start();
  choices.contents.drawText("見る");
  hud.contents.drawText("現在地");
  texts = list.slice(5).map((command) => String(command.parameters[0]));
  message.startMessage();
  message.contents.drawText("所要時間:20分");
  message.contents.drawText("推奨");
  await playtest.look();
  const drawn = Object.fromEntries(
    sent
      .filter((event) => event.type === "japanese")
      .map((event) => [event.value.text, event.value.data ?? null]),
  );
  const page = "/events/1/pages/0/list";
  const help = {
    file: "Map001.json",
    pointer: `${page}/5`,
    last: 6,
    untranslated: true,
    comment: "選択肢ヘルプ",
    shown: true,
  };
  assert.deepEqual(drawn, {
    見る: { file: "Map001.json", pointer: `${page}/2/parameters/0/0` },
    現在地: null,
    "所要時間:20分": help,
    推奨: help,
  });
});
