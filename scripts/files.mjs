// File moves for the launcher, setup and updates, which all replace files that
// were written moments earlier.
import fs from "node:fs";

/**
 * Antivirus scanners briefly lock new files on Windows, and a folder being
 * removed stays until its last open file closes; retry before failing.
 */
export function settle(action, tries = 20) {
  for (let attempt = 1; ; attempt++)
    try {
      return action();
    } catch (error) {
      const code = /** @type {NodeJS.ErrnoException} */ (error).code ?? "";
      if (
        attempt >= tries ||
        !["EBUSY", "EPERM", "EACCES", "ENOTEMPTY"].includes(code)
      )
        throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    }
}

/**
 * Moves a finished file or folder over whatever is at `target`, since no
 * system renames onto a folder with files in it. A scanner can hold a new tree
 * for many seconds, so this waits far longer than a single file needs.
 */
export function replaceFolder(source, target) {
  try {
    settle(() => fs.rmSync(target, { recursive: true, force: true }), 300);
    settle(() => fs.renameSync(source, target), 300);
  } catch (error) {
    const { code } = /** @type {NodeJS.ErrnoException} */ (error);
    throw new Error(
      `${target} could not be replaced (${code}). Close anything using it, such as a folder window or a virus scanner, then try again.`,
      { cause: error },
    );
  }
}
