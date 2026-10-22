# Using DazedTL

This guide explains how to translate a game with DazedTL.
To install it, see the [README](../README.md).

## The basics

- **Projects.** Every game folder you open is a project.
  Open one with **Open a game** on the Project page.
  The **×** beside a game in the project menu or under Recent projects removes it from the list, closing it if it is open; its work stays, and opening the game again brings it back.
- **Two methods.** A new game asks how to translate it: **Guided steps** for RPG Maker MV, MZ and VX Ace, or [Assistant-led](#assistant-led) for any game.
  **Change method** on the Project page switches later and keeps the other method's work.
- **Your assistant.** Many steps copy a task for your AI coding assistant, such as Claude Code or Codex.
  Paste it into the assistant and keep DazedTL open; the results show up in DazedTL by themselves.
  Copying a task only uses the clipboard and never starts paid work.
- **Costs.** Anything that uses your API key shows a cost estimate first, and nothing is charged until you approve it.

## The Project page

**Status** shows what comes next.
**Continue** (**Start** for a new game) opens the next unfinished task, and **Last opened** returns to the one you left.
Optional tasks say so and never hold up the next step.

**Assistant tasks** lists the tasks you copied to your assistant and where each one stands; the count in the top bar opens it.
**Dismiss** clears a task you gave up on, and copying it again brings it back.

The other tabs are **History** (runs, estimates and other activity) and [**Checkpoints**](#checkpoints) (every change to the game, and game updates).
In **History**, **Undo** takes out a batch of QA corrections, playtest fixes or rewrapping by undoing its [checkpoint](#checkpoints); when a later checkpoint changed the same files, it names that one to undo first.
A batch applied with an earlier DazedTL version has **Review restore** instead, which puts back the copy it saved then.

Lists everywhere use the same words:

| Word | Meaning |
| --- | --- |
| **Waiting** | The task is with your assistant. |
| **Needs review** | Results need your decision. |
| **Ready to apply** | Results are ready to go into the game. |
| **Applied** | The results are in the game. |
| **Done** | Finished work that doesn't change the game. |
| **Outdated** | Something it was based on changed; redo it. |
| **Blocked** | It can't continue; the detail beside it says why. |

A project belongs to its folder, so a moved or copied game opens as a new project.
Plugin files and Images then offer **Use saved progress** to keep the earlier work, or **Start over**.

## Guided steps

Translation follows five stages: **Set up → Context → Translate → Check → Release**.
You can move between tasks at any time; Alt+Left and Alt+Right (Option on macOS) step through them, and Ctrl+S (Cmd+S) saves Guidance, Line widths and Settings.

### 1. Set up

**Set up this game** asks for the game's version and whether it already contains translations.
It then prepares the game files and starts version tracking, so later game updates can be merged.
Before its first change, DazedTL keeps a copy of every original game file in the game folder's Git history, which you never publish; nothing else is backed up.
From then on DazedTL saves every change it makes to the game, such as an Apply, a Plugin files change or QA's corrections, as its own checkpoint in the game folder's Git history, so there is nothing to save by hand.
Changes you make to the game outside DazedTL are saved as a checkpoint of their own, **Edits made outside DazedTL**, the next time DazedTL changes the game.
If a step fails, the reason appears beside the button and **Finish setup** carries on.
**Preparation tools** reruns a single step.

### 2. Context

**Names & glossary**: copy the task to your assistant.
It finds the speakers, running jokes and recurring terms, lists the names with a free local scanner, and writes the glossary, character notes and game context.
In RPG Maker MZ games the scanner also finds likely **Speaker slips**: boxes in the original game whose nameplate or face likely shows the wrong speaker, such as a nameplate on a sound effect.
Your assistant checks each one in its scene and fixes the real ones; **View names** shows what it fixed and why it kept the rest.
Edit what it wrote in **Guidance**.
**Add game folder** lets an earlier game in a series supply terms; copy the task again afterwards.
**Thorough investigation** looks for names, running jokes and speech habits in three independent passes instead of one, and that step then uses about three times as much of your assistant's plan.

**Event text sources**: copy the investigation to your assistant.
It finds which variables, plugin commands and scripts hold text players see and turns those on.
It also decides how English words stay together in plugin commands and which internal values, such as placeholders, stay untranslated.
When the game shows text DazedTL has no pattern for, your assistant writes one for this game, so you don't need to add it to DazedTL.
Change any choice under **Source choices**; **Other event text** in Translate translates them later.

**Line widths** fills in from your assistant's measurements, which it checks in the running game, and you can change them.
Until then a VX Ace game uses its standard windows' widths, which are narrower than MV and MZ's.
If your assistant cannot measure the game's windows, its task still finishes and the current widths stay; change them yourself if needed and save.
If the app cannot use your assistant's report, Line widths says why; copy the measurement task again or keep the current widths.
Message rows is how many rows one message window shows; a longer message starts its next page after a sentence, and Text QA keeps its corrections within it.
Saving new widths after you apply translations rewraps the text DazedTL applied that no longer fits, and says so beside **Save line widths**; files you translated another way stay as they are.
Wider widths also join again the lines and pages DazedTL broke to fit narrower ones, where the message then takes fewer rows; Apply and an assistant's writes do the same for text translated while the widths were narrower.
Text that does not fit even rewrapped, such as help that needs more rows than its window shows, is listed under **Too long to fit** with its file and place, until you apply text again or change the widths; shorten it in Text QA or the translation.
With portrait is never wider than Dialogue, so saving a narrower Dialogue lowers it and says so.
While a game update waits on conflicts, or another Git problem the page names, the widths save and the rewrap waits until it is resolved.
To undo it, inspect **Fit text to the new Line widths** in the Project page's **History** and choose **Undo**.
Notes is the width of note text DazedTL wraps, such as an item's detail panel; other note text, such as a monster book's lore, keeps the game's own line breaks.

**Cost estimate** shows what translating the whole game costs with your API key before you translate anything.
Click **Estimate cost**: it estimates Database files, Maps & events and Other event text over all their files, with the model shown beside it, and lists each task's cost.
Estimating is free and translates nothing; for Claude models it uses Anthropic's free token count.
On a large game this can take several minutes: each task shows how far it has got and about how long is left, and a finished estimate says how long it took.
The other tasks use your assistant's plan, not your API key.
Choosing another model of the same connection usually shows its prices at once, since its requests stay the same; Claude models count tokens their own way, so they need a new estimate.
If you change the guidance, the source choices or the game's files, choose a model whose requests differ, or update DazedTL, the estimate reads **Outdated**; click **Estimate again**.
Until then **Estimate again** stays off, since it would give the same result.

### 3. Translate

Translate has five tasks.

**Database files** and **Maps & events** translate with your API key:

1. Pick the files; all of them start selected.
   Translate the database first, and try a small early scene before the rest.
2. Choose **Batch** (often half the price, but can take hours) or **Live** (results arrive as you watch), and the model.
3. Click **Translate**, check the estimate and approve it.
   A Batch estimate is often a range: the provider charges less for instructions it reuses, but a Batch sends its requests together, so it may reuse few of them and cost up to the higher figure.
   Until the estimate is ready, its window shows each step, how far it has got and about how long is left.
   If you decline or close it, clicking **Translate** again reuses it while the files and settings are unchanged.
   Choose another model beside the price to see its cost: the estimate takes the new prices at once when the requests stay the same, and a Batch then prepares its requests again for that model before you can submit.
   With **Batch**, names and labels the glossary lacks are translated first with Live, after their own review; they join the glossary even if you then decline the Batch.
4. Click **Apply** to write the translations into the game.
   It writes each file's newest translation, so a file Other event text translated after Maps & events gets both tasks' text, and its review says so.
   Translation wraps each line to your **Line widths**, keeping the Japanese line breaks where the English allows, and Apply wraps again any line still too wide.

**Lines** counts what each file holds right now: lines translated of the lines that hold Japanese, where a message, a choice, a help text or a name each count once.
A file reads **Needs review** while lines are left; hover its status to see why, or click its eye to list them.

Maps & events also translates the names, nicknames and profiles that events give characters, and the choice help that plugins such as MPP_ChoiceEX show from event comments.
Guided turns **Comment text** on for this the first time it opens a game that shows such help; you can change it in Context > Names & glossary > Speaker detection > Settings.
In a project translated before then, each file whose help is still in Japanese counts it as lines left; **Translate** sends only them.
The help wraps to the message window, to the **With portrait** width when the message before the choice shows a face, and is rewrapped with the other text when it no longer fits.

Approved Batch work carries on after DazedTL restarts.
**Reload from game…** starts selected files over from the game's current text.

**Other event text** translates the sources chosen in **Event text sources**, like the other files.

**Plugin files**: copy the task to your assistant, which finds and translates the player-visible text in every plugin.
**Apply to game** writes the translated plugins into the game in one click, as one checkpoint, and **Recovery** lists each application with **Undo**.
Copy the task again to continue, or to have it recheck after you spot untranslated plugin text.
When **Text QA** finds plugin labels too long for the screen, such as a menu command, the task waits on them: copy it again and your assistant shortens them, or keeps one with its reason, then click **Apply to game**.
Your assistant checks each shorter label in the game: DazedTL plays it in a hidden window with the shorter text, without changing the game, and the label counts only once it fits there.

**Images** has four steps, and the filled button is always the next one:

1. **Investigate**: copy the task; your assistant recommends the images with text players read, leaving out sound effects drawn into scenes.
2. **Choose**: recommended images arrive ticked under **Recommended**; untick any, or tick others under **Unsure** or **All images**.
3. **Translate**: copy the translation task; your assistant edits copies of the ticked images.
4. **Apply**: check the results, ask your assistant to redo any, then click **Apply to game**; applied images leave **Recommended** and **Unsure** for **Applied**.
   An image your assistant changed without saving its recipe, or that failed the app's checks, reads **Needs review** with the reason; copy the translation task again so your assistant fixes it, or compare it and mark it reviewed yourself.

**More > Investigate all images again** has your assistant start over; its recommendations replace your list, except images already translated.
**More > Restore originals…** puts the ticked applied images back as the original game had them, from the game's record of its original files; the edited copies stay.

Clicking an image only previews it; its tick box, Space or Ctrl-click ticks it, and **Compare** shows the original beside the edited copy.
**More > Edit text…** opens the ticked images in the Image Text Editor, where you draw boxes over the original text and type their translation.
Each box's **Text style** sets the font, with the game's own fonts first, its colour, and an optional outline, shadow and glow, each with its own colour and opacity; **Render image** draws the result onto the editable copy.

**When something fails.** A banner above the files explains a failed run, and **Run history** lists the task's runs.
**Inspect** shows each request's text, the AI's reply and the technical details.
Files with problems show a warning; **Review issues** jumps to them.
Lines the AI got wrong keep their original text until you translate again.

### 4. Check

Check has one task, **Text QA**, and it is optional.

- **Start text QA** copies the task, and your assistant reviews the translated text and applies the corrections it verifies.
  It runs four reviewers at once; when the page says **one reviewer at a time**, your assistant is reviewing alone, which takes several times longer, so ask it to start the reviewers its QA task describes.
  A correction too wide for its box is rewrapped to the Line widths saved when QA started, and text a window cuts off even rewrapped, such as a long item description, goes to its reviewers to shorten.
  Where a line writes a glossary term another way, such as a place name translated before its glossary row existed, your assistant puts in the glossary's English unless the line means an ordinary word; those corrections read **Glossary term**.
  When the game's wording is the one you want, change the glossary row before running QA.
  QA also opens the game's screens, such as its menus, item lists and shop, without changing the game, and shortens names and commands the game squeezes or cuts off.
  Squeezed text QA can't change, such as a plugin's menu command, goes to **Plugin files**, where its assistant shortens it.
  Answer the questions it can't settle on the page; each correction is listed with **Undo**, and an undone one with **Apply again**.
  QA reviews translations, not Japanese that was never translated; in MV and MZ the playtest below finds that, with the task that translates it.
  Running QA again after plugin files change opens the game's screens again and keeps the review done so far; text the game squeezes only now goes to review, even once QA finished.
  A correction that changes several lines of one scene, such as narration that switches tense, is listed and undone as one.
  QA reviews only text it hasn't reviewed before or that changed since, including lines whose glossary entries changed, and reads the rest only as context.
  When text was checked before you used DazedTL, such as everything up to an update, tell your assistant which version, and QA skips it from then on.
  To take out every correction at once, inspect **Apply QA corrections** in the Project page's **History** and choose **Undo**.
  Inspecting **Prepare or resume translation QA** there shows what QA did not cover: lines its reviewers declined, Japanese never translated and screen text QA can't change.
- For MV and MZ games the same task is also the final check with a playtest, so you copy it once.
  While QA reviews, DazedTL plays the game in a hidden window, writing nothing into it, and your assistant fixes what it finds: translated text through QA's review, Japanese a plugin shows through **Plugin files**, and crashes or windows too small for English in a fixes plugin of DazedTL's own.
  DazedTL puts those fixes into the game only after playing it with them in place breaks nothing new; to take them out, inspect **Apply playtest fixes** in the Project page's **History** and choose **Undo**.
  Its fixes change the game's plugins, so your assistant prepares QA again itself, keeping the review done so far.
  Your assistant adds places the tour can't reach by itself, such as story scenes or a recollection room, and plays the game again after QA's corrections; text problems that play finds go to another round of QA, which your assistant runs too.
  **Assistant tasks** shows Text QA as **Waiting** until a playtest of the game as it now is leaves nothing more for your assistant; then the Project page marks it done.
  If DazedTL can't play the game at all, such as a game without its engine's scripts, the **Playtest** panel reads **Blocked** with the reason, and Text QA finishes without a play once nothing in its report is your assistant's to fix; a crash that stops the game is, so your assistant fixes it first.
  The **Playtest** panel shows how far it got; **Problems** lists what is left, each with the task that fixes it, and **View** shows what the game looked like.
  If no assistant will play the game, as for a QA task copied before an update added the playtest, **Run QA again** copies a task that does.

**Playtest tools** at the top installs TL Inspector and Forge to help you playtest MV and MZ games.
Apply and playtest an early scene before translating everything.

Applying replaces the game's files with the translations.
In a VX Ace game it also packs them into the `Data` files the game reads, as do Plugin files, Text QA, Line widths and undos in **History**.
If you edit a file in the game afterwards, applying it again replaces your edits, and the review names those files.
If applying stops midway, **Restore** on the notice puts its files back as they were before it.

### 5. Release

**Release** builds a clean game ZIP or a patch ZIP with only the changed files.
The clean game ZIP holds the game and its translation; files added to the game folder while you worked, such as notes or downloads, stay out; **View files & exclusions** lists them.
Inside the ZIP, the game's folder takes the archive name, without `.zip`.
Save it outside the game folder.
Translations that aren't in the game yet need **Apply** first.
The ZIP shows **Outdated** once the game changes; build it again to include the changes.
To let players update from a public repository, see [Publishing with GameUpdate](#publishing-with-gameupdate).
**Player walkthrough** copies an optional task for your assistant to write a walkthrough for players.
For an RPG Maker MV/MZ game it reads **Done** once your assistant's validation of the saved page passes.

### RPG Maker VX Ace

Set up's **Convert Ace data** unpacks an encrypted `Game.rgss3a` and converts the game data so it can be translated, into the `ace_json` folder.
The game reads only `Game.rgss3a` while it sits beside `Game.exe`, so Set up moves it into `.dazedtl/ace`.
A game that comes with `ace_json` already converted, such as from DazedMTLTool, keeps it and its translations; Set up then adds only what's missing and moves the archive aside.
Until then every task warns about it, and Apply and Release refuse.
In Assistant-led, your assistant's first preparation of the game does the same conversion.
A [game update](#game-updates) converts the new release the same way, whether it is the complete game or only a new `Game.rgss3a`, and once applied packs your translation into its `Data` and keeps its archive for patches.
VX Ace keeps menu commands, battle messages and other interface text in its Ruby scripts instead of plugins, so **Plugin files** has your assistant translate the text the scripts show.
**Apply** packs the translations into the game's `Data` files in the same step, and Plugin files' **Apply to game** does the same for the scripts.
It also puts the translated game title into `Game.ini`, which is the title the game window shows, in plain letters (é as e, ♥ left out), since players on Linux, Steam Deck or JoiPlay can't start the game from a title in other letters.
If you or your assistant edit `ace_json` outside DazedTL, or it came converted, **Pack outside edits**, in Check or Release, puts it all into the game; Release waits for it.
Name a clean game ZIP with English letters, numbers and symbols only: the name becomes the game's folder, and a VX Ace game doesn't start on English Windows from a folder named in Japanese.
A game whose folder name is in Japanese starts with the folder name in English letters, or `translated-game.zip`, so rename it to the translated title.
A patch ZIP for an encrypted game carries a rebuilt `Game.rgss3a`, so players replace one file.
GameUpdate can't update an encrypted game, so share a new patch for each update instead.

## Assistant-led

1. In **Options**, choose who translates:
   - **API Batch** is recommended: your API key translates in one provider job, usually at half the Live price where the provider offers it.
   - **Live API** sends one request at a time at the full price; new games start on it when your connection can't run Batch.
   - **Assistant only** needs no API key, but your assistant translates every line itself, which uses far more of its plan.

   The API modes need a connection in Settings, and nothing is sent until you approve your assistant's estimate on **Progress**.
2. Set which images to include and any instructions for your assistant.
   **Thorough investigation** looks for names, running jokes and speech habits in three independent passes instead of one, and that step then uses about three times as much of your assistant's plan.
3. **Copy starting prompt** and paste it into your assistant.
   It needs access to the game folder and the DazedTL folder.
   It works on its own and asks you only when it must, such as to approve spending.
4. Keep DazedTL open while it works.
   **Progress** shows its phases, anything it needs from you and any API run.
   DazedTL saves your assistant's changes to the game as checkpoints, such as **Assistant-led: Injection**, each time it reports a phase and when a translation run ends, so your assistant saves nothing by hand.
   With **Image text** on, it also finds the images with text, translates them and puts them in the game; **Images** shows where that stands and lets you change the list.
   For RPG Maker games it measures the game's text boxes and checks them in the running game, and DazedTL wraps the text it writes to them, as Guided does, without changing the game's events, so saved games still load.
   In a VX Ace game DazedTL also packs what it writes into the `Data` files the game reads, so the game folder plays the translation as soon as it is written.
   In MV and MZ games DazedTL's playtest confirms the measurements; in a VX Ace game, which the playtest can't play, your assistant runs the game to check them.
   For RPG Maker games it also runs text QA: **Text QA** appears once it starts, lists each correction with **Undo** and asks you only what it can't settle, which **Progress** points out.
   It also shortens plugin text the game squeezes or cuts off on its screens, such as a menu command.
   For MV and MZ games it runs the playtest too, which **Playtest** shows once it has.
   It fixes crashes and windows too small for English in a fixes plugin of DazedTL's own, which DazedTL puts into the game only after playing it with the fix breaks nothing new, as a checkpoint of its own.
   Approve your assistant's API estimate with the button on **Progress**; your assistant can't start a run you haven't approved there.
   A newer estimate replaces the one waiting.
   Choosing another model of the same connection, or switching between **API Batch** and **Live API**, shows the waiting estimate at the new prices at once when its requests stay the same; approving then sends them with your new choice.
   Other changes, such as a Claude model or another connection, make it out of date; **Estimate again** prepares a new one without your assistant.
   After you approve, **Progress** reminds you to tell your assistant until it has checked in.
   If it goes quiet, for example at a usage limit, paste the prompt into a new session; it picks up the saved work.
   DazedTL counts the game's Japanese text itself, and **Progress** shows whether your assistant extracted all of it; it can't leave out maps or scenes on its own.
   In **Assistant only**, lines your assistant won't translate appear under **Declined lines** while it carries on.
   Estimate them with your API connection and approve, or copy a prompt that has another coding assistant translate only those lines; your assistant picks up the translations once they're saved.
5. To try again from scratch, stop your assistant and choose **Start over…** on **Progress**.
   It puts back the original game files as a new checkpoint, so the attempt stays under **Checkpoints**, and moves your assistant's work and the playtest's fixes to `.dazedtl/archived`; save games, Image Manager work, older backups and your options stay, and so do the glossary and notes unless you clear **Keep glossary and notes**.

Your assistant's session uses its own plan in every mode, so on a limited plan pick a smaller model or lower reasoning effort.

Follow progress and check the translations in the Project page's **History**.
**Inspect run** shows a run's requests one at a time; type a request number, file name or **Failed** in its request box to find one, or choose **Inspect** beside a request error.
Notes beside a translation flag text the AI wasn't sure about; check them against the original.

## Publishing with GameUpdate

GameUpdate lets players update to your latest translation from its public Git repository on GitGud, GitHub or a Forgejo server such as Codeberg.
It is separate from [game updates](#game-updates), which merge a new official version of the game.

Set up adds `GameUpdate.bat` for Windows, `GameUpdate_linux.sh` for Linux, the `gameupdate` folder and a `README.md` that tells players how to patch and becomes the repository's front page.
MV and MZ games also get a startup check that warns players when the repository has a newer version and links to it; offline or after an error, the game starts as usual.
Set up never replaces a game's existing `README.md`; to get the current one, delete it and choose **Recreate GameUpdate files** under **Preparation tools**.

DazedTL connects each game to its repository through `gameupdate/patch-config.txt`, which it writes and saves with the translation:

1. In **Settings > GameUpdate**, choose the forge and host and enter the owner of your patch repositories, such as `dazed-translations`.
   Leave the owner empty if you don't publish with GameUpdate.
2. Each game's repository is under **GameUpdate** in the **Release** task, or on **Options** for Assistant-led.
   DazedTL fills it in from the game's `origin` remote when that belongs to the owner; otherwise type it and **Save**.
   Until it's known, Release waits for it.

The status below it says whether the file is **Ready to publish** or **Changed outside DazedTL**.
For a file someone edited, **Keep the file** keeps its values for this game and **Rewrite the file** puts DazedTL's back; **Follow Settings** later drops what the game kept.
A warning appears when players would download from a site or repository this game's Git remotes don't point to.

The file holds these keys:

| Key | Meaning |
| --- | --- |
| `forge` | `gitlab` (the default), `github` or `forgejo` (`gitea` also works) |
| `host` | The host name only; defaults to `gitgud.io`, `github.com` or `codeberg.org` to match `forge` |
| `username` | The user, organization or group that owns the repository (`owner` and `org` also work) |
| `repo` | The repository name |
| `branch` | The branch players update from |

A file with only `username`, `repo` and `branch` uses GitLab on `gitgud.io`.

The translation's checkpoints also hold the game's glossary, settings and skills in its `.dazedtl` folder, so they are pushed to the repository with the translation.
Players never get them: the game's `.gitattributes` keeps `.dazedtl` out of the downloads GameUpdate applies and out of patch ZIPs.

Before building a clean game ZIP for players, push the translation to the repository branch it tracks.
**Release** then writes that commit into the ZIP's `gameupdate/previous_patch_sha.txt`, so GameUpdate knows which version players start from; the game folder itself doesn't change.
Without the pushed commit, the clean ZIP leaves out `patch-config.txt`, as patch ZIPs always do, so GameUpdate stays off in it.

## Checkpoints

Every change DazedTL makes to the game is a checkpoint in the game folder's Git history, and the Project page's **Checkpoints** tab lists them, newest first, by game version and by stage.
The top says the game's version and either **All changes saved** or how many files were edited outside DazedTL; those become their own checkpoint before DazedTL's next change.

Each checkpoint has **View changes**, which lists the files it changed and, for game text, each line before and after.
Its **…** menu has:

- **Go back to here** puts the game's files back as they were after that change.
- **Undo this change** takes out only that change and keeps the later ones.
  When a later checkpoint changed the same files, the menu names it; undo that one first.
- **Save a copy…** writes the whole game as it was then into a new folder inside the one you choose, and the game stays as it is.

Going back and undoing are checkpoints too, so either can be undone the same way.
The tasks follow: an Apply, QA's corrections or a Plugin files change undone here reads undone in **History** and in its task too, and comes back when you undo the undo.
They work within the current game version; for an earlier version, save a copy.
A file that wasn't part of the translation then gets the original game's version back.

### Game updates

When a game gets a new official version, choose **Start game update** on **Checkpoints**.
Choose the folder the developer released, either the complete game or a patch of files to copy over it; DazedTL says which it looks like, and you can change that.
It sets the new version up as a separate copy, previews the changes, then applies the update to your translation.
Changes you made to the game outside DazedTL are saved as their own checkpoint before the preview, so the update can start.
Lines the developer left as they were keep their translations, even beside new or changed ones.
The preview counts the lines to translate and the translations that go back to Japanese; open a file to see its lines before and after.
A patch keeps every game file it doesn't include, but it can't remove files the developer deleted.
Steps above the checkpoints show where the update stands, and the update starts a new version in the list.
**Discard release** drops an update you don't want.

An update that stops partway, such as when the app closes during it, shows **Finish the interrupted update** on **Checkpoints** and keeps every other change to the game refused until you decide.
When files conflict, **Use official files & continue** resolves the rest with the official game's files, so affected translated text may need translating again.
**Cancel update & restore translation** gives the game back as it was before the update, and you can apply it again.
When the translation already has the update, **Copy assets & finish** copies the images, sounds and other assets it brings into the game.
When the update stopped before it reached the translation, **Cancel update** goes back to the version you had.

Once the update is in the game, Guided steps list the tasks it changed, such as **Maps & events**; each opens with the changed files selected.
Files you translated before read **Outdated** there, so **Reload from game…** brings in their new text, and translating them again only sends the Japanese lines.
For Assistant-led, **Copy post-update task** gives your assistant the update to translate.

### Backups from before checkpoints

DazedTL no longer takes backups; the ones it saved before checkpoints stay in the game's `.dazedtl/backups` folder, and **Checkpoints** opens it.
A game set up then keeps reading its original files from them.
These commands, run from the DazedTL folder, list, check and restore them; your coding assistant can run them for you.
On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`.

```bash
.venv/bin/python scripts/backups.py --game "/path/to/game" list
.venv/bin/python scripts/backups.py --game "/path/to/game" verify --id SNAPSHOT_ID
.venv/bin/python scripts/backups.py --game "/path/to/game" restore --id SNAPSHOT_ID --destination "/path/to/new-recovery-folder"
```

Don't edit or delete files inside the backup store by hand; backups share files with each other.

## API setup

In **Settings**, choose a provider, paste its API key and save.
Saving checks the connection by listing the provider's models, without generating any text; **Check again** repeats it, and **Model** picks one.
**Translation defaults** holds the target language and the advanced options.
Removing a connection stops its unfinished runs from resuming, so DazedTL tells you how many first.

**Advanced model options** apply to new estimates:

- Requests send 50 lines each by default.
- **Output token allowance** caps each reply at 32,768 tokens, or less when the model allows less.
- For OpenAI, **Batch token allowance** caps how much Batch work runs at once; raise it to your account's limit from [OpenAI Limits](https://platform.openai.com/settings/organization/limits).
- Prices come from the model catalog; models it doesn't know need your own rates, and 0 is fine for free models.

### OpenRouter

Save the key, then choose or type the full model ID, such as `anthropic/claude-sonnet-4.5`.
To use one hosting provider, edit the connection and choose **Host**; a chosen host never falls back to another, and **Automatic** lets OpenRouter choose.
OpenRouter Batches can take up to 24 hours and can't be cancelled once sent.
**Stop queued work** holds back what hasn't been sent, and **Continue queued work** resumes it.
Results missing from a finished Batch wait for **Retry collection** and are never sent again automatically.
Results DazedTL has downloaded stay available after OpenRouter deletes its copy.

### Kimi

Create a key on [Kimi's platform](https://platform.kimi.ai/), then choose **Kimi** as the provider.
Batch works with Kimi K2.6 and K2.7 Code, at 40% off the Live price; Kimi K3 translates Live only.
These models think before they answer, which is billed as output and isn't in the estimate.

## Notifications

**Settings > Notifications** can call you back to DazedTL with a sound, a desktop notification, a notification on your phone, or any of them; all start off.
They come when a translation or other step that took more than a few seconds ends, when work waits for your approval, and when your assistant hands back a task, asks you something or finishes an Assistant-led run.
The sound plays even while DazedTL is in front, so you hear it from across the room; the desktop notification shows only while DazedTL is in the background, clicking it brings DazedTL back, and coming back clears it.
**Sound** plays the built-in chime or a file you choose, such as an MP3 or WAV, for up to 10 seconds; DazedTL keeps its own copy, so you can move or delete the original.
**Send to your phone** goes through [ntfy](https://ntfy.sh), a free notification app for Android and iPhone: install it, tap **+** and subscribe to the **Phone topic** DazedTL shows.
Phone notifications come even while DazedTL is in front, but only while it is open on your computer, since it is what notices the work ending.
They pass through ntfy.sh with the game's name and what happened; the topic is their only password, so keep it to yourself.
**Test notification** tries what you chose.

## Updates

DazedTL checks for a new version once a day and downloads it in the background.
When one is ready, Settings shows a dot; **Settings > Updates** shows what's new in it and has **Restart to update**, which waits while a translation is running.
After the restart, the same tab shows what changed since the version you had, followed by the notes of every earlier version.
Projects, settings, API keys and runs are kept, and every file is checked against the release's signature first.
If an update fails, DazedTL keeps the version you had and says why.

**Go back to** returns to the previous version after a restart, and **Keep** cancels that.
The **Beta** channel offers test versions early.

## When something goes wrong

**Copy diagnostics** in the sidebar copies the app's version and recent errors for a problem report.
If something stays stuck, copy diagnostics while it is still stuck; after a minute they say where it is waiting.
It never includes API keys, game text or what was sent to the AI.
Errors explained on screen aren't recorded, so include that message too.

If a page fails, its panel offers **Try again** and **Reload interface**; reloading keeps running translations going.
