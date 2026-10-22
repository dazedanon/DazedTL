import { useSyncExternalStore } from "react";
import type { NotificationSound } from "../api/transport.ts";
import { newTopic } from "./phoneTopic.ts";
import type { WorkAlert } from "./workAlerts.ts";

/** How DazedTL tells the user that work finished or needs them. */
export interface NotificationSettings {
  sound: boolean;
  desktop: boolean;
  phone: boolean;
  /** The ntfy topic the user's phone subscribes to, kept while phone is off. */
  topic: string;
}

interface NotificationState extends NotificationSettings {
  /** The user's own sound file, "" for the chime, or null while it loads. */
  soundName: string | null;
}

// A browser-profile preference, like the remembered workflow views; the
// sound file itself lives in the app profile.
const key = "dazedtl:notifications:v1";
let current: NotificationState | null = null;
const listeners = new Set<() => void>();
let audio: AudioContext | undefined;
const context = () => (audio ??= new AudioContext());
/** The user's sound once loaded, or null for the chime. */
let custom: { name: string; buffer: AudioBuffer } | null | undefined;
let loading: Promise<void> | undefined;

function read(): NotificationState {
  if (current) return current;
  let saved: Partial<NotificationSettings> | null = null;
  try {
    saved = JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    saved = null;
  }
  current = {
    sound: saved?.sound === true,
    desktop: saved?.desktop === true,
    phone: saved?.phone === true,
    // A topic ntfy would refuse is replaced the next time phone is turned on.
    topic:
      typeof saved?.topic === "string" &&
      /^[-_A-Za-z0-9]{1,64}$/.test(saved.topic)
        ? saved.topic
        : "",
    soundName: custom === undefined ? null : custom?.name || "",
  };
  return current;
}

function publish(change: Partial<NotificationState>) {
  current = { ...read(), ...change };
  for (const listener of listeners) listener();
}

export function saveNotifications(change: Partial<NotificationSettings>) {
  const next = { ...read(), ...change };
  if (next.phone && !next.topic) next.topic = newTopic();
  const { sound, desktop, phone, topic } = next;
  localStorage.setItem(key, JSON.stringify({ sound, desktop, phone, topic }));
  publish({ sound, desktop, phone, topic });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  void loadSound();
  return () => {
    listeners.delete(listener);
  };
}

export function useNotifications() {
  return useSyncExternalStore(subscribe, read);
}

// Decoding detaches the bytes it reads, so it gets its own copy.
const decode = (data: Uint8Array) =>
  context().decodeAudioData(data.slice().buffer);

function loadSound() {
  loading ??= window.dazedtl.sound
    .read()
    .then(async (saved) => {
      custom = saved && { name: saved.name, buffer: await decode(saved.data) };
    })
    // A saved file that no longer plays leaves the chime.
    .catch(() => {
      custom = null;
    })
    .finally(() => publish({ soundName: custom?.name || "" }));
  return loading;
}

/** Two soft bell tones a fifth apart, rising. */
function chime(audio: AudioContext) {
  const output = audio.createGain();
  output.gain.value = 0.2;
  output.connect(audio.destination);
  const start = audio.currentTime + 0.03;
  for (const [note, delay] of [
    [659.25, 0],
    [987.77, 0.14],
  ])
    // A bell's fundamental rings longest; its overtones fade first.
    for (const [ratio, level, decay] of [
      [1, 1, 1.4],
      [2, 0.18, 0.5],
      [3, 0.06, 0.25],
    ]) {
      const at = start + delay;
      const tone = audio.createOscillator();
      const envelope = audio.createGain();
      tone.frequency.value = note * ratio;
      envelope.gain.setValueAtTime(0.0001, at);
      envelope.gain.exponentialRampToValueAtTime(level, at + 0.012);
      envelope.gain.exponentialRampToValueAtTime(0.0001, at + decay);
      tone.connect(envelope).connect(output);
      tone.start(at);
      tone.stop(at + decay + 0.05);
    }
}

/** A sound file plays for up to this many seconds, then fades out. */
const LONGEST = 10;

async function play() {
  await loadSound();
  const audio = context();
  void audio.resume();
  if (!custom) return chime(audio);
  const source = audio.createBufferSource();
  const level = audio.createGain();
  source.buffer = custom.buffer;
  source.connect(level).connect(audio.destination);
  const start = audio.currentTime + 0.03;
  source.start(start);
  if (custom.buffer.duration > LONGEST) {
    level.gain.setValueAtTime(1, start + LONGEST - 1);
    level.gain.linearRampToValueAtTime(0, start + LONGEST);
    source.stop(start + LONGEST);
  }
}

const unplayable =
  "That file can't be played. Choose an MP3, WAV, OGG, FLAC or M4A file.";

/**
 * Lets the user pick a sound file and plays it. It is kept only if it
 * decodes, so a file that can't play leaves the current sound in place.
 */
export async function chooseSound() {
  const picked: NotificationSound | null = await window.dazedtl.sound.choose();
  if (!picked) return;
  const buffer = await decode(picked.data).catch(() => {
    throw new Error(unplayable);
  });
  await window.dazedtl.sound.save(picked);
  custom = { name: picked.name, buffer };
  publish({ soundName: picked.name });
  await play();
}

/** Goes back to the built-in chime and plays it. */
export async function resetSound() {
  await window.dazedtl.sound.clear();
  custom = null;
  publish({ soundName: "" });
  await play();
}

/**
 * Plays the sound and sends the desktop and phone notifications, as chosen
 * in Settings. Electron shows the desktop notification only while the window
 * is in the background, unless this is the Settings test. One that fails
 * leaves the others; the first failure is reported.
 */
export async function notify(alert: WorkAlert, test = false) {
  const settings = read();
  if (settings.sound) play().catch(() => undefined);
  const lines = alert.lines
    .slice(0, 3)
    .map((line) => (line.length > 160 ? line.slice(0, 159) + "…" : line));
  if (alert.lines.length > 3) lines.push(`and ${alert.lines.length - 3} more`);
  const message = { title: alert.title, body: lines.join("\n") };
  const sent = await Promise.allSettled([
    settings.desktop && window.dazedtl.notify({ ...message, test }),
    settings.phone &&
      window.dazedtl.phone({ ...message, topic: settings.topic }),
  ]);
  for (const result of sent)
    if (result.status === "rejected") throw result.reason;
}
