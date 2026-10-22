import { encode } from "uqr";

/** Screen pixels per module, whole so each module's edges stay sharp. */
const MODULE = 4;

/**
 * A QR code a phone camera reads: dark modules on a light square with the
 * four-module quiet zone the standard asks for, in every theme, since many
 * scanners miss a light-on-dark code.
 */
export function QrCode({ value, label }: { value: string; label: string }) {
  const { data, size } = encode(value, { ecc: "M", border: 4 });
  const modules = data
    .flatMap((row, y) =>
      row.map((dark, x) => (dark ? `M${x} ${y}h1v1h-1z` : "")),
    )
    .join("");
  return (
    <svg
      className="qr-code"
      role="img"
      aria-label={label}
      width={size * MODULE}
      height={size * MODULE}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
    >
      <rect width={size} height={size} />
      <path d={modules} />
    </svg>
  );
}
