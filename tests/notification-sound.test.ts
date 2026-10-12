import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const { NotificationSound } = createRequire(import.meta.url)(
  "../app/electron/sound.cjs",
);

test("a notification sound keeps one copy in the profile and refuses names that leave it", () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-sound-"));
  const folder = path.join(profile, "notification-sound");
  const sound = new NotificationSound(folder);
  assert.equal(sound.read(), null);
  sound.save({ name: "ding.wav", data: new Uint8Array([1, 2]) });
  sound.save({ name: "Bell 鈴.MP3", data: new Uint8Array([3]) });
  assert.deepEqual(sound.read(), {
    name: "Bell 鈴.MP3",
    data: Buffer.from([3]),
  });
  assert.equal(
    fs.readdirSync(folder).filter((name) => name.startsWith("sound-")).length,
    1,
  );
  // The interface sends the name and bytes; neither may write elsewhere.
  for (const name of ["../escape.mp3", "notes.txt", ""])
    assert.throws(() => sound.save({ name, data: new Uint8Array([1]) }));
  assert.throws(() =>
    sound.save({ name: "empty.wav", data: new Uint8Array() }),
  );
  assert.deepEqual(fs.readdirSync(profile), ["notification-sound"]);
  assert.equal(sound.read()?.name, "Bell 鈴.MP3");
  sound.clear();
  assert.equal(sound.read(), null);
  assert.deepEqual(fs.readdirSync(folder), []);
  fs.rmSync(profile, { recursive: true });
});
