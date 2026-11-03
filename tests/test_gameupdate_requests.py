"""Players' GameUpdate asks GitGud for the newest patch the way GitGud's
admin asks apps to: since 2026-11-02 its Cloudflare rule answers a request
without one of the headers it looks for, such as X-Gitlab-Token, with a
challenge page (HTTP 403), which broke every GitGud game's GameUpdate. When
the forge's API or archive download fails anyway, GameUpdate reads the branch
from Git's ref advertisement and fetches it with Git's own protocol."""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
GAMEUPDATE = ROOT / "backend/dazedtl/engine/gameupdate"
SHA = "c" * 40
CONFIG = "forge=gitlab\nhost=gitgud.io\nusername=Owner\nrepo=Game\nbranch=main\n"
GIT = shutil.which("git")

# A stand-in curl that answers as curl does (-f fails on an HTTP error, -w
# prints the status, 000 when nothing answered) with what each environment
# variable sets: API (GitGud's challenge without the header by default),
# ARCHIVE ("ok", a status or "corrupt") and REFS (a status, or a file holding
# the ref advertisement); "offline" for any of them answers nothing.
CURL = """
import json, os, sys, zipfile
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("https://"))
headers = [args[i + 1] for i, arg in enumerate(args) if arg == "-H"]
fail = any(arg[:1] == "-" and arg[1:2] != "-" and "f" in arg for arg in args)
out = args[args.index("-o") + 1] if "-o" in args else None
status = "-w" in args

def answer(code, body=b""):
    if code == "offline":
        sys.stderr.write("curl: (7) Failed to connect\\n")
        print("000" if status else "", end="")
        sys.exit(7)
    code = int(code)
    if code >= 400 and fail:
        sys.stderr.write(f"curl: (22) The requested URL returned error: {code}\\n")
        sys.exit(22)
    if out:
        with open(out, "wb") as file:
            file.write(body)
    else:
        sys.stdout.buffer.write(body)
    print(code if status else "", end="")
    sys.exit(0)

if "/info/refs" in url:
    refs = os.environ.get("REFS", "403")
    if os.path.isfile(refs):
        answer(200, open(refs, "rb").read())
    answer(refs)
if "/repository/branches/" in url:
    named = any(header.lower().startswith("x-gitlab-token:") for header in headers)
    answer(os.environ.get("API", "200" if named else "403"), json.dumps({"commit": {"id": "SHA"}}).encode())
if "/repository/archive.zip" in url:
    archive = os.environ.get("ARCHIVE", "ok")
    if archive == "corrupt":
        answer(200, b"PK not really a ZIP")
    if archive != "ok":
        answer(archive)
    with zipfile.ZipFile(out, "w") as zipped:
        zipped.writestr("Game-SHA/www/data/Map001.json", '{"translated": true}')
    answer(200, open(out, "rb").read())
answer(404)
""".replace("SHA", SHA)

POSIX_TOOLS = sys.platform != "win32" and all(
    shutil.which(tool) for tool in ("bash", "git", "jq", "unzip")
)
# Windows ships Windows PowerShell; PowerShell 7 goes first where installed.
POWERSHELL = shutil.which("pwsh") or "powershell"
PACKAGE_MANAGERS = {"apt-get", "dnf", "pacman", "zypper", "pkg", "steamos-readonly"}


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


def advertisement(refs):
    """A Git smart HTTP ref advertisement of *refs*, (sha, ref) pairs."""

    def pkt(line):
        return f"{len(line.encode()) + 4:04x}".encode() + line.encode()

    lines = [
        pkt(f"{sha} {ref}" + ("" if index else "\0multi_ack side-band-64k") + "\n")
        for index, (sha, ref) in enumerate(refs)
    ]
    return pkt("# service=git-upload-pack\n") + b"0000" + b"".join(lines) + b"0000"


class GameUpdateRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "gitconfig").write_text("", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def game(self, name="game"):
        game = self.root / name
        shutil.copytree(GAMEUPDATE / "gameupdate", game / "gameupdate")
        (game / "gameupdate/patch-config.txt").write_text(CONFIG, encoding="utf-8")
        return game

    def patch_repository(self, lfs=False):
        """A bare repository standing in for the patch repository on the
        forge, whose newest commit holds a translated map and DazedTL's
        export-ignored settings, and with *lfs* an image kept in Git LFS;
        returns the Git settings that send GitGud's address to it, and that
        commit."""
        work = self.root / "work"
        env = git_env(self.root)

        def run(*args, cwd=work):
            return subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=env,
                check=True,
                capture_output=True,
                encoding="utf-8",
            ).stdout.strip()

        (work / "www/data").mkdir(parents=True)
        (work / "www/data/Map001.json").write_text(
            '{"translated": true}\n', encoding="utf-8"
        )
        (work / ".dazedtl").mkdir()
        (work / ".dazedtl/settings.json").write_text("{}", encoding="utf-8")
        (work / ".gitattributes").write_text(
            "/.dazedtl export-ignore\n", encoding="utf-8"
        )
        if lfs:
            (work / "img").mkdir()
            (work / "img/Title.png").write_text(
                "version https://git-lfs.github.com/spec/v1\noid sha256:"
                + "0" * 64
                + "\nsize 9\n",
                encoding="utf-8",
            )
            (work / "img/.gitattributes").write_text(
                "*.png filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8"
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
        url = (self.root / "Game.git").as_uri()
        return {f"url.{url}.insteadOf": "https://gitgud.io/Owner/Game.git"}, run(
            "rev-parse", "HEAD"
        )

    def stand_in_curl(self):
        (self.bin / "curl.py").write_text(CURL, encoding="utf-8")
        self.command("curl", f'exec "{sys.executable}" "{self.bin / "curl.py"}" "$@"\n')

    def without_git(self):
        """A PATH with every command but Git and the package managers."""
        tools = self.root / "tools"
        tools.mkdir()
        for folder in os.environ["PATH"].split(os.pathsep):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if (
                    name != "git"
                    and name not in PACKAGE_MANAGERS
                    and not (tools / name).exists(follow_symlinks=False)
                ):
                    (tools / name).symlink_to(Path(folder) / name)
        return f"{self.bin}{os.pathsep}{tools}"

    def command(self, name, script="exit 0\n"):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        path.chmod(0o755)

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

    def assert_applied(self, game, output, sha):
        state = game / "gameupdate/previous_patch_sha.txt"
        self.assertTrue(state.is_file(), output)
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
        self.assert_applied(game, result.stdout + result.stderr, SHA)

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_fetches_the_patch_with_git_when_the_forge_refuses_it(self):
        self.stand_in_curl()
        config, head = self.patch_repository()
        env = git_env(self.root, **config)
        # The API refused, or only the archive download, or an archive that
        # does not unpack.
        for name, refused in (
            ("api", {"API": "403"}),
            ("archive", {"ARCHIVE": "403"}),
            ("corrupt", {"ARCHIVE": "corrupt"}),
        ):
            with self.subTest(name):
                game = self.game(name=name)
                result = self.patch_sh(game, {**env, **refused})
                self.assert_applied(game, result.stdout + result.stderr, head)
                # The files a forge's archive carries, not the repository's own.
                self.assertFalse((game / ".dazedtl").exists())
                self.assertFalse((game / ".git").exists())

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_tells_players_without_git_how_to_install_it(self):
        self.stand_in_curl()
        path = self.without_git()
        # SteamOS's read-only system needs more than pacman.
        for manager, install in (
            ("dnf", "sudo dnf install git"),
            ("steamos-readonly", "sudo steamos-readonly disable"),
        ):
            with self.subTest(manager):
                game = self.game(name=manager)
                self.command(manager)
                result = self.patch_sh(game, {**os.environ, "API": "403"}, path=path)
                (self.bin / manager).unlink()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(install, result.stdout)
                self.assertFalse((game / "gameupdate/previous_patch_sha.txt").exists())

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_answers_from_the_ref_advertisement_without_git(self):
        # No Git and no package manager: anything that needed Git would say
        # how to install it instead.
        self.stand_in_curl()
        path = self.without_git()
        refs = self.root / "refs"
        refs.write_bytes(
            advertisement(
                [
                    ("a" * 40, "HEAD"),
                    ("a" * 40, "refs/heads/old"),
                    (SHA, "refs/heads/main"),
                ]
            )
        )
        cases = (
            ("current", {"API": "403", "REFS": str(refs)}, "Already up to date"),
            (
                "missing",
                {"API": "404", "REFS": "401"},
                "was not found or is not public",
            ),
            (
                "offline",
                {"API": "offline", "REFS": "offline"},
                "Could not reach gitgud.io",
            ),
            ("down", {"API": "502", "REFS": "502"}, "gitgud.io is having problems"),
        )
        for name, answers, said in cases:
            with self.subTest(name):
                game = self.game(name=name)
                (game / "gameupdate/previous_patch_sha.txt").write_text(
                    SHA + "\n", encoding="utf-8"
                )
                result = self.patch_sh(game, {**os.environ, **answers}, path=path)
                self.assertIn(said, result.stdout, result.stdout + result.stderr)
                self.assertNotIn("Install it with", result.stdout)
                self.assertEqual(name == "current", result.returncode == 0)

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_refuses_a_patch_kept_in_git_lfs(self):
        # Git would bring only LFS's pointer files, which break the game.
        game = self.game()
        self.stand_in_curl()
        config, _head = self.patch_repository(lfs=True)
        result = self.patch_sh(game, {**git_env(self.root, **config), "API": "403"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git LFS", result.stdout)
        self.assertFalse((game / "img").exists())
        self.assertFalse((game / "gameupdate/previous_patch_sha.txt").exists())

    @unittest.skipUnless(
        POSIX_TOOLS,
        "patch.sh runs where bash, git, jq and unzip do; Windows players run patch.ps1",
    )
    def test_patch_sh_removes_its_temporary_files_when_stopped(self):
        # A Git stopped mid-fetch, as by a closed terminal.
        game = self.game()
        self.stand_in_curl()
        config, _head = self.patch_repository()
        self.command(
            "git",
            f'case " $* " in *" fetch "*) kill -TERM $PPID; sleep 0.2; exit 1;; esac\nexec "{GIT}" "$@"\n',
        )
        temporary = self.root / "tmp"
        temporary.mkdir()
        result = self.patch_sh(
            game,
            {**git_env(self.root, **config), "API": "403", "TMPDIR": str(temporary)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(temporary.iterdir()), [], result.stdout + result.stderr)
        self.assertFalse((game / "repo.zip").exists())

    def test_patch_ps1_pins_the_mingit_dazedtl_installs(self):
        lock = (ROOT / "scripts/runtimes.lock").read_text(encoding="utf-8")
        sha, url = re.search(
            r"^([0-9a-f]{64})  (\S*/MinGit-\S+\.zip)$", lock, re.MULTILINE
        ).groups()
        script = (GAMEUPDATE / "gameupdate/patch.ps1").read_text(encoding="utf-8")
        self.assertIn(f"$MinGitUrl = '{url}'", script)
        self.assertIn(f"$MinGitSha256 = '{sha}'", script)


@unittest.skipUnless(
    sys.platform == "win32" and GIT,
    "patch.ps1 runs on Windows, with its cmd.exe",
)
class PatchPs1Tests(unittest.TestCase):
    """patch.ps1's own functions, read from the script so its main block does
    not run, with stand-ins for what reaches the network."""

    setUp = GameUpdateRequestTests.setUp
    game = GameUpdateRequestTests.game
    patch_repository = GameUpdateRequestTests.patch_repository
    assert_applied = GameUpdateRequestTests.assert_applied

    def powershell(self, body, env=None):
        script = (
            "$ErrorActionPreference = 'Stop'; "
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            f"'{GAMEUPDATE / 'gameupdate/patch.ps1'}', [ref]$null, [ref]$null); "
            "foreach ($function in $ast.EndBlock.Statements | Where-Object { "
            "$_ -is [System.Management.Automation.Language.FunctionDefinitionAst] }) { "
            ". ([scriptblock]::Create($function.Extent.Text)) }; "
            "$MinGitUrl = 'https://example.invalid/MinGit.zip'; "
            "$MinGitSha256 = $env:PINNED; "
            "try { "
            + body
            + " } catch { Write-Output ('ERROR ' + $_.Exception.Message); exit 3 }"
        )
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            env={**os.environ, "GAMEUPDATE_DL_ATTEMPTS": "1", **(env or {})},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )
        return result.stdout + result.stderr

    def update(self, game, stand_ins, env):
        """Runs Invoke-PatchDownloadExtract on *game* after *stand_ins*,
        PowerShell that replaces some of its functions, and prints its
        result."""
        config = game / "gameupdate/patch-config.txt"
        state = game / "gameupdate/previous_patch_sha.txt"
        return self.powershell(
            stand_ins
            + f"$resolved = Resolve-PatchForge -Cfg (Read-PatchConfig -ConfigPath '{config}'); "
            f"Write-Output ('RESULT ' + (Invoke-PatchDownloadExtract -Root '{game}' "
            f"-StateFilePath '{state}' -Resolved $resolved -BundleRoot '{game / 'gameupdate'}'))",
            env,
        )

    def test_patch_ps1_names_gameupdate_to_gitgud(self):
        output = self.powershell(
            "foreach ($kind in 'gitlab', 'github') { "
            "$headers = New-PatchApiHeaders -Resolved @{ kind = $kind }; "
            "Write-Output ($kind + '=' + [string]$headers['X-Gitlab-Token']) }"
        )
        named = dict(line.split("=", 1) for line in output.split() if "=" in line)
        self.assertTrue(named["gitlab"], output)
        self.assertEqual(named["github"], "")

    def test_patch_ps1_fetches_the_patch_with_git_when_the_forge_refuses_it(self):
        config, head = self.patch_repository()
        env = git_env(self.root, **config)
        api = f"function Get-PatchLatestSha {{ '{head}' }}; "
        cases = {
            # The API refused, and the ref advertisement answered a challenge.
            "api": "function Get-PatchLatestSha { throw '403' }; "
            "function Invoke-PatchHttpGet { @{ Status = 403 } }; ",
            "archive": api + "function Invoke-PatchArchiveDownload { "
            "throw 'The remote server returned an error: (403) Forbidden.' }; ",
            "corrupt": api
            + "function Invoke-PatchArchiveDownload { param($Url, $OutFile) "
            "[IO.File]::WriteAllText($OutFile, 'PK not really a ZIP') }; ",
        }
        for name, stand_ins in cases.items():
            with self.subTest(name):
                game = self.game(name=name)
                output = self.update(game, stand_ins, env)
                self.assertIn("RESULT 0", output)
                self.assert_applied(game, output, head)
                self.assertFalse((game / ".dazedtl").exists())

    def test_patch_ps1_answers_from_the_ref_advertisement_before_any_git(self):
        refs = base64.b64encode(
            advertisement([("a" * 40, "HEAD"), (SHA, "refs/heads/main")])
        ).decode()
        no_git = (
            "function Get-PatchGit { throw 'Git was asked for' }; "
            "function Get-PatchLatestSha { throw '404' }; "
        )
        cases = (
            (
                "current",
                (
                    "function Invoke-PatchHttpGet { "
                    f"@{{ Status = 200; Bytes = [Convert]::FromBase64String('{refs}') }} }}; "
                ),
                "RESULT 10",
            ),
            (
                "missing",
                "function Invoke-PatchHttpGet { @{ Status = 401 } }; ",
                "was not found or is not public",
            ),
            (
                "offline",
                "function Invoke-PatchHttpGet { @{ Status = 0 } }; ",
                "Could not reach gitgud.io",
            ),
            (
                "down",
                "function Invoke-PatchHttpGet { @{ Status = 502 } }; ",
                "gitgud.io is having problems",
            ),
        )
        for name, stand_ins, said in cases:
            with self.subTest(name):
                game = self.game(name=name)
                (game / "gameupdate/previous_patch_sha.txt").write_text(
                    SHA + "\n", encoding="utf-8"
                )
                output = self.update(game, no_git + stand_ins, {})
                self.assertIn(said, output)
                self.assertNotIn("Git was asked for", output)

    def test_patch_ps1_refuses_a_patch_kept_in_git_lfs(self):
        game = self.game()
        config, _head = self.patch_repository(lfs=True)
        output = self.update(
            game,
            "function Get-PatchLatestSha { throw '403' }; "
            "function Invoke-PatchHttpGet { @{ Status = 403 } }; ",
            git_env(self.root, **config),
        )
        self.assertIn("Git LFS", output)
        self.assertFalse((game / "img").exists())
        self.assertFalse((game / "gameupdate/previous_patch_sha.txt").exists())

    def test_patch_ps1_unpacks_without_the_archives_root_folder(self):
        # GitLab's <repo>-<sha>-<sha> root put deep patch paths past 260 characters.
        archive = self.root / "patch.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(f"Game-{SHA}-{SHA}/www/data/Map001.json", "{}")
        stage = self.root / "stage"
        output = self.powershell(
            f"Expand-PatchZip -ZipPath '{archive}' -Destination '{stage}'"
        )
        self.assertTrue((stage / "www/data/Map001.json").is_file(), output)

    def mingit(self):
        """PowerShell that hides Git on PATH and serves a stand-in MinGit ZIP,
        counting downloads in a file; that ZIP's SHA-256; and the file."""
        archive = self.root / "MinGit.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("cmd/git.exe", "stand-in")
        count = self.root / "downloads"
        serve = (
            "$env:PATH = (($env:PATH -split ';') | Where-Object { "
            "$_ -and -not (Test-Path (Join-Path $_ 'git.exe')) }) -join ';'; "
            "function Save-MinGitZip { param($OutFile) "
            f"Add-Content -LiteralPath '{count}' -Value 1; "
            f"Copy-Item -LiteralPath '{archive}' -Destination $OutFile }}; "
        )
        return serve, hashlib.sha256(archive.read_bytes()).hexdigest(), count

    def test_patch_ps1_unpacks_mingit_once_and_reuses_it(self):
        serve, pinned, count = self.mingit()
        bundle = self.root / "gameupdate"
        bundle.mkdir()
        output = self.powershell(
            serve + f"Write-Output (Get-PatchGit -BundleRoot '{bundle}'); "
            f"Write-Output (Get-PatchGit -BundleRoot '{bundle}')",
            {"PINNED": pinned},
        )
        git = bundle / "mingit/cmd/git.exe"
        self.assertEqual(
            [line for line in output.splitlines() if line.endswith("git.exe")],
            [str(git)] * 2,
            output,
        )
        self.assertEqual(
            (bundle / "mingit/dazedtl-mingit.sha256")
            .read_text(encoding="utf-8")
            .strip(),
            pinned,
        )
        self.assertFalse((bundle / "mingit.partial").exists())
        self.assertEqual(count.read_text(encoding="utf-8").split(), ["1"])

    def test_patch_ps1_waits_for_a_scanner_to_let_go_of_mingit(self):
        # A virus scanner holding a file of the MinGit being replaced.
        serve, pinned, _count = self.mingit()
        bundle = self.root / "gameupdate"
        (bundle / "mingit").mkdir(parents=True)
        held = bundle / "mingit/held.dll"
        output = self.powershell(
            serve
            + f"$stream = [IO.File]::Open('{held}', 'Create', 'ReadWrite', 'None'); "
            "$timer = New-Object Timers.Timer 1500; $timer.AutoReset = $false; "
            "Register-ObjectEvent $timer Elapsed -Action { $stream.Dispose() } | Out-Null; "
            "$timer.Start(); "
            f"Write-Output (Get-PatchGit -BundleRoot '{bundle}' -Reinstall)",
            {"PINNED": pinned},
        )
        self.assertTrue((bundle / "mingit/cmd/git.exe").is_file(), output)
        self.assertFalse(held.exists())

    def test_patch_ps1_downloads_a_failing_mingit_again(self):
        serve, pinned, count = self.mingit()
        bundle = self.root / "gameupdate"
        bundle.mkdir()
        output = self.powershell(
            serve + "$script:runs = 0; "
            f"Write-Output (Invoke-WithPatchGit -BundleRoot '{bundle}' -Name 'Fetch' -Action {{ "
            "param($git) $script:runs++; "
            "if ($script:runs -eq 1) { throw 'git-remote-https.exe was quarantined' }; 'fetched' })",
            {"PINNED": pinned},
        )
        self.assertIn("fetched", output)
        self.assertEqual(count.read_text(encoding="utf-8").split(), ["1", "1"])

    def test_patch_ps1_lets_one_gameupdate_run_at_a_time(self):
        bundle = self.root / "gameupdate"
        bundle.mkdir()
        output = self.powershell(
            f"$first = Enter-GameUpdateLock -BundleRoot '{bundle}'; "
            f"Enter-GameUpdateLock -BundleRoot '{bundle}'"
        )
        self.assertIn("Another GameUpdate is already running", output)

    def test_patch_ps1_refuses_a_mingit_download_that_is_not_the_pinned_one(self):
        archive = self.root / "MinGit.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("cmd/git.exe", "tampered")
        pinned = hashlib.sha256(b"the real MinGit").hexdigest()
        folder = self.root / "gameupdate/mingit"
        output = self.powershell(
            f"Expand-VerifiedMinGit -ZipPath '{archive}' -Sha256 '{pinned}' -Destination '{folder}'"
        )
        self.assertIn("pinned checksum", output)
        self.assertFalse(folder.exists())
        self.assertFalse(folder.with_name("mingit.partial").exists())

    def test_patch_ps1_runs_unattended_and_falls_back_to_git(self):
        # The whole script, with the API and every web request refused and
        # its input redirected, so it must not wait for a key.
        game = self.game()
        config, head = self.patch_repository()
        script = (
            "function Invoke-RestMethod { throw 'The remote server returned an error: (403) Forbidden.' }; "
            "function Invoke-WebRequest { [pscustomobject]@{ "
            "StatusCode = 403; RawContentStream = [IO.MemoryStream]::new() } }; "
            f"& '{game / 'gameupdate/patch.ps1'}' -GameRoot '{game}'; exit $LASTEXITCODE"
        )
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            env={**git_env(self.root, **config), "GAMEUPDATE_DL_ATTEMPTS": "1"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )
        self.assert_applied(game, result.stdout + result.stderr, head)
        self.assertFalse((game / ".dazedtl").exists())
        self.assertFalse((game / "gameupdate/gameupdate.lock").exists())


if __name__ == "__main__":
    unittest.main()
