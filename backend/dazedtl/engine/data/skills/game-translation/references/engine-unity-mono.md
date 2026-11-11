# Unity Mono

**Indicators:** `<Game>_Data/Managed/Assembly-CSharp.dll`, `MonoBleedingEdge/`, often `winhttp.dll` + `doorstop_config.ico` (BepInEx already installed). Managed DLLs are real .NET assemblies (unlike IL2CPP) - readable directly in dnSpy.

**Reference implementations:**
- `RP/Unity Mono (NTR Soccer)/` - Unity 2022.3, BepInEx 5.4.23, Pixel Crushers Dialogue System. The **official-localization-locked-to-ja** case (step 3). Mod at `.\mod\NTRSoccerEnglish\`.
- `RP/Unity Mono PlayMaker (CoinPussy)/` - Unity 2022.3, BepInEx 5.4.23, **no localization system and no strings in Assembly-CSharp at all**: everything is PlayMaker FSMs plus CSV TextAssets. Claude batch + live drivers, box-fitting (`reflow`/`shorten`), sha1-keyed CSV swap. See "PlayMaker games" below.

(`RP/` = `tools/Reference Pipelines/`.)

## Step 1 - extract with AssetRipper

`tools/.NET/AssetRipper/AssetRipper.GUI.Free.exe` (a download, see `tools/THIRD-PARTY.md`) → export the game to an `ExportedProject/`. This gives you decompiled `Assets/Scripts/Assembly-CSharp/*.cs` (readable) and all serialized assets as YAML (`.unity`, `.prefab`, `.asset`, `MonoBehaviour/*.asset`).

For DazedTL's census, `tools/Unity Text Dump/unity_dump.py` dumps every TextAsset and MonoBehaviour as text or JSON on Linux or Windows; `TypeTreeGeneratorAPI` rebuilds stripped type trees from `Managed/*.dll`, so no MonoBehaviour is left as raw bytes.

## Step 2 - find where the JP text lives

Search the export for untranslated text with the `JP_TEXT` class in `SKILL.md` ("What counts as untranslated text"), which counts Japanese punctuation as well as kana and kanji. It is almost never in `.cs` code - it's in serialized assets. The usual homes:
- **A dialogue database** - Pixel Crushers Dialogue System stores everything in one big `MonoBehaviour/*.asset` YAML (NTR Soccer: `Dialogue Database.asset`, 8 MB). Entries have base + per-language fields (`Dialogue Text` / `ja` / `zh` / `ko`).
- **A UI text table** - `MonoBehaviour/UI Localization Text Table.asset` (Pixel Crushers TextTable): `m_languageKeys` + `m_fieldValues`, each field with a value per language.
- **TextMeshPro components** in scenes/prefabs - `m_text:` fields (dominant. NTR Soccer had 79 TMP prefabs, 0 legacy `UI.Text`).
- **PlayMaker FSMs** - `stringParams` (plaintext YAML) and hex `byteData` blobs. Decode byteData as UTF-8/UTF-16LE and scan. Usually noise **but sometimes the entire script** - see below.
- **TextAssets** - `TextAsset/*.txt|.csv|.json` in the export, or `m_Script` inside `resources.assets`. CSV script tables live here.
- **StreamingAssets Addressables bundles** (`*.bundle`) - binary. Only if the YAML export is incomplete.

If a full JP sweep of the export finds nothing in `.cs` **and** nothing in a
localization asset, the game is almost certainly FSM-driven. Do not conclude the
text is encrypted - look at PlayMaker and TextAssets before reaching for a runtime
harvest.

Robust YAML field extraction: parse `- title: X` / `value: Y` pairs, join Unity's wrapped multi-line scalars (folds line-wraps as single spaces), handle single-quote `''` escaping. See `tools/Reference Pipelines/Unity Mono (NTR Soccer)/scripts/extract_text.py`.

## Step 3 - CHECK FOR AN OFFICIAL LOCALIZATION AND A MOD FOLDER FIRST

**Some games read loose text files themselves.** List the file paths in `Assembly-CSharp.dll`'s user strings (UTF-16LE) before building a plugin.
One game exports its CSV tables to `../CSV/` on first launch and reads them back, with per-language overrides in `CSV/Language/<name>/`; a translation ships as loose CSV files with no BepInEx at all.

**Many Japanese Unity games ship an official English localization, complete or partial, that is simply locked to `ja`.** Translation tables keyed by the Japanese text (`ニューゲーム,New Game`) count toward it. Before building any dictionary, check:
- Dialogue DB entries have non-empty English base fields (`Dialogue Text`) with `ja` as the variant.
- Scenes hard-code `localizationSettings: { language: ja }`.
- A TextTable has an English `Default`/`en` column.

If so, the entire job is **flipping the language** - a few Harmony prefixes, zero translation. NTR Soccer was 2,590/2,595 strings already in official English. Only 5 needed Mistral.

### Force-locale mod (Pixel Crushers example)
Harmony prefixes that rewrite the language to base/English on every entry point:
```csharp
// DialogueSystemController.SetLanguage(string language)  -> language = ""
// UILocalizationManager.set_currentLanguage(string value) -> value = ""
// Localization.set_language(string value)                 -> value = ""
// TextTable.set_currentLanguageID(int value)              -> value = 0   (0 = Default = EN)
```
Also clear the saved choice: `PlayerPrefs.SetString("Language", "")`. With language `""`, `Field.LookupLocalizedValue` returns base (English) fields and `TextTable.GetFieldTextForLanguage` falls back to the Default column (and for blank Defaults, to the field name, which is usually English too).

Adapt the entry points to the game's localization framework (Unity Localization `LocalizationSettings.SelectedLocale`, I2 Localization `LocalizationManager.CurrentLanguage`, or a custom manager - find it in the decompiled scripts).

## PlayMaker games (no localization, no strings in Assembly-CSharp)

Indicator: `PlayMaker.dll` in `Managed/`, thousands of `Fsm`/`actionData` blocks in
the YAML, and a JP sweep of `Assets/Scripts/` that comes back empty.

### Decoding `actionData`

PlayMaker serialises action parameters into parallel arrays. Each entry has a
`paramDataType` code selecting which typed column its value lives in
(`stringParams`, `intParams`, `fsmStrings`, …). **The codes are build-specific - do
not hardcode a table.** Derive it and prove it:

1. Sweep every `actionData` block, recording each `(paramDataType, column lengths)`.
2. Solve for the assignment where every column is consumed **exactly**.
3. Assert zero saturation violations. A wrong mapping silently reads the wrong
   column and you extract garbage that looks plausible.

Reference: `RP/Unity Mono PlayMaker (CoinPussy)/scripts/unitytl/pmparams.py`
(`tl.py derive` - run once per export, prints the solved table and the proof).

### Separating display text from engine keys

FSM strings are a mix of dialogue and machinery: state names, animator triggers
(`H_M字ピース`), `StringSwitch` comparison values. Translating a key breaks the game
logic silently. Classify by **site**, not by content:

- A string read by a text-setting action (`setTextmeshProUGUIText`, `UiTextSetText`) → display.
- A string used by `StringSwitch` / `StringCompare` / `SetAnimatorTrigger` → key. Denylist it.
- A string that is **both** (a name-box label that is also a switch value - `支配人`,
  `バニー`, `終了`) → translate it, because the dictionary hook runs on the text
  setter, *after* every FSM comparison has already happened. Exclude these from the
  denylist explicitly or they never translate.

Ship the denylist with the plugin: it also stops the untranslated-text log filling
with animator names.

### CSV script tables - one chokepoint hook

Scripted dialogue often lives in TextAsset CSVs parsed through PlayMaker's
DataMaker addon. Every one of them passes through a single static method:

```
HutongGames.PlayMaker.Ecosystem.DataMaker.CSV.CsvReader.LoadFromString(string file_contents, bool, char)
```

One Harmony prefix there swaps the whole file for a translated copy - every row at
once, no per-cell ambiguity, no repack. Resolve it by name via
`AccessTools.Method("Namespace.Type:Method")` so the plugin still builds if the game
updates, and match the Harmony parameter name (`file_contents`) exactly.

**Key the swap on SHA-1 of the original file, not its name or header.** A CSV the
pipeline never saw then simply does not match and stays Japanese, which rules out
the one failure mode that is invisible in play: a stale translation silently
substituted for content it was not built from. Log the unrecognised file's header
and what to re-run. Ship a `DumpLoadedCsv` debug option that writes every CSV the
game parses - that is how you catch one the extractor missed after an update.

### BOM discipline

`TextAsset.text` **keeps** the UTF-8 BOM on Unity 2022.3. Two consequences:

- The first CSV field is a column key the FSMs look up by name. Adding or removing a
  BOM silently renames it. Preserve the caller's BOM state exactly - strip it for
  hashing, re-attach it if the input had one.
- Strings reaching the UI can carry one too. **`String.Trim()` does not treat U+FEFF
  as whitespace in .NET**, so a dictionary key without the BOM never matches one
  with it. Strip U+FEFF explicitly in your normaliser.

## Step 4 - dictionary hook (when text is genuinely Japanese)

Build a BepInEx 5 plugin that hooks text setters and swaps JP→EN from a bundled JSON dict.
Reference: `tools/Reference Pipelines/Unity Mono (NTR Soccer)/mod/NTRSoccerEnglish/` (ported from `tools/Unity BepInEx Translation Plugin Template/SheepClickerTL/`, which is IL2CPP - for Mono, target `BaseUnityPlugin`/`Awake` not `BasePlugin`/`Load`, and reference the real `TMP_Text`/`Text` types directly).

Hooks (two coverage layers):
```
Prefix  TMP_Text.set_text(ref string value)             -> translate in place
Prefix  TMP_Text.SetText(ref string sourceText, bool)
Prefix  UnityEngine.UI.Text.set_text(ref string value)
Postfix TextMeshProUGUI.Awake / OnEnable (TMP_Text __instance)  -> refresh deserialized labels
Postfix TextMeshPro.Awake / OnEnable
Postfix UI.Text.OnEnable
```
The Awake/OnEnable postfixes catch text Unity wrote directly to the `m_text` backing field during scene deserialization (never goes through the setter). Re-assigning `t.text` there routes through the setter prefix.

`TranslationStore` (dict lookup): exact match, newline-normalized match (`\\n`/CRLF/trim), `{0}`-format-pattern matching (compile JP `得点 {0}/{1}` → regex, splice captures into EN template, **slot-aware** so `{1}は{0}`→`{0} is {1}` maps correctly), and a compose walk for concatenated strings.
**A key with a format placeholder is a pattern whatever kind of unit it came from**, so a per-game builder or store must decide by the key, as the template's `LoadAll` does, never by the unit's kind.
Labyrinth City Asylum's `GuildQuest.RewardPlayer` runs `string.Format` on a serialized dialogue line, `クエストクリア！\r\n報酬{0}ゴールドをもらった。`, before the typewriter shows it; its builder filed dialogue units as whole lines, so the key held a literal `{0}` and every reward amount stayed Japanese.
Match patterns with CRs removed from both the key and the game's text, as the template does, so the CRLF a scene serializes and the LF a script writes meet the same key.
**Test coverage with every placeholder filled** (`報酬101ゴールド`, not `報酬{0}ゴールド`): that game's in-game sweep looked up the unfilled template, which matched the literal key, so it reported full coverage while the dialogue box showed Japanese; Step 6's probes fill them for you.
**No English value holds a CR**, bare or in CRLF: TextMeshPro sets the pen back to the line's left edge on one (`if (charCode == 13) m_xAdvance = 0 + tag_Indent` in Unity 2022.3's `TextMeshProUGUI`), so the rest of the line draws over its start.
The same builder joined each dialogue translation into one paragraph by replacing LF only, and the source's CRLF left a CR in 13 English lines (`Quest Clear!\r Received a reward of 2000 gold.`); the template's store drops CRs from every value it loads, and a per-game builder must not write them.
**Give the store one `IsUntranslated` predicate built from `SKILL.md`'s `JP_TEXT` class**, and use it for the lookup gate, the untranslated log and the coverage test alike.
A gate on kana and kanji alone never looks up a punctuation-only line: Labyrinth City Asylum's dictionary had `……。` -> `...`, but its `HasJapanese` gate let 586 lines such as `……。` and `────!!!` through as Japanese, and its log and self-test sweep used the same check, so nothing reported them.
The predicate is true for `……。` and false for `...` and `♡`, so the English the store returns is never looked up again; leave out only the marks this game's English keeps on purpose.
**Gate the compose/pattern paths behind that predicate** and **reject a compose result that leaves any of it in the passthrough** - otherwise a 2-char key like `ん？` corrupts novel strings mid-word (`さん？`→`さHm?`).
Cap the hit/miss caches (dynamic timers/counters grow them unbounded).
Log every string the predicate matches but the store cannot translate to `untranslated.txt` for the QA loop.
Hand-rolled flat JSON parser (`{ "<jp>": "<en>" }`) - no external deps.

## Step 5 - build & install

Compile against the game's own DLLs (`<Game>_Data/Managed/`) + BepInEx core. Csc from VS is fine. **add `netstandard.dll` from the game's Managed folder** as a reference or you get `CS0012: type 'Object' ... netstandard`:
```powershell
csc /target:library /out:Mod.dll `
  /r:"$Managed\mscorlib.dll" /r:"$Managed\netstandard.dll" `
  /r:"$Managed\UnityEngine.CoreModule.dll" /r:"$Managed\UnityEngine.UI.dll" `
  /r:"$Managed\Unity.TextMeshPro.dll" /r:"$Managed\Assembly-CSharp-firstpass.dll" `
  /r:"$Core\BepInEx.dll" /r:"$Core\0Harmony.dll" *.cs
```
Install to `BepInEx/plugins/<ModName>/` with a `translations/` subfolder for the dict. Verify by launching 30s and reading `BepInEx/LogOutput.log` for "N plugins to load" and your hook count.

**Log your verbose swaps at Info, not Debug.** BepInEx's default disk `LogLevels`
excludes `Debug`, so a `LogDebug` line makes `VerboseLogging = true` look broken
unless the user also edits `BepInEx.cfg`.

## Step 6 - the coverage A-test

With the untranslated logger on, play a pass and diff what reached a text component
against what you extracted. On a real run this was **131 of 132 already extracted**,
and the one exception was built at runtime by joining two FSM variables - both of
which *were* extracted separately, and which the store's compose fallback splices.
So coverage was effectively total, and the test proved it rather than assuming it.

Packaging a patch that carries a BepInEx plugin waits for the plugin's coverage self-test, which DazedTL feeds and judges:

1. Run the project helper's `hook-probes` after each export: it writes every exported line as the game shows it, each `{0}`-style item and placeholder token filled with a number no line holds, to `.dazedtl/len-method/work/hook-probes.jsonl`.
2. Start the game once with the plugin installed. Copy `CoverageSelfTest.cs` from the template or NTR Soccer's mod and call `CoverageSelfTest.Run(Paths.GameRootPath)` once the store loads: it looks each probe up through the store the hooks use and writes what the game would show to `hook-results.jsonl` beside the list. If the game's own hooks gate or rewrite text before the store, do the same in it.
3. Run `hook-probes --check`. It names each line that misses, keeps Japanese by `SKILL.md`'s class, holds a carriage return or drops its filled value; fix the store, start the game again and check again.

Packaging also refuses once the export or the plugin's files change after the check, so check again after either.

The logger uses the store's predicate, so punctuation-only lines reach the diff; check that at least one seen in the game, such as `……。`, shows up as translated.

Normalise both sides before diffing (unescape the logger's `\n`, strip BOM and CRLF)
or you will chase phantom misses. That same diff is what surfaced the U+FEFF bug.

## Step 7 - fit the text to its boxes

TMP renders CJK already, so EN needs no font work - but it will overflow boxes
authored for full-width glyphs, and **matching the source's line count does not
prevent it**. Measure the box and wrap to it: `references/text-fitting.md`, toolkit
at `tools/Text Fitting/layout.py`. Auto-sizing
(`tools/Unity BepInEx Text Layout Plugin`) is the fallback for the
long tail of individually-sized widgets, not the fix for dialogue.

## Step 8 - ship it: a build for players, not for you

The dev install logs everything on purpose. A release must not, or the first thing
a player sees is a console window full of Harmony chatter.

```
BepInEx.cfg   [Logging.Console] Enabled = false     # no console window
              [Logging.Disk]    Enabled = false     # no LogOutput.log
plugin cfg    VerboseLogging   = false
              LogUntranslated  = false              # no untranslated.txt
              DumpLoadedCsv    = false
```

Several sections of `BepInEx.cfg` share the key name `Enabled`, so edit
**section-aware** - a blind `Enabled = true -> false` also disables the chainloader
and the patch silently stops loading.

Exclude from the copy: your `tools/`, the AssetRipper export, `BepInEx/cache/`
(machine-specific, regenerates), `LogOutput.log`, `untranslated.txt`, `__pycache__`.
Keep `winhttp.dll`, `doorstop_config.ini` and `.doorstop_version` - drop those and
BepInEx never loads, and the game just runs in Japanese with no error.

Title the window with the project helper's `window-title` text.
Unity titles it with `productName`, which with `companyName` names the save folder (`persistentDataPath`), so never change either: set the window's own text with `WindowTitle.cs` from `tools/Unity BepInEx Translation Plugin Template/SheepClickerTL`, called from the plugin's `Awake`, its `Title` the helper's text.
It calls `SetWindowTextW` on this process's visible `UnityWndClass` window and checks it every second, so the title lands once the window exists and returns if the game resets it.
Labyrinth City Asylum (Unity 2022.3 Mono, BepInEx 5) ran the same calls from a hidden `DontDestroyOnLoad` object's coroutine, because coroutines on BepInEx's manager object never ran there; the template's timer needs no Unity object at all.
Read the title from the running window before shipping.

Ship **two** artefacts. The patch-only archive (plugin + `translations/` + config +
readme, laid out to extract over a game folder) is a couple of hundred KB and is the
one you can hand out. A full repack is the game itself and a licensing question, not
a technical one.

**Key the translated readme files by file name, never by position**, and give the extractor and the builder one list of them that names the files it leaves out.
Labyrinth City Asylum's tools numbered readme units by position among the game folder's sorted `*.txt` files; the publish step then wrote `repo-description.txt` beside the game, which sorts first, so a plain rebuild would have written the cheat readme's English into it and the credits' English into the cheat readme.
Have the builder stop before writing anything when a readme line lands on no line with text.

Verify by running the distribution copy and confirming no `LogOutput.log` and no
`untranslated.txt` appear. The general release discipline, including what a
release archive holds, is in `playtesting-and-release.md`.

**Windows gotcha:** `[` and `]` are wildcards to PowerShell's path parser, so a
folder like `Game [English v1.0]` makes `Copy-Item`/`Compress-Archive` match nothing
and succeed silently - producing an empty archive with no error. Use `-LiteralPath`,
or build the archive from a language that does not glob.
