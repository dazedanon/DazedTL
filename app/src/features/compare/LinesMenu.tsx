import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { CompareScene } from "../../api/contracts";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { lineCounts } from "./compareView";

/** "Map002 Whispering Forest", or "Actors" for a database file. */
export const sceneName = (scene: CompareScene) =>
  [scene.file.replace(/\.json$/i, ""), scene.title].filter(Boolean).join(" ");

const countLabel = (count: number, scene: CompareScene) =>
  count
    ? `first ${count} lines`
    : `${scene.lines.toLocaleString()} ${scene.lines === 1 ? "line" : "lines"}`;

/** The scene a comparison reads by default: the first map's, else the first. */
export const defaultScene = (scenes: readonly CompareScene[]) =>
  scenes.find((scene) => /^Map\d+\.json$/i.test(scene.file)) ?? scenes[0];

/** A tab's file and line count, starting on the default scene's first 10. */
export function useSceneChoice(scenes: readonly CompareScene[]) {
  const [chosen, setChosen] = useState<{ file: string; lines: number }>();
  const scene =
    scenes.find((item) => item.file === chosen?.file) ?? defaultScene(scenes);
  const counts = scene ? lineCounts(scene) : [0];
  return {
    file: scene?.file ?? "",
    lines:
      chosen && scene?.file === chosen.file && counts.includes(chosen.lines)
        ? chosen.lines
        : counts[0],
    change: (file: string, lines: number) => setChosen({ file, lines }),
  };
}

/**
 * Which file's lines a comparison translates, and how many of its first
 * lines: 10, 25 or all of them.
 */
export function LinesMenu({
  scenes,
  file,
  lines,
  change,
  disabled,
}: {
  scenes: readonly CompareScene[];
  file: string;
  lines: number;
  change: (file: string, lines: number) => void;
  disabled: boolean;
}) {
  const scene = scenes.find((item) => item.file === file);
  return (
    <span className="compare-setup-field">
      <span className="compare-setup-label">Lines</span>
      {!scene ? (
        <span className="muted">No file holds text to compare.</span>
      ) : (
        <Menu
          variant="link"
          label="Lines to compare"
          align="start"
          className="compare-lines"
          disabled={disabled}
          trigger={
            <>
              {sceneName(scene)} · {countLabel(lines, scene)}
              <ChevronDown size={14} aria-hidden="true" />
            </>
          }
        >
          {scenes.map((item) => (
            <MenuItem
              key={item.file}
              current={item.file === file}
              className="compare-scene-item"
              onSelect={() =>
                change(item.file, lineCounts(item).includes(lines) ? lines : 0)
              }
            >
              <span>{sceneName(item)}</span>
              <small>{countLabel(0, item)}</small>
            </MenuItem>
          ))}
          <MenuSeparator />
          {lineCounts(scene).map((count) => (
            <MenuItem
              key={count}
              current={count === lines}
              onSelect={() => change(file, count)}
            >
              {count ? `First ${count} lines` : `All ${countLabel(0, scene)}`}
            </MenuItem>
          ))}
        </Menu>
      )}
    </span>
  );
}
