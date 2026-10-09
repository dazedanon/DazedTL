// Adds DazedTL to the Windows Start menu and desktop, or the Linux application
// menu, pointing at this folder's START launcher. A moved folder updates them
// on its next launch; a desktop shortcut the user deleted stays deleted.
// Another install keeps them while it is there and not older.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { root } from "./dependencies.mjs";
import { compare, installed } from "./update.mjs";

// The folder the Start menu shortcut, or else the desktop one, opens. Shell
// links store paths in any script, but WScript.Shell reads them through the
// ANSI code page, so Shell.Application reads them.
const windowsOwner = `
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$app = New-Object -ComObject Shell.Application
foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
  $item = $app.Namespace($folder).ParseName('DazedTL.lnk')
  if ($item) {
    [Console]::Out.Write($item.GetLink.WorkingDirectory)
    break
  }
}`;

// WScript.Shell writes a shortcut's paths through the ANSI code page, which
// turns a folder named outside it, such as a Japanese user name on an English
// Windows, into question marks, so the shell's Unicode link object writes it.
const windows = `
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW {
  void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int size, IntPtr data, int flags);
  void GetIDList(out IntPtr list);
  void SetIDList(IntPtr list);
  void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int size);
  void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
  void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder folder, int size);
  void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string folder);
  void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder arguments, int size);
  void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
  void GetHotkey(out short key);
  void SetHotkey(short key);
  void GetShowCmd(out int show);
  void SetShowCmd(int show);
  void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, out int index);
  void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
  void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, int reserved);
  void Resolve(IntPtr window, int flags);
  void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
}
[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
class ShellLink {}
public static class DazedTLShortcut {
  public static void Save(string file, string target, string folder, string icon) {
    var link = (IShellLinkW)new ShellLink();
    link.SetPath(target);
    link.SetWorkingDirectory(folder);
    link.SetIconLocation(icon, 0);
    link.SetDescription("Translate games with DazedTL");
    ((IPersistFile)link).Save(file, true);
  }
}
'@
$folders = @([Environment]::GetFolderPath('Programs'))
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'DazedTL.lnk'
if ($env:DAZEDTL_FIRST -or (Test-Path $desktop)) { $folders += [Environment]::GetFolderPath('Desktop') }
foreach ($folder in $folders) {
  [DazedTLShortcut]::Save((Join-Path $folder 'DazedTL.lnk'), $env:DAZEDTL_TARGET, $env:DAZEDTL_ROOT, $env:DAZEDTL_ICON)
}`;

// Desktop entries quote arguments, then escape backslashes again as strings.
const quote = (value) =>
  `"${value.replace(/[`"$\\]/g, (character) => `\\${character}`)}"`
    .replace(/\\/g, "\\\\")
    .replace(/%/g, "%%");

/** The application menu entry; Electron names its Linux window after it. */
export const desktopEntry = "dazedtl.desktop";

const menu = () =>
  path.join(
    process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local/share"),
    "applications",
  );

/** The install folder the shortcuts open, or "" when there are none. */
function owner() {
  if (process.platform === "win32") {
    const result = spawnSync(
      "powershell.exe",
      ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", windowsOwner],
      { windowsHide: true, encoding: "utf8" },
    );
    return result.status === 0 ? result.stdout.trim() : "";
  }
  if (process.platform !== "linux") return "";
  try {
    const entry = fs.readFileSync(path.join(menu(), desktopEntry), "utf8");
    const icon = /^Icon=(.+)$/m.exec(entry)?.[1];
    return icon ? path.dirname(path.dirname(icon)) : "";
  } catch {
    return "";
  }
}

/**
 * Whether another install keeps the shortcuts: one still there and not older
 * than this one, so setting up a second copy, such as an older release kept
 * for comparison, leaves the user's shortcuts alone.
 */
function yields(other) {
  const same = (a, b) =>
    process.platform === "win32"
      ? path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase()
      : path.resolve(a) === path.resolve(b);
  if (!other || same(other, root)) return false;
  const launcher = process.platform === "win32" ? "START.bat" : "START.sh";
  if (!fs.existsSync(path.join(other, launcher))) return false;
  try {
    return compare(installed(other).version, installed(root).version) >= 0;
  } catch {
    return false;
  }
}

/**
 * Creates or moves the shortcuts once per install location. An install that
 * yields them to another asks again on its next start.
 * @param {{ shortcuts?: string }} state
 */
export function shortcuts(state) {
  if (state.shortcuts === root || yields(owner())) return;
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
    const folder = menu();
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
