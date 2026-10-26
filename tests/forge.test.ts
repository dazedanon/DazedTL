import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { root } from "../scripts/dependencies.mjs";

const quickLoad = fs.readFileSync(
  path.join(root, "backend/dazedtl/engine/util/forge/quick_load.js"),
  "utf8",
);

/** Forge's quick load in a game whose scene manager changes scene only when
 * `change` runs, as a frame does once the old scene has stopped. */
function game() {
  class Scene_Base {
    initialize() {}
    create() {}
    start() {}
    addChild() {}
  }
  class Scene_Map extends Scene_Base {}
  const SceneManager = {
    _scene: new Scene_Map() as Scene_Base,
    _nextScene: null as Scene_Base | null,
    _stack: [] as (new () => Scene_Base)[],
    push(scene: new () => Scene_Base) {
      this._stack.push(this._scene.constructor as new () => Scene_Base);
      this.goto(scene);
    },
    pop() {
      this.goto(this._stack.pop()!);
    },
    goto(scene: new () => Scene_Base) {
      this._nextScene = new scene();
    },
    isSceneChanging() {
      return !!this._nextScene;
    },
    snapForBackground() {},
    backgroundBitmap: () => null,
    change() {
      this._scene = this._nextScene!;
      this._nextScene = null;
      this._scene.create();
      this._scene.start();
    },
  };
  const context: Record<string, unknown> = {
    Scene_Base,
    Sprite: class {},
    SceneManager,
    Promise,
  };
  context.window = context;
  vm.runInNewContext(quickLoad, context);
  const loads: string[] = [];
  /** Forge's own quick load: it replaces the game objects, then goes to the
   * map unless the save failed to load. */
  const load = (loaded: boolean) => (slot: number) => {
    loads.push(`${slot} in ${SceneManager._scene.constructor.name}`);
    if (loaded) SceneManager.goto(Scene_Map);
  };
  const start = context.__dazedForgeQuickLoad as (
    slot: number,
    load: (slot: number) => void,
  ) => void;
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  return { SceneManager, Scene_Map, start, load, loads, settle };
}

test("quick load replaces the game objects only once the map scene has stopped", async () => {
  // Forge loaded the save while the map scene kept updating for its fade, so
  // the map ran the loaded objects against the old map and the game crashed.
  const { SceneManager, Scene_Map, start, load, loads, settle } = game();
  start(1, load(true));
  start(1, load(true));
  await settle();
  assert.deepEqual(loads, []);
  SceneManager.change();
  await settle();
  assert.deepEqual(loads, ["1 in QuickLoadScene"]);
  assert.ok(SceneManager._nextScene instanceof Scene_Map);

  // A save that fails to load returns to the scene quick load left.
  SceneManager.change();
  start(2, load(false));
  SceneManager.change();
  await settle();
  assert.deepEqual(loads.at(-1), "2 in QuickLoadScene");
  assert.ok(SceneManager._nextScene instanceof Scene_Map);
});
