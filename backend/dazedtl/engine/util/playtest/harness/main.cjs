// Plays an RPG Maker MV/MZ game in a hidden window for the release playtest.
// rpgmaker_window/launcher.cjs runs the game and page.js plays the tour;
// this writes runtime.json and its captures to the output folder. Progress
// goes to stdout as one JSON object a line.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { launch } = require("../../rpgmaker_window/launcher.cjs");

const SCHEMA = "rpgmaker-playtest-runtime-v1";

launch((run) => {
  const plan = run.plan;
  const captures = path.join(run.out, "captures");
  fs.mkdirSync(captures, { recursive: true });
  const report = {
    schema: SCHEMA,
    started_at: new Date().toISOString(),
    resolution: run.size,
    stops: plan.stops.map((stop) => ({
      id: stop.id,
      ...(stop.title && { title: stop.title }),
      status: "not-reached",
    })),
    errors: [],
    japanese: [],
    overflow: [],
    scenes: [],
    captures: [],
    messages: { shown: 0, choices: 0, sources: {} },
    battle: 0,
    crashes: [],
  };
  let finished = false;
  let current = -1;
  // Errors already recorded, across reloads of the page.
  const recorded = new Set();
  // Where the next window starts, and the screens that stopped the game.
  let from = 0;
  const skip = [];

  function take(type, value) {
    if (["error", "japanese", "overflow"].includes(type)) {
      const key = JSON.stringify([
        type,
        value.message || value.text,
        value.window || "",
        value.source?.file || "",
        value.data?.pointer || "",
      ]);
      if (recorded.has(key)) return;
      recorded.add(key);
    }
    if (type === "start") {
      current = value.index;
      // A stop played again after a crash starts afresh.
      const { id, title, stopped } = report.stops[value.index];
      report.stops[value.index] = {
        id,
        ...(title && { title }),
        status: "running",
        ...(stopped && { stopped }),
      };
      run.say({
        progress: "stop",
        index: value.index,
        id: value.id,
        total: plan.stops.length,
      });
    } else if (type === "stop") {
      const index = value.index ?? current;
      if (report.stops[index]) {
        delete value.index;
        Object.assign(report.stops[index], value);
      }
      if (value.crashed) {
        report.crashes.push({ stop: value.id, note: value.note });
        run.restart(value.note);
      }
    } else if (type === "done") {
      finished = true;
    } else if (type === "capture") {
      const file = `${run.fileName(value.name)}.jpg`;
      const data = String(value.data || "").split(",", 2)[1];
      if (data) {
        fs.writeFileSync(path.join(captures, file), Buffer.from(data, "base64"));
        report.captures.push({
          name: value.name,
          file: `captures/${file}`,
          stop: value.stop,
          scene: value.scene,
        });
      }
    } else if (type === "error") report.errors.push(value);
    else if (type === "japanese") report.japanese.push(value);
    else if (type === "overflow") report.overflow.push(value);
    else if (type === "scene") report.scenes.push(value);
    else if (type === "message") {
      report.messages.shown++;
      if (value.data) {
        const key = `${value.data.file}#${value.data.pointer}`;
        report.messages.sources[key] = (report.messages.sources[key] || 0) + 1;
      }
    } else if (type === "choice") report.messages.choices++;
    else if (type === "battle") report.battle++;
  }

  /** Marks the stop that was running as stopped by `note`. */
  function stopped(note) {
    const stop = report.stops[current];
    if (stop && stop.status === "running")
      Object.assign(stop, { status: "failed", note, crashed: true });
    if (!report.crashes.some((row) => row.note === note && row.stop === stop?.id))
      report.crashes.push({ stop: stop?.id, note });
    run.say({ progress: "crash", index: current, note });
  }

  return {
    page: path.join(__dirname, "page.js"),
    plan: () => ({ ...plan, from, skip }),
    take,
    resized(size) {
      report.resolution = size;
    },
    trace: "window.__playtest && window.__playtest.debug()",
    recover(note, step) {
      // The screens stop goes on without a screen that stopped the game.
      const screen =
        report.stops[current]?.id === "screens" && step.startsWith("screen ")
          ? step.slice(7)
          : "";
      if (screen) {
        skip.push(screen);
        report.stops[current].stopped = [...skip];
      }
      stopped(note);
      from = Math.max(from, screen ? current : current + 1);
      if (from >= plan.stops.length) finished = true;
      return !finished;
    },
    finish({ note, timedOut }) {
      if (note) stopped(note);
      if (timedOut)
        for (const stop of report.stops)
          if (stop.status === "running")
            Object.assign(stop, {
              status: "failed",
              note: "The playtest ran out of time.",
            });
      report.finished_at = new Date().toISOString();
      report.complete = finished;
      fs.writeFileSync(
        path.join(run.out, "runtime.json"),
        JSON.stringify(report, null, 1),
      );
      run.say({ progress: "done", complete: finished });
    },
  };
});
