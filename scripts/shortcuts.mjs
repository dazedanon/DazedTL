// Adds DazedTL to the Windows Start menu and desktop, or the Linux application
// menu, pointing at this folder's START launcher. A moved folder updates them
// on its next launch; a desktop shortcut the user deleted stays deleted.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { root } from "./dependencies.mjs";

const windows = `
$shell = New-Object -ComObject WScript.Shell
$folders = @([Environment]::GetFolderPath('Programs'))
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'DazedTL.lnk'
if ($env:DAZEDTL_FIRST -or (Test-Path $desktop)) { $folders += [Environment]::GetFolderPath('Desktop') }
foreach ($folder in $folders) {
  $link = $shell.CreateShortcut((Join-Path $folder 'DazedTL.lnk'))
  $link.TargetPath = $env:DAZEDTL_TARGET
  $link.WorkingDirectory = $env:DAZEDTL_ROOT
  $link.IconLocation = $env:DAZEDTL_ICON
  $link.Description = 'Translate games with DazedTL'
  $link.Save()
}`;

// Desktop entries quote arguments, then escape backslashes again as strings.
const quote = (value) =>
  `"${value.replace(/[`"$\\]/g, (character) => `\\${character}`)}"`
    .replace(/\\/g, "\\\\")
    .replace(/%/g, "%%");

/** The application menu entry; Electron names its Linux window after it. */
export const desktopEntry = "dazedtl.desktop";

/**
 * Creates or moves the shortcuts once per install location.
 * @param {{ shortcuts?: string }} state
 */
export function shortcuts(state) {
  if (state.shortcuts === root) return;
  if (process.platform === "win32") {
    const result = spawnSync(
      "powershell.exe",
      ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", windows],
      {
        windowsHide: true,
        env: {
          ...process.env,
          DAZEDTL_FIRST: state.shortcuts ? "" : "1",
          DAZEDTL_TARGET: path.join(root, "START.bat"),
          DAZEDTL_ROOT: root,
          DAZEDTL_ICON: path.join(root, "resources", "icon.ico"),
        },
      },
    );
    // Shortcuts are a convenience; START keeps working without them.
    if (result.status !== 0) return;
  } else if (process.platform === "linux") {
    const folder = path.join(
      process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local/share"),
      "applications",
    );
    try {
      fs.mkdirSync(folder, { recursive: true });
      fs.writeFileSync(
        path.join(folder, desktopEntry),
        [
          "[Desktop Entry]",
          "Type=Application",
          "Name=DazedTL",
          "Comment=Translate games with AI",
          `Exec=bash ${quote(path.join(root, "START.sh"))}`,
          `Icon=${path.join(root, "resources", "icon.png")}`,
          // The terminal shows setup and update progress, then closes.
          "Terminal=true",
          "Categories=Utility;",
          "StartupWMClass=dazedtl",
          "",
        ].join("\n"),
      );
    } catch {
      return;
    }
  }
  state.shortcuts = root;
}
