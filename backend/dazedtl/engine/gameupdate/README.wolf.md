# Wolf Games
WOLF RPG games from DLsite often ship a `Data.wolf` archive that the game loads instead of the translated files.
GameUpdate unpacks it once with the bundled `UberWolfCli.exe` ([UberWolf](https://github.com/Sinflower/UberWolf), MIT) and renames `Data.wolf` to `Data.wolf.bak`, so the translation loads.
No separate UberWolf download is needed; on Linux, GameUpdate runs it with Wine.

If unpacking fails (rare, on protected builds), unpack the game once with [UberWolf](https://github.com/Sinflower/UberWolf/releases) so a loose `Data` folder exists, rename or remove `Data.wolf`, delete `gameupdate/previous_patch_sha.txt` and run GameUpdate again.
