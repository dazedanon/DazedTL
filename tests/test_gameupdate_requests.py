"""Players' GameUpdate asks GitGud for the newest patch the way GitGud's
admin asks apps to: since 2026-11-02 its Cloudflare rule answers a request
without one of the headers it looks for, such as X-Gitlab-Token, with a
challenge page (HTTP 403), which broke every GitGud game's GameUpdate. When
the forge's API or archive download fails anyway, GameUpdate fetches the
branch with Git's own protocol instead."""

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
GAMEUPDATE = ROOT / "backend/dazedtl/engine/gameupdate"
SHA = "c" * 40
CONFIG = "forge=gitlab\nhost={host}\nusername=Owner\nrepo=Game\nbranch=main\n"

# A stand-in curl: GitGud's challenge for a request without the header, for
# every request when REFUSE is "all" and for the archive when it is "archive",
# else the branch's newest commit and the patch archive of it.
CURL = """
import json, os, sys, zipfile
args = sys.argv[1:]
headers = [args[i + 1] for i, arg in enumerate(args) if arg == "-H"]
url = next(arg for arg in args if arg.startswith("https://"))
refuse = os.environ.get("REFUSE")
if (
    refuse == "all"
    or refuse == "archive" and "/repository/archive.zip" in url
    or not any(header.lower().startswith("x-gitlab-token:") for header in headers)
):
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

POSIX_TOOLS = sys.platform != "win32" and all(
    shutil.which(tool) for tool in ("bash", "git", "jq", "unzip")
)
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def git_env(home: Path, **config: str) -> dict[str, str]:
    """An environment whose Git reads only *config*, never the user's."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": str(len(config)),
    }
    for index, (key, value) in enumerate(config.items()):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


class GameUpdateRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "gitconfig").write_text("", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def game(self, host="gitgud.io", name="game"):
        game = self.root / name
        shutil.copytree(GAMEUPDATE / "gameupdate", game / "gameupdate")
        (game / "gameupdate/patch-config.txt").write_text(
            CONFIG.format(host=host), encoding="utf-8"
        )
        return game

    def patch_repository(self):
        """A bare repository standing in for the patch repository on the
        forge, whose newest commit holds a translated map and DazedTL's
        export-ignored settings; returns its file URL and that commit."""
        work = self.root / "work"
        env = git_env(self.root)
        run = lambda *args, cwd=work: subprocess.run(
            ["git", *args], cwd=cwd, env=env, check=True, capture_output=True
        )
        (work / "www/data").mkdir(parents=True)
        (work / "www/data/Map001.json").write_text(
            '{"translated": true}\n', encoding="utf-8"
        )
        (work / ".dazedtl").mkdir()
        (work / ".dazedtl/settings.json").write_text("{}", encoding="utf-8")
        (work / ".gitattributes").write_text(
            "/.dazedtl export-ignore\n", encoding="utf-8"
        )
        run("-c", "init.defaultBranch=main", "init", "-q")
        run("add", "-A")
        run("-c", "user.name=T", "-c", "user.email=t@t", "commit", "-qm", "patch")
        run(
            "clone",
            "-q",
            "--bare",
            str(work),
            str(self.root / "Game.git"),
            cwd=self.root,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=work,
            env=env,
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()
        return (self.root / "Game.git").as_uri(), head

    def stand_in_curl(self):
        (self.bin / "curl.py").write_text(CURL, encoding="utf-8")
        curl = self.bin / "curl"
        curl.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{self.bin / "curl.py"}" "$@"\n',
            encoding="utf-8",
        )
        curl.chmod(0o755)

    def patch_sh(self, game, env, path=None):
        return subprocess.run(
            ["bash", "gameupdate/patch.sh"],
            cwd=game,
            env={
                **env,
                "PATH": path or f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "GAMEUPDATE_DL_ATTEMPTS": "1",
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )

    def assert_applied(self, game, result, sha):
        state = game / "gameupdate/previous_patch_sha.txt"
        self.assertTrue(state.is_file(), result.stdout + result.stderr)
        self.assertEqual(state.read_text(encoding="utf-8").strip(), sha)
        self.assertEqual(
            json.loads((game / "www/data/Map001.json").read_text(encoding="utf-8")),
            {"translated": True},
        )

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_reaches_gitgud_and_applies_its_newest_patch(self):
        game = self.game()
        self.stand_in_curl()
        result = self.patch_sh(game, os.environ)
        self.assert_applied(game, result, SHA)

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_fetches_the_patch_with_git_when_the_forge_refuses_it(self):
        self.stand_in_curl()
        url, head = self.patch_repository()
        env = git_env(
            self.root, **{f"url.{url}.insteadOf": "https://gitgud.io/Owner/Game.git"}
        )
        # The API refused, or only the archive download.
        for refuse in ("all", "archive"):
            with self.subTest(refuse=refuse):
                game = self.game(name=refuse)
                result = self.patch_sh(game, {**env, "REFUSE": refuse})
                self.assert_applied(game, result, head)
                # The files a forge's archive carries, not the repository's own.
                self.assertFalse((game / ".dazedtl").exists())
                self.assertFalse((game / ".git").exists())

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_tells_players_without_git_how_to_install_it(self):
        game = self.game()
        self.stand_in_curl()
        # Every command on PATH but Git and the package managers, and a dnf.
        tools = self.root / "tools"
        tools.mkdir()
        hidden = {"git", "apt-get", "dnf", "pacman", "zypper", "pkg"}
        for folder in os.environ["PATH"].split(os.pathsep):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if name not in hidden and not (tools / name).exists(
                    follow_symlinks=False
                ):
                    (tools / name).symlink_to(Path(folder) / name)
        dnf = self.bin / "dnf"
        dnf.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dnf.chmod(0o755)
        result = self.patch_sh(
            game, {**os.environ, "REFUSE": "all"}, path=f"{self.bin}{os.pathsep}{tools}"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sudo dnf install git", result.stdout)
        self.assertFalse((game / "gameupdate/previous_patch_sha.txt").exists())

    def test_patch_ps1_pins_the_mingit_dazedtl_installs(self):
        lock = (ROOT / "scripts/runtimes.lock").read_text(encoding="utf-8")
        sha, url = re.search(
            r"^([0-9a-f]{64})  (\S*/MinGit-\S+\.zip)$", lock, re.MULTILINE
        ).groups()
        script = (GAMEUPDATE / "gameupdate/patch.ps1").read_text(encoding="utf-8")
        self.assertIn(f"$MinGitUrl = '{url}'", script)
        self.assertIn(f"$MinGitSha256 = '{sha}'", script)

    def powershell(self, script, env=None, cwd=None):
        return subprocess.run(
            [
                POWERSHELL or "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )

    def functions(self, *names):
        """PowerShell that defines only *names* from patch.ps1, so nothing
        else in it runs."""
        quoted = ", ".join(f"'{name}'" for name in names)
        return (
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            f"'{GAMEUPDATE / 'gameupdate/patch.ps1'}', [ref]$null, [ref]$null); "
            "foreach ($function in $ast.FindAll({ param($node) "
            "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            f"-and $node.Name -in @({quoted}) }}, $true)) {{ "
            ". ([scriptblock]::Create($function.Extent.Text)) }; "
        )

    @unittest.skipUnless(
        POWERSHELL, "patch.ps1 runs where PowerShell does, as on Windows"
    )
    def test_patch_ps1_names_gameupdate_to_gitgud(self):
        result = self.powershell(
            self.functions("New-PatchApiHeaders")
            + "foreach ($kind in 'gitlab', 'github') { "
            "$headers = New-PatchApiHeaders -Resolved @{ kind = $kind }; "
            "Write-Output ($kind + '=' + [string]$headers['X-Gitlab-Token']) }"
        )
        named = dict(line.split("=", 1) for line in result.stdout.split())
        self.assertTrue(named["gitlab"], result.stderr)
        self.assertEqual(named["github"], "")

    @unittest.skipUnless(
        POWERSHELL, "patch.ps1 runs where PowerShell does, as on Windows"
    )
    def test_patch_ps1_refuses_a_mingit_download_that_is_not_the_pinned_one(self):
        archive = self.root / "MinGit.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("cmd/git.exe", "tampered")
        pinned = hashlib.sha256(b"the real MinGit").hexdigest()
        folder = self.root / "gameupdate/mingit"
        result = self.powershell(
            self.functions("Expand-VerifiedMinGit", "Remove-FileOrDirectoryViaCmd")
            + "$ErrorActionPreference = 'Stop'; "
            f"Expand-VerifiedMinGit -ZipPath '{archive}' -Sha256 '{pinned}' -Destination '{folder}'"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pinned checksum", result.stdout + result.stderr)
        self.assertFalse(folder.exists())
        self.assertFalse(folder.with_name("mingit.partial").exists())

    @unittest.skipUnless(
        sys.platform == "win32" and shutil.which("git"),
        "patch.ps1 runs on Windows, with its cmd.exe",
    )
    def test_patch_ps1_fetches_the_patch_with_git_when_the_api_fails(self):
        # A forge that hangs up on every connection, so the API fails at once.
        server = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(server.close)

        def hang_up():
            while True:
                try:
                    server.accept()[0].close()
                except OSError:
                    return

        threading.Thread(target=hang_up, daemon=True).start()
        host = f"127.0.0.1:{server.getsockname()[1]}"
        game = self.game(host)
        url, head = self.patch_repository()
        env = git_env(
            self.root, **{f"url.{url}.insteadOf": f"https://{host}/Owner/Game.git"}
        )
        result = subprocess.run(
            [
                POWERSHELL or "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(game / "gameupdate/patch.ps1"),
                "-GameRoot",
                str(game),
            ],
            env={**env, "GAMEUPDATE_DL_ATTEMPTS": "1"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )
        self.assert_applied(game, result, head)
        self.assertFalse((game / ".dazedtl").exists())
        self.assertFalse((game / "gameupdate/mingit").exists())


if __name__ == "__main__":
    unittest.main()
