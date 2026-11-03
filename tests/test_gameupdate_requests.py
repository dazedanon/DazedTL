"""Players' GameUpdate asks GitGud for the newest patch the way GitGud's
admin asks apps to: since 2026-11-02 its Cloudflare rule answers a request
without one of the headers it looks for, such as X-Gitlab-Token, with a
challenge page (HTTP 403), which broke every GitGud game's GameUpdate."""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

GAMEUPDATE = Path(__file__).resolve().parents[1] / "backend/dazedtl/engine/gameupdate"
SHA = "c" * 40

# A stand-in curl: GitGud's challenge for a request without the header,
# else the branch's newest commit and the patch archive of it.
CURL = """
import json, sys, zipfile
args = sys.argv[1:]
headers = [args[i + 1] for i, arg in enumerate(args) if arg == "-H"]
url = next(arg for arg in args if arg.startswith("https://"))
with open(sys.argv[0] + ".log", "a", encoding="utf-8") as log:
    log.write(url + "\\n")
if not any(header.lower().startswith("x-gitlab-token:") for header in headers):
    sys.stderr.write("curl: (22) The requested URL returned error: 403\\n")
    sys.exit(22)
if "/repository/branches/" in url:
    print(json.dumps({"commit": {"id": "SHA"}}))
elif "/repository/archive.zip" in url:
    with zipfile.ZipFile(args[args.index("-o") + 1], "w") as archive:
        archive.writestr("Game-SHA/www/data/Map001.json", '{"translated": true}')
else:
    sys.exit(22)
""".replace("SHA", SHA)


class GameUpdateRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    @unittest.skipIf(
        sys.platform == "win32"
        or not all(shutil.which(tool) for tool in ("bash", "jq", "unzip")),
        "patch.sh runs where bash, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_reaches_gitgud_and_applies_its_newest_patch(self):
        game = self.root / "game"
        shutil.copytree(GAMEUPDATE / "gameupdate", game / "gameupdate")
        (game / "gameupdate/patch-config.txt").write_text(
            "forge=gitlab\nhost=gitgud.io\nusername=Owner\nrepo=Game\nbranch=main\n",
            encoding="utf-8",
        )
        bin = self.root / "bin"
        bin.mkdir()
        (bin / "curl.py").write_text(CURL, encoding="utf-8")
        curl = bin / "curl"
        curl.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{bin / "curl.py"}" "$@"\n',
            encoding="utf-8",
        )
        curl.chmod(0o755)
        result = subprocess.run(
            ["bash", "gameupdate/patch.sh"],
            cwd=game,
            env={**os.environ, "PATH": f"{bin}{os.pathsep}{os.environ['PATH']}"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )
        state = game / "gameupdate/previous_patch_sha.txt"
        self.assertTrue(state.is_file(), result.stdout + result.stderr)
        self.assertEqual(state.read_text(encoding="utf-8").strip(), SHA)
        self.assertEqual(
            json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8")),
            {"translated": True},
        )

    @unittest.skipUnless(
        shutil.which("powershell") or shutil.which("pwsh"),
        "patch.ps1 runs where PowerShell does, as on Windows",
    )
    def test_patch_ps1_names_gameupdate_to_gitgud(self):
        # Only the function, read from the script, so nothing else runs.
        script = (
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            f"'{GAMEUPDATE / 'gameupdate/patch.ps1'}', [ref]$null, [ref]$null); "
            "$function = $ast.Find({ param($node) "
            "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $node.Name -eq 'New-PatchApiHeaders' }, $true); "
            ". ([scriptblock]::Create($function.Extent.Text)); "
            "foreach ($kind in 'gitlab', 'github') { "
            "$headers = New-PatchApiHeaders -Resolved @{ kind = $kind }; "
            "Write-Output ($kind + '=' + [string]$headers['X-Gitlab-Token']) }"
        )
        shell = shutil.which("powershell") or shutil.which("pwsh") or "pwsh"
        result = subprocess.run(
            [shell, "-NoProfile", "-Command", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )
        named = dict(line.split("=", 1) for line in result.stdout.split())
        self.assertTrue(named["gitlab"], result.stderr)
        self.assertEqual(named["github"], "")


if __name__ == "__main__":
    unittest.main()
