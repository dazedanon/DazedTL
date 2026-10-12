// The release playtest inside the game's page: hooks that record what the
// game shows, and the tour that plays it. rpgmaker_window/launcher.cjs runs
// this before the game's own scripts, and everything it records goes to
// harness/main.cjs as it happens, through the launcher's bridge.
//
// Works on RPG Maker MV and MZ. It never writes the game folder: the page
// runs in a session of its own, so saves and options stay there.
"use strict";
(() => {
  const JAPANESE = /[ぁ-ゔァ-ヴ一-龠々〆〤]/;
  const PLACEHOLDER = /[◯〇]|○○/;
  // Errors from a plugin that needs NW.js, which this browser lacks.
  const NEEDS_NWJS =
    /\b(?:require|nw|process|global|__dirname|__filename)\b is not defined|reading '(?:Window|App|Shell|Clipboard)'/;
  const ENGINE_SCENES = new Set([
    "Scene_Base",
    "Scene_Boot",
    "Scene_Title",
    "Scene_Message",
    "Scene_Map",
    "Scene_MenuBase",
    "Scene_Menu",
    "Scene_ItemBase",
    "Scene_Item",
    "Scene_Skill",
    "Scene_Equip",
    "Scene_Status",
    "Scene_Options",
    "Scene_File",
    "Scene_Save",
    "Scene_Load",
    "Scene_GameEnd",
    "Scene_Shop",
    "Scene_Name",
    "Scene_Debug",
    "Scene_Battle",
    "Scene_Gameover",
  ]);
  const KEYS = {
    ok: [13, "Enter"],
    cancel: [27, "Escape"],
    up: [38, "ArrowUp"],
    down: [40, "ArrowDown"],
    left: [37, "ArrowLeft"],
    right: [39, "ArrowRight"],
  };
  const CAPTURE_LIMIT = 80;
  const TEXT_LIMIT = 200;

  const bridge = window.dazedtlHarness;
  const seen = new Set();
  const state = {
    stop: "boot",
    crashed: "",
    captures: 0,
    scenes: new Set(),
    help: null,
    item: null,
    message: null,
    messages: 0,
    pending: [],
    backdrop: null,
    // Game updates a frame: the tour plays text and battles faster.
    speed: 1,
  };
  const send = (type, value) => bridge.send(type, value);
  /** Names what the tour does now, which a crash or hang interrupts. */
  function doing(stop) {
    state.stop = stop;
    bridge.send("step", stop);
  }
  const clip = (text) =>
    String(text).length > TEXT_LIMIT
      ? String(text).slice(0, TEXT_LIMIT) + "…"
      : String(text);

  // ---------------------------------------------------------------- where

  function sceneName() {
    const scene = window.SceneManager && SceneManager._scene;
    return scene ? scene.constructor.name : "";
  }

  function mapId() {
    try {
      return window.$gameMap ? $gameMap.mapId() : 0;
    } catch {
      return 0;
    }
  }

  /** The file and line in a stack that drew something: the first plugin's,
   * or else the engine's, past this script. */
  function source(stack) {
    let engine = null;
    for (const line of String(stack).split("\n").slice(1)) {
      const match = /\/(js\/[^\s?#)]+\.js)(?:\?[^:\s)]*)?:(\d+):(\d+)/.exec(
        line,
      );
      if (!match || match[1].includes("/libs/")) continue;
      const found = {
        file: decodeURIComponent(match[1]),
        line: Number(match[2]),
        column: Number(match[3]),
      };
      if (found.file.startsWith("js/plugins/")) return found;
      engine ||= found;
    }
    return engine;
  }

  function where(extra = {}) {
    return { stop: state.stop, scene: sceneName(), map: mapId(), ...extra };
  }

  /** The event command list an interpreter runs, as a JSON pointer into its
   * data file, found by the identity of the list the engine parsed. */
  function listPointer(list) {
    try {
      if (window.$dataMap && $dataMap.events)
        for (const event of $dataMap.events)
          if (event)
            for (let page = 0; page < event.pages.length; page++)
              if (event.pages[page].list === list)
                return {
                  file: `Map${String($gameMap.mapId()).padStart(3, "0")}.json`,
                  pointer: `/events/${event.id}/pages/${page}/list`,
                };
      for (const common of window.$dataCommonEvents || [])
        if (common && common.list === list)
          return { file: "CommonEvents.json", pointer: `/${common.id}/list` };
      for (const troop of window.$dataTroops || [])
        if (troop)
          for (let page = 0; page < troop.pages.length; page++)
            if (troop.pages[page].list === list)
              return {
                file: "Troops.json",
                pointer: `/${troop.id}/pages/${page}/list`,
              };
    } catch {
      // A plugin's own data layout leaves the message unplaced.
    }
    return null;
  }

  /** The Show Text command behind the message on screen. */
  function messageSource() {
    const interpreters = [];
    const add = (interpreter) => {
      while (interpreter) {
        interpreters.push(interpreter);
        interpreter = interpreter._childInterpreter;
      }
    };
    try {
      if (window.$gameTroop && $gameParty.inBattle())
        add($gameTroop._interpreter);
      if (window.$gameMap) {
        add($gameMap._interpreter);
        for (const event of $gameMap.events()) add(event._interpreter);
        for (const common of $gameMap._commonEvents || [])
          add(common._interpreter);
      }
    } catch {
      return null;
    }
    for (const interpreter of interpreters.reverse()) {
      const list = interpreter._list;
      if (!list || !interpreter.isRunning || !interpreter.isRunning()) continue;
      let index = Math.min(interpreter._index, list.length - 1);
      while (index > 0 && list[index] && list[index].code !== 101) index--;
      if (!list[index] || list[index].code !== 101) continue;
      const found = listPointer(list);
      if (found)
        return { file: found.file, pointer: `${found.pointer}/${index}` };
    }
    return null;
  }

  /** The database field a help window shows. */
  function helpSource(item) {
    if (!item || !window.DataManager) return null;
    const file = DataManager.isSkill(item)
      ? "Skills.json"
      : DataManager.isItem(item)
        ? "Items.json"
        : DataManager.isWeapon(item)
          ? "Weapons.json"
          : DataManager.isArmor(item)
            ? "Armors.json"
            : "";
    return file ? { file, pointer: `/${item.id}/description` } : null;
  }

  // ---------------------------------------------------------------- errors

  function error(kind, message, stack = "") {
    const text = clip(message);
    const nwjs = NEEDS_NWJS.test(text);
    const key = "error " + text + " " + state.stop;
    if (seen.has(key)) return;
    seen.add(key);
    send(
      "error",
      where({
        kind: nwjs ? "nwjs" : kind,
        message: text,
        stack: clip(String(stack).split("\n").slice(0, 6).join("\n")),
        source: source(stack),
      }),
    );
  }

  window.addEventListener(
    "error",
    (event) => {
      // A file an element could not load, such as a script or an image.
      // The playtest blocks the network, so what the game asks of other
      // sites, such as a web font a style imports, never loads.
      const target = event.target;
      if (target instanceof Element) {
        const url = String(target.src || target.href || "");
        const local = url.match(/^game:\/\/game\/(.*)$/);
        if (local)
          error("load", "Failed to load: " + decodeURIComponent(local[1]));
        return;
      }
      error(
        "error",
        event.message || "Script error",
        event.error && event.error.stack ? event.error.stack : "",
      );
    },
    true,
  );
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    error(
      "rejection",
      reason && reason.message ? reason.message : String(reason),
      reason && reason.stack ? reason.stack : "",
    );
  });
  const consoleError = console.error.bind(console);
  console.error = (...values) => {
    consoleError(...values);
    const first = values.find((value) => value instanceof Error);
    error(
      "console",
      values
        .map((value) => (value && value.message) || String(value))
        .join(" "),
      first ? first.stack : new Error().stack,
    );
  };

  // ---------------------------------------------------------------- hooks

  function after(owner, name, run) {
    const original = owner && owner[name];
    if (typeof original !== "function") return;
    owner[name] = function (...values) {
      const result = original.apply(this, values);
      try {
        run.call(this, values, result);
      } catch {
        // A hook never breaks the game it watches.
      }
      return result;
    };
  }

  function before(owner, name, run) {
    const original = owner && owner[name];
    if (typeof original !== "function") return;
    owner[name] = function (...values) {
      try {
        run.call(this, values);
      } catch {
        // A hook never breaks the game it watches.
      }
      return original.apply(this, values);
    };
  }

  /** Japanese or a placeholder glyph the game draws, once per screen. */
  function drawn(text, bitmap) {
    if (typeof text !== "string" && typeof text !== "number") return;
    text = String(text);
    if (text.replace(/\s/g, "").length < 2 && !PLACEHOLDER.test(text)) return;
    const japanese = JAPANESE.test(text);
    if (!japanese && !PLACEHOLDER.test(text)) return;
    const key = "draw " + sceneName() + " " + text.replace(/\d+/g, "#");
    if (seen.has(key) || state.pending.some((row) => row.key === key)) return;
    const stack = new Error().stack;
    const message =
      state.message && window.$gameMessage && $gameMessage.isBusy()
        ? state.message
        : null;
    const help =
      state.help && bitmap === state.help.window.contents ? state.help : null;
    state.pending.push({
      type: "japanese",
      key,
      bitmap,
      event: where({
        text: clip(text),
        glyph: !japanese,
        source: source(stack),
        ...(message && message.source && { data: message.source }),
        ...(help && help.source && { data: help.source }),
      }),
    });
  }

  /** Text that runs past its window's contents. */
  function overflow(window_, textState, edge) {
    if (!window_.contents || /NameBox/.test(window_.constructor.name)) return;
    const text = window_._playtestText || textState.text || "";
    const key =
      "overflow " +
      window_.constructor.name +
      " " +
      edge +
      " " +
      String(text).replace(/\d+/g, "#");
    if (seen.has(key) || state.pending.some((row) => row.key === key)) return;
    const help =
      state.help && state.help.window === window_ ? state.help.source : null;
    const message =
      /Message/.test(window_.constructor.name) && state.message
        ? state.message.source
        : null;
    state.pending.push({
      type: "overflow",
      key,
      bitmap: window_.contents,
      event: where({
        window: window_.constructor.name,
        edge,
        text: clip(text),
        width: Math.round(window_.contentsWidth()),
        height: Math.round(window_.contentsHeight()),
        x: Math.round(textState.x),
        y: Math.round(textState.y + (textState.height || 0)),
        ...((help || message) && { data: help || message }),
        source: source(new Error().stack),
      }),
    });
  }

  function checkBounds(textState, drew) {
    if (!drew || this._playtestMeasuring) return;
    const width = this.contentsWidth();
    const height = this.contentsHeight();
    // A window too small for a line only stands in for drawing elsewhere.
    if (width < 24 || height < 12) return;
    if (textState.x > width + 2) overflow(this, textState, "right");
    // A list scrolls, so its rows below the window are expected, and a
    // message goes on in a new page.
    else if (
      textState.y + (textState.height || 0) > height + 2 &&
      !(window.Window_Selectable && this instanceof Window_Selectable) &&
      !(window.Window_Message && this instanceof Window_Message)
    )
      overflow(this, textState, "bottom");
  }

  function install() {
    // MZ pauses while the page lacks focus; this page never has it.
    SceneManager.isGameActive = () => true;
    // Faster play runs more game updates for each frame drawn, as the
    // engine itself does to catch up after a slow frame.
    if (SceneManager.determineRepeatNumber) {
      const repeat = SceneManager.determineRepeatNumber;
      SceneManager.determineRepeatNumber = function (...values) {
        return repeat.apply(this, values) * state.speed;
      };
    } else
      before(SceneManager, "updateMain", function () {
        if (this._accumulator !== undefined && this._deltaTime)
          this._accumulator += (state.speed - 1) * this._deltaTime;
      });
    after(Graphics, "printError", ([name, message, cause]) => {
      state.crashed = `${name}: ${message}`;
      error(
        "crash",
        `${name}: ${message}`,
        cause && cause.stack ? cause.stack : "",
      );
    });
    after(Graphics, "printLoadingError", ([url]) =>
      error("load", `Failed to load: ${url}`),
    );
    after(SceneManager, "stop", () => {
      state.crashed ||= "The game stopped.";
    });
    after(Bitmap.prototype, "drawText", function ([text]) {
      drawn(text, this);
    });
    // Which database entry a help window draws, set before it draws.
    const setItem = Window_Help.prototype.setItem;
    Window_Help.prototype.setItem = function (item) {
      state.item = { window: this, source: helpSource(item) };
      try {
        return setItem.call(this, item);
      } finally {
        state.item = null;
      }
    };
    before(Window_Help.prototype, "setText", function () {
      state.help = {
        window: this,
        source:
          state.item && state.item.window === this ? state.item.source : null,
      };
    });
    // A pass that only measures, MZ's drawing false or MV's text drawn below
    // the contents, can't overflow.
    const drawTextEx = Window_Base.prototype.drawTextEx;
    Window_Base.prototype.drawTextEx = function (text, x, y, ...rest) {
      const measuring = this._playtestMeasuring;
      const textBefore = this._playtestText;
      this._playtestMeasuring =
        measuring || (this.contents && y >= this.contents.height);
      this._playtestText = text;
      try {
        return drawTextEx.call(this, text, x, y, ...rest);
      } finally {
        this._playtestMeasuring = measuring;
        this._playtestText = textBefore;
      }
    };
    if (Window_Base.prototype.flushTextState)
      after(Window_Base.prototype, "flushTextState", function ([textState]) {
        checkBounds.call(this, textState, textState.drawing !== false);
      });
    else
      after(
        Window_Base.prototype,
        "processNormalCharacter",
        function ([textState]) {
          checkBounds.call(this, textState, true);
        },
      );
    before(Window_Message.prototype, "startMessage", () => {
      state.messages++;
      state.message = {
        source: messageSource(),
        text: $gameMessage.allText(),
      };
      send(
        "message",
        where({
          text: clip($gameMessage.allText()),
          ...(state.message.source && { data: state.message.source }),
        }),
      );
    });
    after(Window_ChoiceList.prototype, "start", () => {
      send("choice", where({ choices: $gameMessage.choices().map(clip) }));
    });
    // MZ names the background in Sprite_Battleback, MV in Spriteset_Battle.
    const backdrops = window.Sprite_Battleback
      ? Sprite_Battleback.prototype
      : Spriteset_Battle.prototype;
    for (const [name, at] of [
      ["battleback1Name", 0],
      ["battleback2Name", 1],
    ]) {
      const original = backdrops[name];
      if (typeof original === "function")
        backdrops[name] = function (...values) {
          return state.backdrop && !$gameMap[name]()
            ? state.backdrop[at]
            : original.apply(this, values);
        };
    }
    after(Window_BattleLog.prototype, "addText", ([text]) => {
      send("battle", where({ text: clip(text) }));
    });
  }

  // Before main.js, so this runs ahead of the engine's own load handler,
  // which boots the game.
  window.addEventListener(
    "load",
    () => {
      try {
        install();
      } catch (problem) {
        error(
          "harness",
          "The playtest could not hook the game: " + problem.message,
          problem.stack,
        );
      }
      // The tour waits for the game to start, and starts where the plan
      // says: past the stops an earlier window played.
      tour(bridge.plan()).catch((problem) =>
        send("stop", {
          id: state.stop,
          status: "failed",
          note: problem.message,
          crashed: true,
        }),
      );
    },
    true,
  );

  // ---------------------------------------------------------------- timing

  function frames(count = 1) {
    const target = (Graphics.frameCount || 0) + count;
    const started = Date.now();
    return new Promise((resolve) => {
      const check = () =>
        (Graphics.frameCount || 0) >= target ||
        Date.now() - started > count * 100 + 1000
          ? resolve()
          : setTimeout(check, 8);
      check();
    });
  }

  async function until(test, seconds) {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      if (state.crashed) throw new Crash(state.crashed);
      try {
        if (test()) return true;
      } catch {
        // Not ready yet.
      }
      await frames(1);
    }
    return false;
  }

  class Crash extends Error {}

  // ---------------------------------------------------------------- input

  function key(name, type) {
    const [code, keyName] = KEYS[name];
    const event = new KeyboardEvent(type, {
      key: keyName,
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(event, "keyCode", { get: () => code });
    Object.defineProperty(event, "which", { get: () => code });
    document.dispatchEvent(event);
  }

  async function press(name) {
    await flush();
    key(name, "keydown");
    await frames(3);
    key(name, "keyup");
    await frames(3);
  }

  // ---------------------------------------------------------------- captures

  /** Whether a bitmap is on screen: a visible sprite in the scene shows it,
   * such as a window's contents, inside the screen. */
  function onScreen(bitmap) {
    if (!bitmap) return true;
    const stack = scene() ? [scene()] : [];
    while (stack.length) {
      const node = stack.pop();
      if (
        node.bitmap === bitmap &&
        node.worldVisible &&
        node.worldAlpha > 0.05
      ) {
        const bounds = node.getBounds();
        if (
          bounds.width > 0 &&
          bounds.x < Graphics.width &&
          bounds.y < Graphics.height &&
          bounds.x + bounds.width > 0 &&
          bounds.y + bounds.height > 0
        )
          return true;
      }
      if (node.visible !== false && node.children) stack.push(...node.children);
    }
    return false;
  }

  /** Records what the tour found since it last looked, once it is on
   * screen, with one capture of the screen; a finding on a bitmap nobody
   * sees is dropped. The tour looks before it changes anything. */
  async function flush() {
    if (!state.pending.length) return;
    // A fade in or out shows nothing yet.
    for (
      let wait = 0;
      wait < 30 && scene() && scene()._fadeDuration > 0;
      wait++
    )
      await frames(1);
    await frames(2);
    const shown = state.pending
      .splice(0, state.pending.length)
      .filter((row) => !seen.has(row.key) && onScreen(row.bitmap));
    if (!shown.length) return;
    let name;
    if (state.captures < CAPTURE_LIMIT)
      try {
        const data = SceneManager.snap().canvas.toDataURL("image/jpeg", 0.82);
        name = `${String(++state.captures).padStart(3, "0")}-${shown[0].type}`;
        send("capture", { name, stop: state.stop, scene: sceneName(), data });
      } catch {
        // A screen that can't be read keeps its findings without a picture.
      }
    for (const row of shown) {
      seen.add(row.key);
      send(row.type, { ...row.event, ...(name && { capture: name }) });
    }
  }

  function visited() {
    const name = sceneName();
    if (name && !state.scenes.has(name)) {
      state.scenes.add(name);
      state.pending.push({
        type: "scene",
        key: "scene " + name,
        bitmap: null,
        event: where(),
      });
    }
  }

  // ---------------------------------------------------------------- scenes

  const scene = () => SceneManager._scene;
  const isScene = (name) =>
    !!scene() &&
    !SceneManager.isSceneChanging() &&
    scene().constructor.name === name;

  /** The windows of the current scene that take input now. */
  function activeWindows() {
    const layer = scene() && scene()._windowLayer;
    return layer
      ? layer.children.filter(
          (child) =>
            window.Window_Selectable &&
            child instanceof Window_Selectable &&
            child.active &&
            child.visible &&
            child.isOpen(),
        )
      : [];
  }

  async function settle(seconds = 10) {
    await until(
      () =>
        scene() &&
        !SceneManager.isSceneChanging() &&
        scene().isStarted?.() !== false &&
        scene().isActive?.() !== false,
      seconds,
    );
    await frames(10);
    visited();
  }

  /** Shows each row of a list once, so a help window draws every entry. */
  async function everyRow(list) {
    if (!list || !list.maxItems) return 0;
    const count = list.maxItems();
    for (let index = 0; index < count; index++) {
      await flush();
      list.select(index);
      if (list.ensureCursorVisible) list.ensureCursorVisible(false);
      if (list.callUpdateHelp) list.callUpdateHelp();
      await frames(1);
    }
    return count;
  }

  /** Leaves the current scene the way the player does, then by force. */
  async function leave(target = "Scene_Map") {
    for (let tries = 0; tries < 12 && !isScene(target); tries++) {
      await press("cancel");
      await frames(8);
    }
    if (!isScene(target)) {
      SceneManager.goto(window[target]);
      await settle();
    }
  }

  /** Chooses a command by its symbol, with the arrow keys where possible. */
  async function choose(window_, symbol) {
    const index = window_.findSymbol(symbol);
    if (index < 0) return false;
    await flush();
    // A window opening or a scene fading in takes no input yet.
    await until(() => window_.isOpenAndActive() && !scene().isBusy(), 5);
    window_.select(index);
    await frames(2);
    await press("ok");
    return true;
  }

  async function exploreScene(name) {
    const current = scene();
    if (name === "Scene_Item") {
      for (let index = 0; index < current._categoryWindow.maxItems(); index++) {
        current._categoryWindow.select(index);
        await press("ok");
        await everyRow(current._itemWindow);
        await press("cancel");
      }
    } else if (name === "Scene_Skill") {
      for (
        let index = 0;
        index < current._skillTypeWindow.maxItems();
        index++
      ) {
        current._skillTypeWindow.select(index);
        await press("ok");
        await everyRow(current._itemWindow);
        await press("cancel");
      }
    } else if (name === "Scene_Equip") {
      if (await choose(current._commandWindow, "equip")) {
        for (let index = 0; index < current._slotWindow.maxItems(); index++) {
          current._slotWindow.select(index);
          await press("ok");
          await everyRow(current._itemWindow);
          await press("cancel");
        }
      }
    } else if (name === "Scene_Options") {
      await everyRow(current._optionsWindow);
    } else {
      for (const list of activeWindows()) await everyRow(list);
    }
    await frames(10);
  }

  // ---------------------------------------------------------------- stops

  const stops = {};

  stops.title = async () => {
    const ready = await until(
      () =>
        scene() && !/Boot/.test(sceneName()) && !SceneManager.isSceneChanging(),
      60,
    );
    if (!ready)
      return { status: "failed", note: "The game did not finish starting." };
    await settle();
    return { status: "done", note: sceneName() };
  };

  stops["new-game"] = async () => {
    if (isScene("Scene_Title") && scene()._commandWindow) {
      await until(
        () => scene()._commandWindow.isOpen() && scene()._commandWindow.active,
        20,
      );
      await choose(scene()._commandWindow, "newGame");
    } else if (!isScene("Scene_Map")) {
      await press("ok");
    }
    const ok = await until(() => isScene("Scene_Map"), 30);
    await settle();
    return ok
      ? { status: "done" }
      : {
          status: "failed",
          note: `New Game led to ${sceneName()}, not a map.`,
        };
  };

  /** Plays through what the game shows by itself: messages, the first
   * choice of each list, inputs and battles, until the player can move. */
  /** Runs a part of the tour with the game four times as fast. */
  async function fast(run) {
    const speed = state.speed;
    state.speed = 4;
    try {
      return await run();
    } finally {
      state.speed = speed;
    }
  }

  function play(seconds, quiet = 60) {
    return fast(() => playing(seconds, quiet));
  }

  async function playing(seconds, quiet) {
    const deadline = Date.now() + seconds * 1000;
    const first = state.messages;
    let calm = 0;
    let idle = 0;
    while (Date.now() < deadline) {
      const messages = state.messages - first;
      if (state.crashed) throw new Crash(state.crashed);
      visited();
      const name = sceneName();
      if (SceneManager.isSceneChanging()) {
        await frames(2);
      } else if (name === "Scene_Battle") {
        await battle(30);
      } else if (name === "Scene_Name") {
        scene().onInputOk();
        await frames(10);
      } else if (name === "Scene_Gameover") {
        return {
          messages,
          calm: false,
          note: "Play ended in a game over.",
        };
      } else if (window.$gameMessage && $gameMessage.isBusy()) {
        calm = 0;
        const list = activeWindows().find((window_) =>
          /Choice/.test(window_.constructor.name),
        );
        if (list) list.select(0);
        await press("ok");
      } else if (
        name === "Scene_Map" &&
        !$gameMap.isEventRunning() &&
        !$gamePlayer.isTransferring()
      ) {
        if (++calm >= quiet) return { messages, calm: true };
        await flush();
        await frames(1);
      } else if (name !== "Scene_Map") {
        // A scene a plugin opened, such as a tutorial page.
        await frames(30);
        await press("ok");
        await frames(10);
        if (sceneName() === name) await press("cancel");
      } else {
        // An event may wait for OK without a message, such as over a
        // picture; OK starts nothing while an event runs.
        if (++idle % 30 === 0) await press("ok");
        calm = 0;
        await frames(2);
      }
    }
    return { messages: state.messages - first, calm: false };
  }

  stops.opening = async (options) => {
    const result = await play(options.opening || 120);
    if (result.calm)
      return {
        status: "done",
        note: `${result.messages} messages until the player could move.`,
      };
    // The rest of the tour needs the map to itself, as when the player can
    // move, so it ends the event still running.
    if (isScene("Scene_Map")) {
      $gameMessage.clear();
      $gameMap._interpreter.clear();
      await frames(10);
    }
    return {
      status: "done",
      note:
        result.note ||
        `${result.messages} messages, then the tour ended the opening event to go on.`,
    };
  };

  /** Starts a battle with the engine's own Battle Processing command, which
   * plugins extend. */
  function startBattle(troopId) {
    const interpreter = new Game_Interpreter();
    interpreter.setup(
      [
        { code: 301, indent: 0, parameters: [0, troopId, true, true] },
        { code: 0, indent: 0, parameters: [] },
      ],
      0,
    );
    interpreter.executeCommand();
  }

  /** One of every item, weapon and armor, and each actor's skill types'
   * skills, so every description draws once; only in memory and the tour's
   * own save. */
  function stock() {
    if (!$gameParty.members().length && $dataActors[1]) $gameParty.addActor(1);
    for (const [list, amount] of [
      [$dataItems, 1],
      [$dataWeapons, 1],
      [$dataArmors, 1],
    ])
      for (const item of list)
        if (item && item.name && $gameParty.numItems(item) < 1)
          $gameParty.gainItem(item, amount);
    for (const actor of $gameParty.members()) {
      // MV lists an actor's skill types only as added ones.
      const types = new Set(
        actor.skillTypes ? actor.skillTypes() : actor.addedSkillTypes(),
      );
      for (const skill of $dataSkills)
        if (
          skill &&
          skill.name &&
          types.has(skill.stypeId) &&
          !actor.isLearnedSkill(skill.id)
        )
          actor.learnSkill(skill.id);
    }
  }

  stops.menu = async () => {
    stock();
    SceneManager.push(Scene_Menu);
    if (
      !(await until(
        () => isScene("Scene_Menu") && scene()._commandWindow.active,
        20,
      ))
    )
      return { status: "failed", note: "The menu did not open." };
    await settle();
    const opened = [];
    const symbols = scene()
      ._commandWindow._list.map((command, index) => ({ ...command, index }))
      .filter(
        (command) =>
          command.enabled &&
          !["save", "gameEnd", "formation"].includes(command.symbol),
      );
    for (const command of symbols) {
      if (!isScene("Scene_Menu")) {
        await leave("Scene_Menu");
        if (!isScene("Scene_Menu")) {
          SceneManager.push(Scene_Menu);
          await settle();
        }
      }
      const menu = scene();
      menu._commandWindow.activate();
      menu._commandWindow.select(command.index);
      await press("ok");
      await frames(4);
      if (
        isScene("Scene_Menu") &&
        menu._statusWindow &&
        menu._statusWindow.active
      ) {
        menu._statusWindow.select(0);
        await press("ok");
      }
      if (
        !(await until(
          () => !isScene("Scene_Menu") && !SceneManager.isSceneChanging(),
          5,
        ))
      )
        continue;
      await settle();
      const name = sceneName();
      opened.push(name);
      await exploreScene(name);
      await leave("Scene_Menu");
    }
    await leave("Scene_Map");
    return { status: "done", note: [...new Set(opened)].join(", ") };
  };

  stops["save-load"] = async () => {
    if (!$gameSystem.isSaveEnabled()) $gameSystem.enableSave();
    const at = { map: $gameMap.mapId(), x: $gamePlayer.x, y: $gamePlayer.y };
    SceneManager.push(Scene_Save);
    if (
      !(await until(
        () => isScene("Scene_Save") && scene()._listWindow.active,
        20,
      ))
    )
      return { status: "failed", note: "The save screen did not open." };
    await settle();
    const list = scene()._listWindow;
    if (list.selectSavefile) list.selectSavefile(1);
    else list.select(0);
    await press("ok");
    if (!(await until(() => isScene("Scene_Map"), 20)))
      return { status: "failed", note: "Saving did not return to the map." };
    await settle();
    SceneManager.push(Scene_GameEnd);
    await until(
      () => isScene("Scene_GameEnd") && scene()._commandWindow.active,
      20,
    );
    await settle();
    await choose(scene()._commandWindow, "toTitle");
    if (
      !(await until(
        () =>
          isScene("Scene_Title") &&
          scene()._commandWindow &&
          scene()._commandWindow.active,
        30,
      ))
    )
      return {
        status: "failed",
        note: "Game End did not return to the title.",
      };
    await settle();
    const title = scene()._commandWindow;
    if (!(await choose(title, "continue")))
      return { status: "failed", note: "The title has no Continue." };
    if (
      !(await until(
        () => isScene("Scene_Load") && scene()._listWindow.active,
        20,
      ))
    )
      return {
        status: "failed",
        note:
          "The load screen did not open from the title's Continue" +
          (DataManager.isAnySavefileExists()
            ? ` (${title._list.map((command) => command.symbol + (command.enabled ? "" : " off")).join(", ")}).`
            : ", because the game found no save after saving."),
      };
    await settle();
    const load = scene()._listWindow;
    if (load.selectSavefile) load.selectSavefile(1);
    else load.select(0);
    await press("ok");
    if (!(await until(() => isScene("Scene_Map"), 30)))
      return { status: "failed", note: "Loading did not reach the map." };
    await settle();
    const back =
      $gameMap.mapId() === at.map &&
      $gamePlayer.x === at.x &&
      $gamePlayer.y === at.y;
    return back
      ? { status: "done" }
      : {
          status: "failed",
          note: "The loaded game is not where it was saved.",
        };
  };

  stops.shop = async () => {
    const goods = [];
    for (const [type, list] of [
      [0, $dataItems],
      [1, $dataWeapons],
      [2, $dataArmors],
    ])
      for (const item of list)
        if (item && item.name) goods.push([type, item.id, 0, 0]);
    SceneManager.push(Scene_Shop);
    SceneManager.prepareNextScene(goods, false);
    if (
      !(await until(() => isScene("Scene_Shop") && activeWindows().length, 20))
    )
      return { status: "failed", note: "The shop did not open." };
    await settle();
    // A plugin may open the shop on its list of goods.
    if (
      scene()._buyWindow.active ||
      (await choose(scene()._commandWindow, "buy"))
    ) {
      await frames(4);
      await everyRow(scene()._buyWindow);
      await press("cancel");
    }
    await frames(4);
    if (
      isScene("Scene_Shop") &&
      scene()._commandWindow.active &&
      (await choose(scene()._commandWindow, "sell"))
    ) {
      const categories = scene()._categoryWindow;
      for (
        let index = 0;
        categories && index < categories.maxItems();
        index++
      ) {
        categories.select(index);
        await press("ok");
        await everyRow(scene()._sellWindow);
        await press("cancel");
      }
    }
    await leave("Scene_Map");
    return { status: "done", note: `${goods.length} goods` };
  };

  /** Fights with the first command of each window, or a skill now and then,
   * until the battle ends or time runs out. */
  function battle(seconds) {
    return fast(() => fighting(seconds));
  }

  async function fighting(seconds) {
    const deadline = Date.now() + seconds * 1000;
    let turn = 0;
    while (isScene("Scene_Battle") || SceneManager.isSceneChanging()) {
      if (state.crashed) throw new Crash(state.crashed);
      if (Date.now() > deadline) {
        BattleManager.abort();
        await until(() => !isScene("Scene_Battle"), 15);
        return false;
      }
      const current = scene();
      if (!current || !current._partyCommandWindow) {
        await frames(4);
        continue;
      }
      visited();
      if (current._partyCommandWindow.active) {
        await choose(current._partyCommandWindow, "fight");
      } else if (current._actorCommandWindow.active) {
        turn++;
        const skill =
          turn % 3 === 0 &&
          current._actorCommandWindow.findSymbol("skill") >= 0;
        if (skill) {
          await choose(current._actorCommandWindow, "skill");
          await frames(4);
          if (current._skillWindow.active) {
            await everyRow(current._skillWindow);
            const usable = [
              ...Array(current._skillWindow.maxItems()).keys(),
            ].find((index) =>
              current._skillWindow.isEnabled(
                // MV's skill list has no itemAt.
                current._skillWindow.itemAt
                  ? current._skillWindow.itemAt(index)
                  : current._skillWindow._data[index],
              ),
            );
            if (usable === undefined) await press("cancel");
            else {
              current._skillWindow.select(usable);
              await press("ok");
            }
          }
        } else if (!(await choose(current._actorCommandWindow, "attack")))
          await press("ok");
      } else if (activeWindows().length) {
        await press("ok");
      } else {
        // Battle text and cut-ins may wait for OK, as messages do.
        await press("ok");
        await frames(4);
      }
    }
    return true;
  }

  /** A battle the tour starts on a map that names no background shows one
   * the game ships, or none, never the engine's default the game may lack. */
  function backdrop(options) {
    state.backdrop = options.battlebacks || ["", ""];
  }

  stops.battle = async (options) => {
    const troop = $dataTroops.find(
      (row) =>
        row &&
        row.members &&
        row.members.some(
          (member) =>
            $dataEnemies[member.enemyId] && $dataEnemies[member.enemyId].name,
        ),
    );
    if (!troop)
      return { status: "skipped", note: "The game has no troop with enemies." };
    if (!$gameParty.members().length && $dataActors[1]) $gameParty.addActor(1);
    backdrop(options);
    startBattle(troop.id);
    if (!(await until(() => isScene("Scene_Battle"), 20)))
      return { status: "failed", note: "The battle did not start." };
    await settle();
    const ended = await battle(options.battle || 60);
    state.backdrop = null;
    await settle();
    return {
      status: "done",
      note: `Troop ${troop.id}${ended ? "" : ", stopped after the time allowed"}`,
    };
  };

  stops.screens = async (config) => {
    const opened = [];
    const classes = Object.getOwnPropertyNames(window).filter(
      (name) =>
        /^Scene_/.test(name) &&
        !ENGINE_SCENES.has(name) &&
        typeof window[name] === "function" &&
        window[name].prototype instanceof Scene_Base,
    );
    // A screen other screens build on, such as a custom menu framework's,
    // shows nothing of its own.
    // A screen that stopped the game before is left out when it starts again.
    const names = classes.filter(
      (name) =>
        !state.scenes.has(name) &&
        !(config.skip || []).includes(name) &&
        !classes.some(
          (other) =>
            other !== name && window[other].prototype instanceof window[name],
        ),
    );
    for (const name of names) {
      const stop = state.stop;
      // A screen that fails keeps its name here, so its errors and a crash
      // name it.
      doing(`screen ${name}`);
      SceneManager.push(window[name]);
      if (await until(() => isScene(name), 10)) {
        await settle();
        await exploreScene(name);
        opened.push(name);
      }
      doing(stop);
      await leave("Scene_Map");
    }
    return {
      status: "done",
      note: opened.length
        ? opened.join(", ")
        : "No plugin defines a screen of its own.",
      screens: names,
    };
  };

  stops.end = async () => {
    SceneManager.push(Scene_GameEnd);
    await until(
      () => isScene("Scene_GameEnd") && scene()._commandWindow.active,
      20,
    );
    await choose(scene()._commandWindow, "toTitle");
    const ok = await until(() => isScene("Scene_Title"), 30);
    await settle();
    return ok
      ? { status: "done" }
      : { status: "failed", note: "Game End did not return to the title." };
  };

  /** A stop the assistant asked for. */
  async function custom(step, options) {
    if (!isScene("Scene_Map")) await leave("Scene_Map");
    for (const [id, value] of Object.entries(step.switches || {}))
      $gameSwitches.setValue(Number(id), !!value);
    for (const [id, value] of Object.entries(step.variables || {}))
      $gameVariables.setValue(Number(id), value);
    if (step.do === "map") {
      $gamePlayer.reserveTransfer(step.map, step.x || 0, step.y || 0, 2, 0);
      await until(
        () =>
          isScene("Scene_Map") &&
          $gameMap.mapId() === step.map &&
          !$gamePlayer.isTransferring(),
        30,
      );
    } else if (step.do === "event") {
      if (step.map && $gameMap.mapId() !== step.map) {
        $gamePlayer.reserveTransfer(step.map, step.x || 0, step.y || 0, 2, 0);
        await until(
          () =>
            isScene("Scene_Map") &&
            $gameMap.mapId() === step.map &&
            !$gamePlayer.isTransferring(),
          30,
        );
      }
      const event = $gameMap.event(step.event);
      if (!event)
        return {
          status: "failed",
          note: `Map ${$gameMap.mapId()} has no event ${step.event}.`,
        };
      event.start();
    } else if (step.do === "common-event") {
      $gameTemp.reserveCommonEvent(step.id);
    } else if (step.do === "battle") {
      backdrop(options);
      startBattle(step.troop);
      await until(() => isScene("Scene_Battle"), 20);
      await battle(options.battle || 60);
      state.backdrop = null;
    } else if (step.do === "scene") {
      if (typeof window[step.scene] !== "function")
        return { status: "failed", note: `The game has no ${step.scene}.` };
      SceneManager.push(window[step.scene]);
      if (await until(() => isScene(step.scene), 10)) {
        await settle();
        await exploreScene(step.scene);
      }
      await leave("Scene_Map");
    } else if (step.do === "script") {
      await new Function(step.script)();
    } else {
      return { status: "failed", note: `Unknown stop: ${step.do}` };
    }
    const result = await play(step.seconds || 60, 30);
    return { status: "done", note: `${result.messages} messages` };
  }

  // ---------------------------------------------------------------- tour

  async function tour(config) {
    const plan = config.stops;
    // After a crash the page starts over; later stops need a game running.
    const resume = config.from || 0;
    if (resume && !["title", "new-game"].includes(plan[resume]?.id)) {
      doing("resume");
      try {
        await stops.title();
        await stops["new-game"]();
      } catch (problem) {
        send("stop", {
          index: resume,
          id: plan[resume].id,
          status: "failed",
          note: `The game could not start again: ${problem.message}`,
          crashed: true,
        });
        return;
      }
    }
    for (let index = resume; index < plan.length; index++) {
      const step = plan[index];
      doing(step.id);
      send("start", { index, id: step.id });
      const started = Date.now();
      let result;
      try {
        if (state.crashed) throw new Crash(state.crashed);
        result = step.do
          ? await custom(step, config)
          : await stops[step.id](config);
      } catch (problem) {
        result = {
          status: "failed",
          note:
            problem instanceof Crash
              ? `The game stopped: ${problem.message}`
              : `The stop failed: ${problem.message}`,
          crashed: problem instanceof Crash,
        };
        if (!(problem instanceof Crash))
          error("harness", `${step.id}: ${problem.message}`, problem.stack);
      }
      try {
        await flush();
      } catch {
        // The stop's result stands without its last capture.
      }
      send("stop", {
        index,
        id: step.id,
        seconds: (Date.now() - started) / 1000,
        ...result,
      });
      if (result.crashed) return;
      // Every later stop starts on the map.
      if (!["title", "new-game", "end"].includes(step.id))
        try {
          if (!isScene("Scene_Map")) await leave("Scene_Map");
        } catch (problem) {
          if (problem instanceof Crash) return;
        }
    }
    send("done", {});
  }

  window.__playtest = {
    /** Records what is on screen now, as the tour does before it moves. */
    look: flush,
    /** What the tour is doing, which the launcher's --trace writes. */
    debug() {
      let windows = [];
      try {
        windows = activeWindows().map((window_) => window_.constructor.name);
      } catch {
        // No scene yet.
      }
      return {
        stop: state.stop,
        scene: sceneName(),
        windows,
        message: !!(window.$gameMessage && $gameMessage.isBusy()),
        event: !!(
          window.$gameMap &&
          $gameMap.isEventRunning &&
          $gameMap.isEventRunning()
        ),
        battle: window.BattleManager ? BattleManager._phase : "",
        busy:
          window.BattleManager && BattleManager._logWindow
            ? [
                BattleManager._logWindow.isBusy(),
                BattleManager._spriteset && BattleManager._spriteset.isBusy(),
                BattleManager._spriteset &&
                  BattleManager._spriteset.isAnimationPlaying(),
                !!BattleManager._subject,
                BattleManager._logWindow._waitMode,
                BattleManager._logWindow._waitCount,
                BattleManager._logWindow._methods
                  .slice(0, 3)
                  .map((method) => method.name),
                !!BattleManager._logWindow.parent,
                BattleManager._logWindow.update ===
                  Window_BattleLog.prototype.update,
              ]
            : null,
      };
    },
  };
})();
