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
 * classes its hooks change, with one help window on screen. */
function game() {
  const listeners: Record<string, ((event: unknown) => void)[]> = {};
  let frame = 0;
  class Bitmap {
    height = 72;
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
      const state = { x, y, height: 36, drawing: true, text, index: 0 };
      for (const line of text.split("\n")) {
        this.contents.drawText(line);
        state.x = x + line.length * 10;
        state.index += line.length + 1;
        this.flushTextState(state);
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
  class Window_Message extends Window_Base {
    startMessage() {}
  }
  class Window_ChoiceList extends Window_Selectable {
    start() {}
  }
  class Window_BattleLog extends Window_Base {
    addText() {}
  }
  const help = new Window_Help();
  const hidden = new Window_Help();
  const shown = new Sprite(help.contents);
  const unseen = new Sprite(hidden.contents);
  unseen.worldVisible = false;
  const scene = Object.assign(new Sprite(), {
    constructor: { name: "Scene_Item" },
    children: [shown, unseen],
  });
  // What the page sends the main process, as plain data the way IPC copies
  // it; a plan without stops leaves only the hooks running.
  const sent: { type: string; value: Record<string, unknown> }[] = [];
  const context: Record<string, unknown> = {
    dazedtlHarness: {
      plan: () => ({ stops: [] }),
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
  };
  context.window = context;
  vm.runInNewContext(page, context);
  for (const listener of listeners.load) listener({});
  const playtest = context.__playtest as { look(): Promise<void> };
  return { playtest, sent, help, hidden, Window_Base };
}

test("the playtest records text that runs past a window players see", async () => {
  const { playtest, sent, help, hidden, Window_Base } = game();
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
