import { useState, type CSSProperties } from "react";
import headBody from "../assets/brand/cat-head-outline-body.png";
import headParts from "../assets/brand/cat-head-outline-parts.png";
import catBody from "../assets/brand/cat-outline-body.png";
import catParts from "../assets/brand/cat-outline-parts.png";

/** A part's box in its drawing's pixels: left, top, right, bottom. */
type Box = readonly [number, number, number, number];

/**
 * The dazed cat's two drawings, each split into its still body and one
 * sprite of the parts that move, which sit at their boxes in that sprite.
 * Sparkles are listed in the order they twinkle.
 */
const drawings = {
  head: {
    size: [142, 128],
    body: headBody,
    parts: headParts,
    eyes: [
      [52, 65, 79, 91],
      [90, 71, 116, 98],
    ],
    sparkles: [
      [11, 0, 41, 30],
      [59, 0, 88, 30],
      [0, 35, 29, 65],
    ],
  },
  full: {
    size: [256, 256],
    body: catBody,
    parts: catParts,
    eyes: [
      [87, 78, 118, 110],
      [132, 86, 164, 118],
    ],
    sparkles: [
      [37, 0, 72, 36],
      [94, 0, 130, 36],
      [23, 43, 58, 79],
    ],
  },
} satisfies Record<
  string,
  {
    size: readonly [number, number];
    body: string;
    parts: string;
    eyes: readonly Box[];
    sparkles: readonly Box[];
  }
>;

const percent = (value: number) => `${value * 100}%`;

/**
 * Lays one part over its own box and shows only that box of the sprite, so
 * the part turns and scales about its own centre.
 */
function partStyle(
  [width, height]: readonly [number, number],
  [left, top, right, bottom]: Box,
  sprite: string,
): CSSProperties {
  const w = right - left;
  const h = bottom - top;
  return {
    left: percent(left / width),
    top: percent(top / height),
    width: percent(w / width),
    height: percent(h / height),
    maskImage: `url("${sprite}")`,
    maskSize: `${percent(width / w)} ${percent(height / h)}`,
    maskPosition: `${percent(left / (width - w))} ${percent(top / (height - h))}`,
  };
}

/**
 * The dazed cat as an accent outline. Its sparkles twinkle in turn and its X
 * eyes make a quarter turn: one loop when it appears, then again for as long
 * as it is pointed at, always finishing the loop it is in. The stylesheet
 * keeps it still for reduced motion.
 */
export function CatMark({
  drawing,
  className,
}: {
  drawing: keyof typeof drawings;
  className: string;
}) {
  const [playing, setPlaying] = useState(true);
  const [pointed, setPointed] = useState(false);
  const { size, body, parts, eyes, sparkles } = drawings[drawing];
  return (
    <span
      className={`cat-mark ${className}`}
      data-playing={playing || undefined}
      aria-hidden="true"
      onPointerEnter={() => {
        setPointed(true);
        setPlaying(true);
      }}
      onPointerLeave={() => setPointed(false)}
      onAnimationIteration={() => {
        if (!pointed) setPlaying(false);
      }}
    >
      <span
        className="cat-mark-part cat-mark-body"
        style={{ maskImage: `url("${body}")` }}
      />
      {eyes.map((box, index) => (
        <span
          key={`eye-${index}`}
          className="cat-mark-part cat-mark-eye"
          style={partStyle(size, box, parts)}
        />
      ))}
      {sparkles.map((box, index) => (
        <span
          key={`sparkle-${index}`}
          className="cat-mark-part cat-mark-sparkle"
          data-turn={index}
          style={partStyle(size, box, parts)}
        />
      ))}
    </span>
  );
}
