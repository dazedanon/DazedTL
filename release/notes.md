<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Images:** a scan groups images that share one backdrop and differ only in their text, such as name cards or area banners, and the task your assistant gets names each image's group, so your assistant rebuilds the clean backdrop from the other images instead of painting over the old text.
- **Images:** your assistant can take the font, size, outline, shadow and glow from an image you already accepted and draw the rest of its group in the same style.
- **Image Text Editor:** text boxes have **Outline**, **Shadow** and **Glow** settings, each with its own colour, and the font list shows the game's own fonts under **This game**.
- **Image Text Editor:** **Rebuild from surroundings** offers a **Repair method**: **Harmonic (smoothest)**, now the default, **Telea (fast)** or **Navier-Stokes (follows lines)**.

### Changed

- **Images:** an image your assistant edits reads **Ready to apply** only after your assistant saves how to redraw it and the image passes the app's checks; otherwise it shows **Needs review** with the reason, such as "No reusable recipe is saved for this image.", and **Apply to game** leaves it out until it is fixed or you choose **Mark user reviewed**.
- **Images:** edited images keep the original file's colour profile and other embedded details when they are saved and applied.
- **Plugin files:** **Apply to game** writes the translated plugins in one click instead of opening a list of file names first; **Recovery** still restores them.
- **Text QA:** your assistant runs four reviewers at the same time instead of reviewing all the text itself, so QA finishes several times sooner; the time left follows how fast it really goes, and the activity line says **one reviewer at a time** when your assistant reviews alone.

### Fixed

- **Images:** an image investigation your assistant has saved only part of no longer reads finished and plays the notification while your assistant is still looking at the other images.
- **Images:** on Windows, the LaMa and AOT repair models can be downloaded and installed; downloads no longer fail with `CERTIFICATE_VERIFY_FAILED`, and when Windows lacks the Microsoft Visual C++ Redistributable your assistant can install Microsoft's own package.
- **Translate:** **Apply** on a task applies that task's own finished run; it could put another task's last saved translations into the game instead.
- **Text QA:** after the app updates while it is running, **Run QA again** no longer keeps saying "An update changed QA's rules after this task was prepared."
- **Player walkthrough:** an RPG Maker MV/MZ walkthrough no longer reads finished and plays the notification as soon as your assistant first saves `WALKTHROUGH.html`; it waits until your assistant's validation of the last saved page passes, and Release says when the page is saved but not validated yet or validation found errors.
