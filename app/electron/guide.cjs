const fs = require("node:fs");
const path = require("node:path");

const imageTypes = {
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
};
// Where each kind of mirror shows a file of the published branch.
const filePaths = {
  github: "blob/main",
  gitlab: "-/blob/main",
  forgejo: "src/branch/main",
};

/**
 * The user guide the Guide page shows, read from this install, where its
 * text is written once. The renderer can read only the guide and the images
 * it shows from docs/media, and open only web addresses and files of this
 * repository, which open on its first mirror.
 */
class Guide {
  constructor(root) {
    this.root = root;
    this.docs = path.join(root, "docs");
  }

  read() {
    return fs.readFileSync(path.join(this.docs, "user-guide.md"), "utf8");
  }

  /** An image the guide shows, as a data URL. */
  image(source) {
    if (typeof source !== "string" || !/^[\w./-]{1,200}$/.test(source))
      throw new Error("The guide shows only its own images.");
    const media = path.join(this.docs, "media");
    const file = path.resolve(this.docs, source);
    const type = imageTypes[path.extname(file).toLowerCase()];
    // A link inside docs/media must not lead out of it either.
    if (
      path.dirname(file) !== media ||
      !type ||
      fs.realpathSync(file) !==
        path.join(fs.realpathSync(media), path.basename(file))
    )
      throw new Error("The guide shows only its own images.");
    return `data:${type};base64,${fs.readFileSync(file).toString("base64")}`;
  }

  /** The web address a link in the guide opens in the system browser. */
  link(href) {
    if (typeof href !== "string" || href.length > 2000)
      throw new Error("That link can't be opened.");
    if (/^https:\/\//i.test(href)) return new URL(href).href;
    const [file, anchor] = href.split("#", 2);
    const target = path.resolve(this.docs, file);
    const relative = path.relative(this.root, target);
    if (
      !file ||
      /^[a-z][a-z\d+.-]*:/i.test(file) ||
      relative === ".." ||
      relative.startsWith(".." + path.sep) ||
      path.isAbsolute(relative) ||
      !fs.existsSync(target)
    )
      throw new Error("That link can't be opened.");
    const [mirror] = JSON.parse(
      fs.readFileSync(path.join(this.root, "release/mirrors.json"), "utf8"),
    );
    if (!Object.hasOwn(filePaths, mirror.type))
      throw new Error("That link can't be opened.");
    const url = new URL(
      `${mirror.url}/${filePaths[mirror.type]}/${relative.split(path.sep).map(encodeURIComponent).join("/")}`,
    );
    if (anchor) url.hash = anchor;
    return url.href;
  }
}

module.exports = { Guide };
