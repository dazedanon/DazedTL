// Opens an RPG Maker MV/MZ game's interface screens one by one and captures
// each, with every item, weapon, armor and skill in the party's hands.
//
// Loaded after the game's own scripts by capture.cjs. Every call to
// Bitmap#drawText is measured with the game's fonts, so each capture lists the
// text it shows and which of it the game squeezed into less space than it
// needs or drew past its window.
(() => {
  "use strict";

  const api = window.dazedtlCapture;
  const plan = api.plan();
  const drawn = [];
  let recording = false;

  // Lists longer than this many pages, and troops past this many, are left out.
  const PAGE_LIMIT = 40;
  const TROOP_LIMIT = 40;
  // How long one screen may take to open, in frames.
  const OPEN_FRAMES = 900;

  window.addEventListener("error", (event) =>
    api.error((event.error && event.error.stack) || event.message || String(event.error)),
  );
  window.addEventListener("unhandledrejection", (event) =>
    api.error((event.reason && event.reason.stack) || String(event.reason)),
  );

  const frames = (count) =>
    new Promise((resolve) => {
      let left = count;
      const tick = () => (--left <= 0 ? resolve() : requestAnimationFrame(tick));
      requestAnimationFrame(tick);
    });

  async function until(test, limit = OPEN_FRAMES) {
    for (let frame = 0; frame < limit; frame++) {
      try {
        if (test()) return true;
      } catch {
        // Not ready yet.
      }
      await frames(1);
    }
    return false;
  }

  const scene = () => SceneManager._scene;
  const started = (current) => !!current && (current._started || current._active);
  const isMZ = () => window.Utils && Utils.RPGMAKER_NAME === "MZ";

  function hookDrawing() {
    const drawText = Bitmap.prototype.drawText;
    Bitmap.prototype.drawText = function (text, x, y, maxWidth, lineHeight, align) {
      if (recording && text !== undefined && text !== null && String(text) !== "") {
        const entry = {
          bitmap: this,
          text: String(text),
          x: Number(x) || 0,
          y: Number(y) || 0,
          maxWidth: Number(maxWidth) || 0,
          measured: this.measureTextWidth(String(text)),
          align: align || "left",
        };
        // MV's message text draws one character at a time; each joins the
        // run it continues, so a choice reads as its whole text.
        const last = drawn[drawn.length - 1];
        if (
          entry.text.length === 1 &&
          last &&
          last.run &&
          last.bitmap === this &&
          last.y === entry.y &&
          Math.abs(last.x + last.measured - entry.x) < 2
        ) {
          last.text += entry.text;
          last.measured += entry.measured;
          last.maxWidth = 0;
        } else {
          if (entry.text.length === 1) entry.run = true;
          if (entry.text.trim()) drawn.push(entry);
        }
      }
      return drawText.apply(this, arguments);
    };
  }

  /** Every window the scene shows, wherever it sits in the scene's tree. */
  function windows(root, found = []) {
    for (const child of root.children || []) {
      if (child instanceof Window) found.push(child);
      windows(child, found);
    }
    return found;
  }

  /** The text drawn on the current screen, and what the game squeezed or cut. */
  function labels() {
    const shown = new Map();
    for (const window of windows(scene())) {
      if (!window.visible || !window.contents || window.openness <= 0) continue;
      const padding = window.padding || 0;
      for (const entry of drawn) {
        if (entry.bitmap !== window.contents) continue;
        const width = entry.maxWidth > 0 ? Math.min(entry.measured, entry.maxWidth) : entry.measured;
        const start = entry.align === "center" ? entry.x + (entry.maxWidth - width) / 2
          : entry.align === "right" ? entry.x + entry.maxWidth - width : entry.x;
        const right = window.x + padding + start + width;
        const label = {
          text: entry.text,
          window: window.constructor.name,
          ...(entry.maxWidth > 0 && entry.measured > entry.maxWidth + 0.5
            ? { squeezed: Math.round((entry.maxWidth / entry.measured) * 100) / 100 }
            : {}),
          ...(start + width > window.contents.width + 0.5 || start < -0.5 || right > Graphics.width + 0.5
            ? { clipped: true }
            : {}),
        };
        const key = `${label.window}\u0000${label.text}`;
        const earlier = shown.get(key);
        if (!earlier || label.squeezed || label.clipped) shown.set(key, label);
      }
    }
    return [...shown.values()];
  }

  async function snap(name, title, extra = {}) {
    await frames(3);
    await api.capture(name, { title, labels: labels(), ...extra });
  }

  async function go(SceneClass, ...prepare) {
    drawn.length = 0;
    SceneManager.goto(SceneClass);
    if (prepare.length) SceneManager.prepareNextScene(...prepare);
    const open = await until(
      () => scene() instanceof SceneClass && started(scene()) && !SceneManager.isSceneChanging(),
    );
    if (!open) {
      const shown = scene() ? scene().constructor.name : "nothing";
      throw new Error(`${SceneClass.name} did not open; the game showed ${shown}.`);
    }
    await frames(20);
    return scene();
  }

  /** Every page of a list, each captured with only that page's text drawn. */
  async function pages(name, title, list) {
    const rows = Math.max(1, Math.ceil(list.maxItems() / Math.max(1, list.maxCols())));
    const step = Math.max(1, list.maxPageRows());
    let page = 0;
    for (let top = 0; top < rows && page < PAGE_LIMIT; top += step) {
      drawn.length = 0;
      list.setTopRow(top);
      list.refresh();
      page += 1;
      await snap(`${name}-${String(page).padStart(2, "0")}`, rows > step ? `${title}, page ${page}` : title);
    }
  }

  /** Runs one setup step, reporting it instead of stopping when the game refuses it. */
  function attempt(step, action) {
    try {
      action();
    } catch (error) {
      api.skip(step, (error && error.message) || String(error));
    }
  }

  /** The game's starting party, holding one of everything, its leader knowing
   * every skill. Other actors stay out: plugins often assume who can join. */
  function setUpParty() {
    attempt("new game", () => DataManager.setupNewGame());
    const named = (list) => list.filter((entry) => entry && entry.name && entry.name.trim());
    attempt("items", () => {
      for (const item of [...named($dataItems), ...named($dataWeapons), ...named($dataArmors)])
        $gameParty.gainItem(item, 1);
    });
    attempt("skills", () => {
      const types = [...new Set(named($dataSkills).map((skill) => skill.stypeId).filter((id) => id > 0))];
      Game_Actor.prototype.skillTypes = () => types;
      const leader = $gameParty.members()[0];
      if (leader) for (const skill of named($dataSkills)) leader.learnSkill(skill.id);
    });
  }

  async function title() {
    await go(Scene_Title);
    await until(() => scene()._commandWindow.isOpen());
    await frames(60);
    await snap("title", "Title");
  }

  async function menu() {
    await go(Scene_Menu);
    await snap("menu", "Menu");
  }

  async function items() {
    const current = await go(Scene_Item);
    const categories = current._categoryWindow;
    const list = current._itemWindow;
    for (let index = 0; index < categories.maxItems(); index++) {
      categories.select(index);
      list.setCategory(categories.currentSymbol());
      await pages(`items-${index + 1}`, `Items: ${categories.commandName(index)}`, list);
    }
  }

  async function skills() {
    const actor = $gameParty.members()[0];
    if (!actor) return;
    $gameParty.setMenuActor(actor);
    const current = await go(Scene_Skill);
    const types = current._skillTypeWindow;
    const list = current._itemWindow;
    for (let index = 0; index < types.maxItems(); index++) {
      types.select(index);
      list.setStypeId(types.currentExt());
      await pages(`skills-${index + 1}`, `Skills: ${types.commandName(index)}`, list);
    }
  }

  async function equipment() {
    for (const [index, actor] of $gameParty.members().slice(0, 8).entries()) {
      $gameParty.setMenuActor(actor);
      const current = await go(Scene_Equip);
      await snap(`equip-${index + 1}`, `Equipment: ${actor.name()}`);
      if (index > 0) continue;
      // The lists a slot offers are narrower than the item screen's; MZ shows
      // one only once its slot is chosen.
      const slots = current._slotWindow;
      for (let slot = 0; slot < Math.min(slots.maxItems(), 2); slot++) {
        slots.select(slot);
        current._itemWindow.setSlotId(slot);
        current.onSlotOk();
        await frames(4);
        await pages(`equip-list-${slot + 1}`, `Equipment list: ${actor.name()} slot ${slot + 1}`, current._itemWindow);
        current.onItemCancel();
        await frames(4);
      }
    }
  }

  async function status() {
    for (const [index, actor] of $gameParty.members().slice(0, 8).entries()) {
      $gameParty.setMenuActor(actor);
      await go(Scene_Status);
      await snap(`status-${index + 1}`, `Status: ${actor.name()}`);
    }
  }

  async function shop() {
    const goods = [];
    const add = (list, type) => {
      for (const entry of list) if (entry && entry.name && entry.name.trim()) goods.push([type, entry.id, 0, 0]);
    };
    add($dataItems, 0);
    add($dataWeapons, 1);
    add($dataArmors, 2);
    const current = await go(Scene_Shop, goods, false);
    await snap("shop", "Shop");
    current.commandBuy();
    await frames(10);
    await pages("shop-buy", "Shop: Buy", current._buyWindow);
  }

  async function options() {
    const current = await go(Scene_Options);
    await pages("options", "Options", current._optionsWindow);
    await go(Scene_GameEnd);
    await snap("game-end", "Game End");
  }

  async function battles() {
    // Battles open straight at the commands: no start messages or troop events.
    BattleManager.displayStartMessages = () => {};
    Game_Troop.prototype.setupBattleEvent = () => {};
    // Each troop that shows an enemy name no earlier troop showed.
    const seen = new Set();
    const troops = $dataTroops.filter((troop) => {
      const names = (troop && troop.members ? troop.members : [])
        .map((member) => $dataEnemies[member.enemyId])
        .filter((enemy) => enemy && enemy.name)
        .map((enemy) => enemy.name);
      const fresh = names.some((name) => !seen.has(name));
      names.forEach((name) => seen.add(name));
      return fresh;
    });
    for (const [index, troop] of troops.slice(0, TROOP_LIMIT).entries()) {
      BattleManager.setup(troop.id, true, true);
      const current = await go(Scene_Battle);
      const ready = await until(() => current._partyCommandWindow.active || current._actorCommandWindow.active);
      if (!ready) throw new Error(`The battle with ${troop.name} did not ask for commands.`);
      await frames(20);
      if (index === 0) {
        await snap("battle-party", "Battle: party commands");
        if (current._partyCommandWindow.active) current.commandFight();
        await until(() => current._actorCommandWindow.active);
        await frames(10);
        await snap("battle-actor", "Battle: actor commands");
      }
      drawn.length = 0;
      if (current.startEnemySelection) current.startEnemySelection();
      else current.selectEnemySelection();
      await frames(10);
      await snap(`battle-enemies-${String(index + 1).padStart(2, "0")}`, `Battle: enemies ${index + 1}`);
    }
  }

  function choiceScene() {
    if (isMZ()) {
      return class Scene_DazedChoices extends Scene_Message {
        create() {
          super.create();
          this.createWindowLayer();
          this.createAllWindows();
        }
      };
    }
    function Scene_DazedChoices() {
      this.initialize(...arguments);
    }
    Scene_DazedChoices.prototype = Object.create(Scene_Base.prototype);
    Scene_DazedChoices.prototype.constructor = Scene_DazedChoices;
    Scene_DazedChoices.prototype.create = function () {
      Scene_Base.prototype.create.call(this);
      this.createWindowLayer();
      this._messageWindow = new Window_Message();
      this.addWindow(this._messageWindow);
      this._messageWindow.subWindows().forEach((window) => this.addWindow(window));
    };
    return Scene_DazedChoices;
  }

  /** Each choice list, captured when the game cuts any of it off, or always
   * when the plan asks for every one. */
  async function choices() {
    if (!plan.choices.length) return;
    const current = await go(choiceScene());
    const list = () => current._choiceListWindow || current._messageWindow._choiceWindow;
    let shown = 0;
    for (const [index, entry] of plan.choices.entries()) {
      drawn.length = 0;
      $gameMessage.clear();
      $gameMessage.setChoices(entry.choices, entry.defaultType ?? 0, entry.cancelType ?? -1);
      $gameMessage.setChoiceBackground(entry.background ?? 0);
      $gameMessage.setChoicePositionType(entry.positionType ?? 2);
      if (!(await until(() => list().isOpen(), 240))) {
        api.skip(`choices ${index + 1}`, "The choice list did not open.");
        continue;
      }
      await frames(4);
      const found = labels();
      if (plan.allChoices || found.some((label) => label.squeezed || label.clipped)) {
        shown += 1;
        await api.capture(`choices-${String(index + 1).padStart(3, "0")}`, {
          title: "Choices",
          key: entry.key,
          labels: found,
        });
      }
      list().deactivate();
      list().close();
      $gameMessage.clear();
      await until(() => list().isClosed(), 120);
    }
    return shown;
  }

  const SCREENS = { title, menu, items, skills, equipment, status, shop, options, battles, choices };

  async function run() {
    // MZ pauses scenes while the page lacks focus, which a hidden window never has.
    await until(() => window.SceneManager, 3600);
    SceneManager.isGameActive = () => true;
    const booted = await until(
      () =>
        window.Bitmap &&
        window.SceneManager &&
        DataManager.isDatabaseLoaded() &&
        started(scene()) &&
        !(scene() instanceof Scene_Boot),
      3600,
    );
    if (!booted) {
      api.error("The game did not finish starting.");
      return;
    }
    hookDrawing();
    await api.size(Graphics.width, Graphics.height);
    await frames(10);
    setUpParty();
    recording = true;
    for (const [name, screen] of Object.entries(SCREENS)) {
      if (plan.screens && !plan.screens.includes(name)) continue;
      try {
        await screen();
      } catch (error) {
        api.skip(name, (error && error.message) || String(error));
      }
    }
  }

  run()
    .catch((error) => api.error((error && error.stack) || String(error)))
    .finally(() =>
      api.done(
        window.Graphics
          ? { engine: isMZ() ? "MZ" : "MV", width: Graphics.width, height: Graphics.height }
          : null,
      ),
    );
})();
