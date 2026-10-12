// The user's own notification sound. A copy lives in the profile, so the
// original can move or go; the interface decodes and plays it.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const extensions = ["mp3", "wav", "ogg", "oga", "opus", "flac", "m4a", "aac"];
const limit = 10 * 1024 * 1024;
const unsupported = "Choose an MP3, WAV, OGG, FLAC or M4A file of up to 10 MB.";

class NotificationSound {
  /** @param {string} folder */
  constructor(folder) {
    this.folder = folder;
    this.record = path.join(folder, "sound.json");
  }

  /** The saved sound's name and bytes, or null for the built-in chime. */
  read() {
    let saved;
    try {
      saved = JSON.parse(fs.readFileSync(this.record, "utf8"));
    } catch {
      return null;
    }
    if (typeof saved?.name !== "string" || typeof saved.file !== "string")
      return null;
    try {
      return {
        name: saved.name,
        data: fs.readFileSync(
          path.join(this.folder, path.basename(saved.file)),
        ),
      };
    } catch {
      return null;
    }
  }

  /** A sound file the user picks, not saved until the interface can play it. */
  async choose(window, dialog) {
    const selected = await dialog.showOpenDialog(window, {
      title: "Choose a sound",
      properties: ["openFile"],
      filters: [{ name: "Sounds", extensions }],
    });
    if (selected.canceled || !selected.filePaths[0]) return null;
    const file = selected.filePaths[0];
    const size = fs.statSync(file).size;
    if (!allowed(file) || size === 0 || size > limit)
      throw new Error(unsupported);
    return { name: path.basename(file), data: fs.readFileSync(file) };
  }

  /** Keeps a copy and switches to it; the previous copy goes once it has. */
  save(sound) {
    const name = sound?.name;
    const data = sound?.data;
    if (
      typeof name !== "string" ||
      !name ||
      name.length > 255 ||
      name !== path.basename(name) ||
      !allowed(name) ||
      !(data instanceof Uint8Array) ||
      !data.length ||
      data.length > limit
    )
      throw new Error(unsupported);
    fs.mkdirSync(this.folder, { recursive: true });
    const file = `sound-${crypto.randomUUID()}${path.extname(name).toLowerCase()}`;
    fs.writeFileSync(path.join(this.folder, file), data);
    this.write({ name, file });
    this.prune(file);
  }

  /** Back to the built-in chime. */
  clear() {
    fs.rmSync(this.record, { force: true });
    this.prune("");
  }

  write(value) {
    const temporary = `${this.record}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(value));
    fs.renameSync(temporary, this.record);
  }

  prune(keep) {
    let names = [];
    try {
      names = fs.readdirSync(this.folder);
    } catch {
      return;
    }
    for (const entry of names)
      if (entry.startsWith("sound-") && entry !== keep)
        fs.rmSync(path.join(this.folder, entry), { force: true });
  }
}

function allowed(file) {
  return extensions.includes(path.extname(file).slice(1).toLowerCase());
}

module.exports = { NotificationSound };
