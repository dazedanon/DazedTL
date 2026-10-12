// Captures an RPG Maker MV/MZ game's interface screens without changing it.
//
// rpgmaker_window/launcher.cjs runs the game, serving corrected data files in
// place of the game's own when the plan has them; harness.js opens each
// screen, and every capture is written to the output folder with the text
// the game drew on it, listed in screens.json. A screen that stops the game
// is left out, and the capture goes on with the next in a new window.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { launch } = require("../rpgmaker_window/launcher.cjs");

launch((run) => {
  const result = { game: null, screens: [], skipped: [], errors: [] };
  // Screens opened in an earlier window, which the next one leaves out.
  const begun = [];
  const error = (message) => {
    if (result.errors.length < 50)
      result.errors.push(String(message).slice(0, 2000));
  };
  return {
    page: path.join(__dirname, "harness.js"),
    plan: () => ({
      choices: run.plan.choices || [],
      allChoices: !!run.plan.allChoices,
      screens: run.plan.screens || null,
      skip: [...begun],
    }),
    take(type, value) {
      if (type === "step") begun.push(value);
      else if (type === "skip") result.skipped.push(value);
      else if (type === "error") error(value);
      else if (type === "done") result.game = value;
    },
    calls: {
      async capture(window_, name, meta) {
        const image = await window_.webContents.capturePage();
        const file = `${run.fileName(name)}.png`;
        fs.writeFileSync(path.join(run.out, file), image.toPNG());
        result.screens.push({ name, file, ...meta });
        // Each capture is progress for whoever runs the capture.
        run.say({ captured: name, title: meta.title });
        return true;
      },
    },
    console(level, message) {
      if (level === "error") error(`console: ${message}`);
    },
    recover(note, step) {
      if (step) result.skipped.push({ screen: step, reason: note });
      else error(note);
      return true;
    },
    finish({ note, timedOut }) {
      if (note) error(note);
      if (timedOut) error(`Capturing took longer than ${run.seconds} seconds.`);
      fs.writeFileSync(
        path.join(run.out, "screens.json"),
        JSON.stringify(result, null, 1),
      );
    },
  };
});
