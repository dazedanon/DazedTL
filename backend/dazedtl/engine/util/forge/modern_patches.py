"""Install-time patches for the rewritten Forge plugin (unified forge.js)."""

from __future__ import annotations

import json
import re

_BOOTSTRAP_START = "/*<DazedMTLTool-Forge-bootstrap>*/"
_BOOTSTRAP_END = "/*</DazedMTLTool-Forge-bootstrap>*/"

_MODIFIER_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "meta": "meta",
    "cmd": "meta",
    "command": "meta",
    "win": "meta",
}

_TOGGLE_UI_KEYSTR_RE = re.compile(
    r"(id:`toggle_ui`,name:`Toggle Cheat UI`,desc:`Show/Hide the cheat panel`,keyStr:`)[^`]+(`)"
)
_SHOW_LAUNCHER_DEFAULT_RE = re.compile(
    r"(favorites:\{\},showLauncher:)![01](,quickSaveSlot:1)"
)
_CONFIG_FILENAME_RE = re.compile(r"`forge-config\.json`")
_CONFIG_PATH_EXPRESSION = (
    "window.__dazedForgeConfigPath || `.dazedtl/forge-config.json`"
)
# The minifier renames identifiers between upstream builds, so the anchors
# below capture names from stable code shapes instead of pinning them.
_ID = r"[A-Za-z_$][\w$]*"
_STORAGE_INIT_RE = re.compile(
    rf"if\((?P<path>{_ID})===null\)try\{{let (?P<require>{_ID})={_ID}\(\);"
    rf"if\(!(?P=require)\)return;let (?P<fs>{_ID})=(?P=require)\(`fs`\);"
    rf"if\(!(?P=fs)\)return;(?P<store>{_ID})=(?P=fs);"
    rf"(?P<body>.*?)\}}catch\((?P<error>{_ID})\)\{{(?P<warn>{_ID})\((?P=error)\),"
    rf"(?P=path)=(?P<name>{_ID})\}}"
)
_KEYS_TAB_KEYDOWN_GUARD_RE = re.compile(
    rf"!(?P<shortcuts>{_ID})\._isFocusedOnInput\(\)&&!(?P=shortcuts)\._hasSelection\(\)"
    rf"&&!\((?P<ui>{_ID})\.visible&&(?P=ui)\.activeTab===(?P<tabs>{_ID})\.Shortcuts\)"
)
_CURRENT_KEY_RE = re.compile(
    rf"(?P<shortcuts>{_ID})\.currentKey\.(?P<method>add|remove)\((?P<event>{_ID})\.keyCode\)"
)


def forge_key_str(hotkey: str) -> str:
    """Convert a Dazed forgeHotkey value to Forge shortcut keyStr format."""
    raw = (hotkey or "F10").strip()
    if not raw:
        return "f10"
    parts = re.split(r"\s*\+\s*|\s+", raw)
    out: list[str] = []
    for part in parts:
        token = part.strip().lower()
        if not token:
            continue
        mapped = _MODIFIER_ALIASES.get(token)
        if mapped:
            if mapped not in out:
                out.append(mapped)
        else:
            out.append(token)
    return " ".join(out) or "f10"


def _bootstrap_js(hotkey: str) -> str:
    key_str = json.dumps(forge_key_str(hotkey))
    return f"""{_BOOTSTRAP_START}
(function () {{
  var toggleKey = {key_str};
  // Forge persists settings through NW.js. Resolve the file from the loaded
  // game rather than process.cwd(), which depends on how the executable was
  // launched. Keep it with DazedTL's other ignored per-game metadata.
  window.__dazedForgeConfigPath = ".dazedtl/forge-config.json";
  var forgeNativeFs = null;
  try {{
    var forgeNw =
      typeof nw !== "undefined" ? nw : window.nw || null;
    var forgeRequire =
      typeof window.require === "function"
        ? window.require
        : typeof require === "function"
        ? require
        : forgeNw && typeof forgeNw.require === "function"
        ? forgeNw.require.bind(forgeNw)
        : null;
    var forgeFs = forgeRequire && forgeRequire("fs");
    var forgePath = forgeRequire && forgeRequire("path");
    var forgeProcess =
      (forgeRequire && forgeRequire("process")) ||
      (typeof process !== "undefined" ? process : null);
    forgeNativeFs = forgeFs || null;
    if (forgeFs && forgePath) {{
      var pageDir = "";
      if (
        window.location &&
        String(window.location.protocol || "").toLowerCase() === "file:"
      ) {{
        var pagePath = decodeURIComponent(window.location.pathname || "");
        if (/^\\/[A-Za-z]:\\//.test(pagePath)) pagePath = pagePath.slice(1);
        pageDir = pagePath ? forgePath.dirname(pagePath) : "";
      }}

      // Packaged NW.js games use a chrome-extension:// URL, whose pathname is
      // merely /index.html. Resolve those games from NW/Node process paths and
      // select the first candidate that actually contains an RPG Maker entry.
      var forgeRootCandidates = [];
      function addForgeRoot(candidate) {{
        if (!candidate) return;
        try {{
          var resolved = forgePath.resolve(String(candidate));
          if (forgeRootCandidates.indexOf(resolved) < 0) {{
            forgeRootCandidates.push(resolved);
          }}
        }} catch (e) {{}}
      }}
      addForgeRoot(pageDir);
      addForgeRoot(forgeNw && forgeNw.App && forgeNw.App.startPath);
      if (forgeProcess) {{
        if (forgeProcess.mainModule && forgeProcess.mainModule.filename) {{
          addForgeRoot(forgePath.dirname(forgeProcess.mainModule.filename));
        }}
        if (forgeProcess.execPath) {{
          addForgeRoot(forgePath.dirname(forgeProcess.execPath));
        }}
        if (forgeProcess.cwd) addForgeRoot(forgeProcess.cwd());
      }}

      var gameRoot = "";
      for (var forgeRootIndex = 0; forgeRootIndex < forgeRootCandidates.length; forgeRootIndex++) {{
        var rootCandidate = forgeRootCandidates[forgeRootIndex];
        if (String(forgePath.basename(rootCandidate)).toLowerCase() === "www") {{
          rootCandidate = forgePath.dirname(rootCandidate);
        }}
        if (
          forgeFs.existsSync(forgePath.join(rootCandidate, "index.html")) ||
          forgeFs.existsSync(forgePath.join(rootCandidate, "www", "index.html"))
        ) {{
          gameRoot = rootCandidate;
          break;
        }}
      }}
      if (!gameRoot) gameRoot = forgeRootCandidates[0] || ".";
      var forgeDir = forgePath.join(gameRoot, ".dazedtl");
      var forgeConfig = forgePath.join(forgeDir, "forge-config.json");
      window.__dazedForgeConfigPath = forgeConfig;
      if (!forgeFs.existsSync(forgeDir)) forgeFs.mkdirSync(forgeDir);

      // Preserve settings from the upstream root-level and www locations and
      // the old relative-path patch (which could land under www for MV games).
      var legacyForgeConfigs = [
        forgePath.join(gameRoot, "forge-config.json"),
        forgePath.join(gameRoot, "www", "forge-config.json"),
        forgePath.resolve("forge-config.json")
      ];
      if (pageDir) {{
        legacyForgeConfigs.push(
          forgePath.join(pageDir, ".dazedtl", "forge-config.json")
        );
      }}
      for (var forgeIndex = 0; forgeIndex < legacyForgeConfigs.length; forgeIndex++) {{
        var legacyForgeConfig = legacyForgeConfigs[forgeIndex];
        if (
          forgePath.resolve(legacyForgeConfig) !== forgePath.resolve(forgeConfig) &&
          forgeFs.existsSync(legacyForgeConfig) &&
          !forgeFs.existsSync(forgeConfig)
        ) {{
          forgeFs.renameSync(legacyForgeConfig, forgeConfig);
        }}
      }}
    }}
  }} catch (e) {{}}
  // Some NW.js builds do not expose Node as window.require, and games can also
  // live in read-only folders. Prefer the per-game JSON, but retain settings in
  // a path-scoped browser fallback whenever that file cannot be used.
  var forgeFallbackKey =
    "dazedtl:forge-config:" +
    String((window.location && window.location.pathname) || "game") +
    ":" +
    String(window.__dazedForgeConfigPath);
  function forgeFallbackRead() {{
    try {{
      return localStorage.getItem(forgeFallbackKey);
    }} catch (e) {{
      return null;
    }}
  }}
  function forgeNativeExists(file) {{
    try {{
      return !!(forgeNativeFs && forgeNativeFs.existsSync(file));
    }} catch (e) {{
      return false;
    }}
  }}
  window.__dazedForgeFs = {{
    existsSync: function (file) {{
      return forgeFallbackRead() !== null || forgeNativeExists(file);
    }},
    readFileSync: function (file, encoding) {{
      var fallback = forgeFallbackRead();
      if (fallback !== null) return fallback;
      if (forgeNativeFs) return forgeNativeFs.readFileSync(file, encoding);
      throw new Error("Forge settings storage is unavailable");
    }},
    writeFileSync: function (file, data, encoding) {{
      var nativeError = null;
      if (forgeNativeFs) {{
        try {{
          forgeNativeFs.writeFileSync(file, data, encoding);
          try {{
            localStorage.removeItem(forgeFallbackKey);
          }} catch (e) {{}}
          return;
        }} catch (e) {{
          nativeError = e;
        }}
      }}
      try {{
        localStorage.setItem(forgeFallbackKey, String(data));
        return;
      }} catch (fallbackError) {{
        throw nativeError || fallbackError;
      }}
    }},
    // Forge rereads its settings when the file's modification time changes.
    // The browser fallback has no file, so it reports a fixed time.
    statSync: function (file) {{
      if (forgeFallbackRead() === null && forgeNativeExists(file)) {{
        return forgeNativeFs.statSync(file);
      }}
      return {{ mtimeMs: 0, mtime: new Date(0) }};
    }}
  }};
  // Seed the consolidated store on boot and migrate every legacy forge:* key.
  // This also guarantees that a writable packaged game gets its JSON before
  // the first settings interaction.
  try {{
    var forgeInitialConfig = {{}};
    if (window.__dazedForgeFs.existsSync(window.__dazedForgeConfigPath)) {{
      try {{
        forgeInitialConfig = JSON.parse(
          window.__dazedForgeFs.readFileSync(
            window.__dazedForgeConfigPath,
            "utf8"
          )
        );
      }} catch (e) {{
        forgeInitialConfig = {{}};
      }}
    }}
    function forgeDecodeSetting(value) {{
      if (typeof value !== "string") return value;
      try {{
        return JSON.parse(value);
      }} catch (e) {{
        return value;
      }}
    }}
    function forgeSettingObject(value) {{
      value = forgeDecodeSetting(value);
      return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {{}};
    }}
    for (var forgeConfigKey of Object.keys(forgeInitialConfig)) {{
      if (forgeConfigKey.indexOf("forge:") === 0) {{
        var normalizedForgeKey = forgeConfigKey.slice(6);
        if (!(normalizedForgeKey in forgeInitialConfig)) {{
          forgeInitialConfig[normalizedForgeKey] = forgeDecodeSetting(
            forgeInitialConfig[forgeConfigKey]
          );
        }}
        delete forgeInitialConfig[forgeConfigKey];
      }}
    }}
    try {{
      for (var forgeStorageIndex = 0; forgeStorageIndex < localStorage.length; forgeStorageIndex++) {{
        var legacyForgeKey = localStorage.key(forgeStorageIndex);
        if (legacyForgeKey && legacyForgeKey.indexOf("forge:") === 0) {{
          var migratedForgeKey = legacyForgeKey.slice(6);
          if (!(migratedForgeKey in forgeInitialConfig)) {{
            forgeInitialConfig[migratedForgeKey] = forgeDecodeSetting(
              localStorage.getItem(legacyForgeKey)
            );
          }}
        }}
      }}
    }} catch (e) {{}}
    var forgeShortcuts = forgeSettingObject(forgeInitialConfig.shortcuts);
    forgeShortcuts.toggle_ui = Object.assign(
      {{}},
      forgeShortcuts.toggle_ui,
      {{ keyStr: toggleKey, enabled: true }}
    );
    forgeInitialConfig.shortcuts = forgeShortcuts;
    var forgeSettings = forgeSettingObject(forgeInitialConfig.config);
    forgeSettings.showLauncher = false;
    forgeInitialConfig.config = forgeSettings;
    window.__dazedForgeFs.writeFileSync(
      window.__dazedForgeConfigPath,
      JSON.stringify(forgeInitialConfig, null, 2),
      "utf8"
    );
  }} catch (e) {{}}
  // Forge's shortcut matcher uses legacy keyCode. Some NW.js/Wine builds deliver
  // keydown with keyCode=0 while still setting key/code - map those back.
  window.__dazedKeyCode = function (e) {{
    var kc = e.keyCode || e.which || 0;
    if (kc) return kc;
    var key = String(e.key || "").toLowerCase();
    var code = String(e.code || "");
    if (key === "control") return 17;
    if (key === "alt") return 18;
    if (key === "shift") return 16;
    if (key === "meta") return 91;
    var fm = /^f(\\d{{1,2}})$/.exec(key) || /^f(\\d{{1,2}})$/i.exec(code);
    if (fm) return 111 + parseInt(fm[1], 10);
    var km = /^key([a-z])$/i.exec(code);
    if (km) return km[1].toUpperCase().charCodeAt(0);
    if (key.length === 1) {{
      var c = key.charCodeAt(0);
      if (c >= 97 && c <= 122) return c - 32;
      if (c >= 48 && c <= 57) return c;
    }}
    var dm = /^digit([0-9])$/i.exec(code);
    if (dm) return 48 + parseInt(dm[1], 10);
    return 0;
  }};
}})();
{_BOOTSTRAP_END}"""


def _strip_existing_bootstrap(text: str) -> str:
    while True:
        start = text.find(_BOOTSTRAP_START)
        if start < 0:
            return text
        end = text.find(_BOOTSTRAP_END, start)
        if end < 0:
            return text
        text = text[:start] + text[end + len(_BOOTSTRAP_END) :]
    return text


def _patch_toggle_ui_default(text: str, hotkey: str) -> str:
    """Rewrite Forge's built-in toggle_ui default (Ctrl C) to the Dazed hotkey."""
    key = forge_key_str(hotkey)
    text, n = _TOGGLE_UI_KEYSTR_RE.subn(rf"\g<1>{key}\2", text, count=1)
    if n == 0:
        raise ValueError("Could not patch toggle_ui keyStr in modern Forge bundle")
    return text


def _disable_launcher_default(text: str) -> str:
    """Hide modern Forge's floating launcher; the toggle shortcut remains active."""
    text, n = _SHOW_LAUNCHER_DEFAULT_RE.subn(r"\g<1>!1\2", text, count=1)
    if n == 0:
        raise ValueError("Could not disable modern Forge launcher default")
    return text


def _relocate_config_file(text: str) -> str:
    """Store Forge's runtime settings under the ignored game metadata folder."""
    text, count = _CONFIG_FILENAME_RE.subn(
        _CONFIG_PATH_EXPRESSION, text, count=1
    )
    if count != 1:
        raise ValueError("Could not relocate modern Forge config file")
    return text


def _patch_storage_adapter(text: str) -> str:
    """Load Forge settings from the bootstrap's file/localStorage adapter.

    Upstream resolves its own game root and migrates a www/ copy; the
    bootstrap already resolved the metadata path and migrated older copies.
    """
    def patch(match: re.Match) -> str:
        path, store = match.group("path"), match.group("store")
        reader = re.search(
            rf"{re.escape(store)}\.existsSync\({re.escape(path)}\)\)"
            rf"(?P<read>{_ID})\({re.escape(path)}\)",
            match.group("body"),
        )
        if not reader:
            raise ValueError("Could not find modern Forge's settings reader")
        fs = match.group("fs")
        return (
            f"if({path}===null)try{{let {fs}=window.__dazedForgeFs;"
            f"if(!{fs})return;{store}={fs};{path}=window.__dazedForgeConfigPath;"
            f"{store}.existsSync({path})&&{reader.group('read')}({path})"
            f"}}catch({match.group('error')}){{{match.group('warn')}"
            f"({match.group('error')}),{path}={match.group('name')}}}"
        )

    text, count = _STORAGE_INIT_RE.subn(patch, text)
    if count != 1:
        raise ValueError("Could not patch modern Forge settings storage")
    return text


def _keep_toggle_ui_active_on_keys_tab(text: str) -> str:
    """Keep the required panel toggle active while other keys are disabled."""
    match = _KEYS_TAB_KEYDOWN_GUARD_RE.search(text)
    if not match:
        raise ValueError("Could not keep Forge's UI toggle active on Keys tab")
    shortcuts, ui, tabs = match.group("shortcuts", "ui", "tabs")
    keys_tab = f"{ui}.visible&&{ui}.activeTab==={tabs}.Shortcuts"
    replacements = (
        (
            match.group(0),
            f"!{shortcuts}._isFocusedOnInput()&&!{shortcuts}._hasSelection()",
        ),
        (
            f"{shortcuts}._isFocusedOnInput()||{keys_tab}||",
            f"{shortcuts}._isFocusedOnInput()||",
        ),
        (
            f"for(let e of {shortcuts}.shortcuts)if(!(!e.enabled||!e.keyStr))try{{",
            f"for(let e of {shortcuts}.shortcuts)if(!(!e.enabled||!e.keyStr||"
            f"{keys_tab}&&e.id!==`toggle_ui`))try{{",
        ),
    )
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError("Could not keep Forge's UI toggle active on Keys tab")
        text = text.replace(old, new, 1)
    return text


def _patch_keycode_reads(text: str) -> str:
    """Route Forge shortcut key reads through the keyCode polyfill."""
    methods = [match.group("method") for match in _CURRENT_KEY_RE.finditer(text)]
    if sorted(methods) != ["add", "remove"]:
        raise ValueError(
            "Could not patch Forge keyCode reads: expected one add and one "
            f"remove, found {methods}"
        )
    text = _CURRENT_KEY_RE.sub(
        r"\g<shortcuts>.currentKey.\g<method>(window.__dazedKeyCode(\g<event>))",
        text,
    )

    from_event = re.compile(
        rf"static fromEvent\((?P<event>{_ID})\)\{{return "
        r"(?P<body>[^{}]+)\}(?=static _fromCombiningAloneEvent)"
    )

    def patch_from_event(match: re.Match) -> str:
        event = match.group("event")
        body, count = re.subn(
            rf"\b{re.escape(event)}\.keyCode\b",
            f"window.__dazedKeyCode({event})",
            match.group("body"),
        )
        if count != 2:
            raise ValueError(
                "Could not patch Forge fromEvent keyCode reads: "
                f"expected 2, found {count}"
            )
        return f"static fromEvent({event}){{return {body}}}"

    text, count = from_event.subn(patch_from_event, text, count=1)
    if count != 1:
        raise ValueError("Could not patch Forge fromEvent shortcut parser")
    return text


def apply_modern_forge_patches(text: str, hotkey: str) -> str:
    """Inject the Dazed hotkey and settings bootstrap and harden shortcuts."""
    text = _strip_existing_bootstrap(text)
    text = _patch_toggle_ui_default(text, hotkey)
    text = _disable_launcher_default(text)
    text = _relocate_config_file(text)
    text = _patch_storage_adapter(text)
    text = _keep_toggle_ui_active_on_keys_tab(text)
    text = _patch_keycode_reads(text)
    bootstrap = _bootstrap_js(hotkey)
    match = re.search(r"\*/\s*\n", text)
    if not match:
        return bootstrap + "\n" + text
    pos = match.end()
    return text[:pos] + bootstrap + "\n" + text[pos:]
