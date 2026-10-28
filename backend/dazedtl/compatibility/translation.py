"""Len's maintained skills and engine helpers behind the migration boundary."""

import json
import os
import tempfile
from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import Any

from dazedtl import system
from dazedtl.projects.store import UNRECOGNIZED
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest
from dazedtl.translation.git_status_cache import RepositoryStatusCache, file_signature
from dazedtl.translation.requests import output_schema, provider_view
from dazedtl.translation.skill_users import for_batch

from . import git_blobs, request_parameters
from .git_blobs import git as _git
from .openrouter_batch import ResultsUnavailable


class ProviderFailure(RuntimeError):
    def __init__(self, operation, error):
        status = getattr(error, "status_code", None)
        self.status_code = status if type(status) is int else None
        detail = "HTTP " + str(status) if self.status_code else type(error).__name__
        super().__init__(
            operation + " failed (" + detail + "). No automatic paid retry was made."
        )


def explained(error):
    """Whether an error's own message says what to fix; any other error is a
    fault the user can only report."""
    from util.version_update import GitWorkflowError

    return isinstance(error, (ValueError, OSError, GitWorkflowError, ProviderFailure))


def provider_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ProviderFailure, ResultsUnavailable:
            raise
        except Exception as error:
            raise ProviderFailure(function.__name__, error) from error

    return call


# The engines besides RPG Maker whose patches GameUpdate installs: it copies a
# patch's files over the game, so a patch laid out as the game updates it,
# such as Unity's replaced assets or BepInEx plugin, a TyranoScript game's
# resources/app or rebuilt app.asar and WOLF's loose Data files or packed
# Data/*.wolf, except what gameupdate_refusal names. Other engines' layouts
# were not checked.
GAMEUPDATE_ENGINES = frozenset({"WOLF", "Unity", "TyranoScript"})


def gameupdate_refusal(engine, files):
    """Why GameUpdate would break a patch of these files, or None. In a WOLF
    game it unpacks the game's Data.wolf into a loose Data folder and takes
    the archive out, the Data.wolf a patch brings too, which the game would
    then not read."""
    if engine == "WOLF" and any(name.casefold() == "data.wolf" for name in files):
        return (
            "GameUpdate unpacks this WOLF game's Data.wolf into a loose Data "
            "folder and takes the archive out, so players who update with it "
            "would lose a repacked Data.wolf. Ship the translated files loose "
            "in the Data folder instead of packing Data.wolf."
        )
    return None


def _tracked(source):
    """The files the game's translation branch tracks."""
    from util.version_update.git_workflow import _run_git

    listed = _run_git(Path(source), "ls-files", "-z").stdout
    return set(listed.rstrip("\0").split("\0")) - {""}


def with_dazedtl_files(source, manifest):
    """A runtime patch manifest with DazedTL's own files the game holds, such
    as GameUpdate's and the playtest's fixes, which every checkpoint and patch
    carries."""
    from util.len_patch_scope import with_dazedtl_files as added

    return added(Path(source), manifest)


def _takes_checkpoints(source):
    """Whether the game's Git is set up and its checkout can take work; one
    that can't, such as one mid-merge, keeps its changes for the operation's
    own refusal to explain."""
    from .game_write import _checkout

    try:
        return _checkout(Path(source).resolve()) is not None
    except ValueError:
        return False


class TranslationEngine:
    def __init__(self, profile):
        from .runtime import activate

        self.source = activate()
        self.profile = Path(profile).resolve()
        # Git's metadata decides everything in a status but whether the
        # working tree is clean, so only that is asked again every few seconds.
        self.repository_status = RepositoryStatusCache(stable=True)
        self.worktrees = RepositoryStatusCache()
        self.original_trees = RepositoryStatusCache(stable=True)
        # Its signature covers everything the GameUpdate status reads.
        self.game_updates = RepositoryStatusCache(ttl=float("inf"))

    @contextmanager
    def context(self):
        from util.paths import runtime_data_profile

        # Engine helpers may print. Never mix them into the application's RPC stream.
        with (
            open(os.devnull, "w", encoding="utf-8") as sink,
            runtime_data_profile(self.profile),
            redirect_stdout(sink),
        ):
            yield

    def project(self, source, options):
        from util.len_translation import LenProject

        return LenProject(
            Path(source).resolve(),
            mode="local" if options["mode"] == "agent" else "api",
            # The engine's project keeps only what shapes the corpus and setup.
            **{
                key: options[key]
                for key in (
                    "include_images",
                    "instructions",
                    "include_glossary_base",
                    "install_forge",
                )
            },
        )

    def detect(self, source):
        from util.project_preparation import rpgmaker_layout
        from util.project_scanner import detect_wolf_layout

        layout = rpgmaker_layout(source)
        if layout:
            return layout["engine"]
        root = Path(source)
        if detect_wolf_layout(root)["engine"] == "WOLF":
            return "WOLF"
        if (root / "tyrano").is_dir() or (root / "resources/app/tyrano").is_dir():
            return "TyranoScript"
        if any(root.glob("*_Data")):
            return "Unity"
        return UNRECOGNIZED

    def documents(self, source):
        from desktop.backend.guidance import documents

        return documents(source)

    def document_save(self, source, name, revision, text):
        from desktop.backend.guidance import document_save, written

        from .game_write import write_game

        # Guidance is never the game's ace_json, so nothing packs.
        with write_game(
            source,
            pack=False,
            paths=written(source, [name]),
            summary="Save guidance",
            stage="Context",
        ):
            return document_save(source, name, revision, text)

    def valid_document(self, name):
        from desktop.backend.guidance import valid_document_name

        return valid_document_name(name)

    def prepare(self, source, options, *, language="English", refresh=True):
        from desktop.backend.guidance import written
        from util.len_progress import initialize_progress
        from util.len_translation import (
            BUNDLED_SKILL,
            _prepare_local_work,
            _validate_skill,
            shared_context,
        )
        from util.project_preparation import rpgmaker_layout
        from util.skills import load_generic_project_setup, load_project_setup

        from .game_write import write_game

        project = self.project(source, options)
        paths = {
            "skill": str(BUNDLED_SKILL / "SKILL.md"),
            "setup": str(project.workspace / "setup.md"),
        }
        if not refresh:
            return paths
        _validate_skill(BUNDLED_SKILL)
        # Both move legacy guidance into .dazedtl, create the glossary and keep
        # DazedTL's rules in the game's .gitignore once its Git is set up, so
        # a game before then is recorded only when the assistant first
        # changes its files.
        with write_game(
            source,
            pack=False,
            paths=written(source, ["glossary"]),
            summary="Prepare the project files",
            stage="Set up",
        ):
            shared = shared_context(project, language)
            _prepare_local_work(project)
        layout = rpgmaker_layout(source)
        setup = (
            load_project_setup(
                "rpgmaker",
                prepend=(
                    "Selected game: " + json.dumps(str(project.game_root)) + "\n"
                    "Reviewed RPG Maker JSON directory: "
                    + json.dumps(str(layout["data_path"]))
                    + "\n"
                    "For Ace, complete decryption and conversion before applying the RPG Maker methodology. "
                    "Collect source speakers without paid API calls in Assistant only mode."
                ),
                thorough=options["thorough_investigation"],
            )
            if layout
            else load_generic_project_setup(
                source, thorough=options["thorough_investigation"]
            )
        )
        write_json(project.workspace / "context.json", shared)
        write_bytes(project.workspace / "setup.md", setup.encode("utf-8"))
        initialize_progress(project)
        return paths

    def progress(self, source, options, report=None, *, verify=False):
        from util.len_progress import read_progress, update_progress

        project = self.project(source, options)
        return (
            update_progress(project, report)
            if report is not None
            else read_progress(project, check_hashes=verify)
        )

    def compile(self, source, options, plan, language, skill_users=None):
        """The context of each batch's request. ``skill_users`` holds the
        note on who uses the skill of each unit holding a battle message, with
        the names whose glossary entries join its request
        (translation/skill_users)."""
        from util.len_translation import request_contexts
        from util.skills import ctx

        from .game_write import write_game

        batches = [
            {
                key: item
                for key, item in batch.items()
                if key
                in {"id", "sources", "speakers", "source_context", "instruction_key"}
            }
            for batch in plan["batches"]
        ]
        noted = [for_batch(skill_users or {}, batch["sources"]) for batch in batches]
        for batch, (_notes, names) in zip(batches, noted):
            if names:
                batch["glossary_names"] = names
        for batch in batches:
            try:
                if batch.get("instruction_key"):
                    ctx(
                        batch["instruction_key"],
                        language=language,
                        context=batch.get("source_context", ""),
                    )
            except KeyError:
                raise ValueError(
                    f"Request {batch['id']} names an unknown field template, "
                    f"{batch['instruction_key']}. Use a section.key from data/translation_contexts.json."
                ) from None
        # The requests' shared context moves legacy guidance into .dazedtl.
        with write_game(
            source,
            pack=False,
            summary="Prepare translation requests",
            stage="Translate",
        ):
            compiled = request_contexts(
                self.project(source, options), batches, language
            )
        for original, result, (users, _names) in zip(plan["batches"], compiled, noted):
            finish_context(result["context"], original, language, users)
        return compiled

    def payload(self, request, configuration):
        return request_payload(request, configuration)

    def token_count(self, text):
        import tiktoken

        return len(
            tiktoken.encoding_for_model("gpt-4").encode(text, disallowed_special=())
        )

    def claude_input_tokens(self, requests, configuration, secret):
        """Claude's own count of these requests' input, or None when its
        endpoint can't count them; Guided's estimate counts the same way."""
        from util import claude_tokens

        if not str(secret or "").strip():  # A keyless connection.
            return None
        client = claude_tokens.CountClient(
            str(secret).strip(), configuration["endpoint"] or None
        )
        return claude_tokens.input_tokens(
            client, [item["params"] for item in requests], self.token_count
        )

    def claude_cache(self, requests, configuration, counted=None):
        """What these requests' cached instructions cost (claude_tokens.cache),
        with Claude's count of each prefix or, without one, the approximate."""
        from util import claude_tokens

        params = [item["params"] for item in requests]
        prefixes = dict(counted.prefixes) if counted else {}
        for value in params:
            key = claude_tokens.split(value)[0]
            if key and key not in prefixes:
                prefixes[key] = self.token_count(claude_tokens.cached_text(value))
        return claude_tokens.cache(
            params, prefixes, "anthropic", configuration["model"]
        )

    @staticmethod
    def openai_cache(requests):
        """The OpenAI automatic cache counts of these requests in plan
        order (requests.CACHE_COUNTS), as Guided's estimate counts them, and
        their input tokens (requests.sent_tokens), counted on the way so a
        big game's text is encoded once."""
        from util.translation import openai_prompt_cache

        reads, cacheable, tokens = openai_prompt_cache(
            [item["params"] for item in requests]
        )
        return {
            "cache_read_tokens": reads,
            "cacheable_tokens": cacheable,
            "input_tokens": tokens + 8 * len(requests),
        }

    def batch_supported(self, configuration):
        if configuration.get("provider") == "openrouter":
            from dazedtl.settings.openrouter import validate_policy

            policy = configuration.get("openrouterBatch")
            return (
                "openrouter"
                if policy and validate_policy(policy, configuration["model"])
                else None
            )
        from .openrouter_batch import is_route

        if is_route(configuration.get("endpoint")):
            return None
        from util.batch_providers import detect_batch_provider

        return detect_batch_provider(
            configuration["model"],
            api_url=configuration["endpoint"],
            api_provider=configuration["protocol"],
        )

    @staticmethod
    def batch_factor(provider):
        """A Batch's price as a multiple of Live, or None when the provider
        has its own Batch rates."""
        if not provider or provider == "openrouter":
            return None
        from util.provider_costs import batch_price_factor

        return batch_price_factor(provider)

    def batch_limits(self, configuration):
        if configuration.get("provider") == "openrouter":
            from dazedtl.settings.openrouter import validate_policy

            policy = validate_policy(
                configuration.get("openrouterBatch"), configuration["model"]
            )
            return [policy["max_requests"], policy["max_bytes"] - 4096, None]
        from util.batch_providers import batch_limits
        from util.translation import _openai_batch_token_limit

        from dazedtl.settings.preferences import batch_input_tokens
        from dazedtl.settings.providers import own_api

        # The OpenAI window applies to this plan's chunks and clarifications
        # (batch_window.reserve_run) only when it holds this allowance.
        native = configuration["protocol"] == "openai" and own_api(
            "openai", configuration["endpoint"]
        )

        allowance = batch_input_tokens(configuration.get("batchInputTokens"))
        return [
            *batch_limits(self.batch_supported(configuration) or ""),
            (allowance or _openai_batch_token_limit()) if native else None,
        ]

    def input_tokens(self, parameters):
        from util.translation import _estimate_openai_batch_input_tokens

        return _estimate_openai_batch_input_tokens(parameters)

    def git_status(self, source, options):
        from util.len_git import git_status
        from util.version_update.git_workflow import worktree_clean

        # The UI polls status twice a second while work runs; a full inspection
        # launches a dozen Git processes, which Windows starts slowly (about
        # 40 ms each). Between metadata changes a poll asks only `git status`.
        project = self.project(source, options)
        key = (str(project.game_root), digest(options))
        status = self.repository_status.get(
            key, project.game_root, lambda: git_status(project)
        )
        if status.get("repo_root"):
            clean = self.worktrees.get(
                key,
                project.game_root,
                lambda: worktree_clean(Path(status["repo_root"])),
            )
            status = {**status, "worktree_clean": clean}
        return status

    def game_update(self, source, defaults, action=None, repo=None):
        """GameUpdate's config status, or the result of reconciling it."""
        from util import gameupdate_config

        from .game_write import write_game

        root = Path(source)
        # A sync on returning to the window mostly changes nothing, and then
        # starts no write, whose checkpoint runs Git.
        if action == "sync" and not gameupdate_config.changes(root, defaults):
            action = None
        if action is not None:
            # It writes the config and the game's settings, never ace_json.
            paths = [gameupdate_config.CONFIG, ".dazedtl/settings.json"]
            with write_game(
                root,
                paths=paths,
                summary="Update the GameUpdate config",
                stage="Release",
            ):
                return gameupdate_config.reconcile(root, defaults, action, repo)
        # Each poll reads it; it changes only with Git's metadata, the config,
        # GameUpdate's scripts, the game's settings and the defaults.
        files = (
            gameupdate_config.CONFIG,
            "gameupdate/patch.ps1",
            "gameupdate/patch.sh",
            ".dazedtl/settings.json",
        )
        return self.game_updates.get(
            str(root),
            root,
            lambda: gameupdate_config.status(root, defaults),
            extra=(
                tuple(sorted(defaults.items())),
                *(file_signature(root / name) for name in files),
            ),
        )

    def source_bindings(self, source, paths):
        """Tracked source inputs follow original, so normal English injection is not source drift."""
        from util.version_update.git_workflow import _run_git

        def listing():
            tree = _run_git(
                Path(source), "ls-tree", "-r", "-z", "original", check=False
            )
            blobs = {}
            if tree.returncode:
                return blobs
            for entry in tree.stdout.split("\0"):
                header, separator, relative = entry.partition("\t")
                fields = header.split()
                if (
                    separator
                    and not relative.startswith(".dazedtl/")
                    and len(fields) == 3
                    and fields[1] == "blob"
                    and fields[0] != "120000"
                ):
                    blobs[relative] = fields[2]
            return blobs

        # Each poll reads these several times; the listing changes only when
        # the original branch moves, which changes the repository signature.
        blobs = self.original_trees.get(str(source), Path(source), listing)
        wanted = set(paths)
        return {path: blob for path, blob in blobs.items() if path in wanted}

    def verify_bindings(self, source, bindings):
        if self.source_bindings(source, list(bindings)) != bindings:
            raise ValueError(
                "The untranslated source baseline changed. Prepare a new request plan for this game version."
            )

    def original_bytes(self, source, blob):
        return git_blobs.original_bytes(source, blob)

    def original_blobs(self, source, blobs):
        """Yields each blob with its bytes, read through one Git process."""
        return git_blobs.original_blobs(source, blobs)

    def error_message(self, error):
        if explained(error):
            return str(error)
        return (
            "Operation failed ("
            + type(error).__name__
            + "). Saved receipts were retained."
        )

    def glossary_terms(self, source):
        """Source terms of the game's own glossary entries, which cover the
        names and nameplates Len translates through the glossary."""
        import re

        from util.paths import GLOSSARY_BASE_SEPARATOR

        path = Path(source) / ".dazedtl/glossary.txt"
        if not path.is_file():
            return []
        game = path.read_text(encoding="utf-8-sig").split(GLOSSARY_BASE_SEPARATOR, 1)[0]
        terms = []
        for line in game.splitlines():
            match = re.match(r"^([^#].*?)\s+\((.+)\)\s*$", line.strip())
            if match:
                terms += [
                    term.strip() for term in match.group(1).split(",") if term.strip()
                ]
        return terms

    def census_decoders(self, root, workdir):
        """What the census uses for data it can't read as text: Ruby Marshal,
        RGSS archives, and Wolf data through the bundled WolfDawn."""
        from util import wolfdawn
        from util.ace import rgssad, ruby_marshal

        root, workdir = Path(root), Path(workdir)

        class Decoders:
            marshal = staticmethod(ruby_marshal.load)

            @staticmethod
            def rgssad(data):
                members = []
                for name, offset, size, key in rgssad.entries(data):
                    if offset + size > len(data):
                        raise ValueError(
                            "An archived file runs past the archive's end."
                        )
                    members.append(
                        (
                            rgssad.safe_path(name).as_posix(),
                            rgssad.decrypt(data[offset : offset + size], key),
                        )
                    )
                return members

            @staticmethod
            def wolf(names):
                return _wolf_documents(wolfdawn, root, workdir, names)

        return Decoders()

    @staticmethod
    def ace_data(folder, names):
        """A VX Ace original's data files in `folder` as plain data, by name:
        each loose Data/*.rvdata2 among `names`, or each inside the RGSS
        archive among them, without decrypting the archive's graphics and
        sound. Scripts are left out."""
        from util.ace import rgssad, ruby_marshal

        from dazedtl.translation.census import marshal_tree

        def wanted(name):
            folder_name, _, file_name = name.casefold().partition("/")
            return (
                folder_name == "data"
                and "/" not in file_name
                and file_name.endswith(".rvdata2")
                and file_name != "scripts.rvdata2"
            )

        raws = {}
        for name in names:
            path = Path(folder) / name
            if wanted(name):
                raws[name] = path.read_bytes()
            elif name.casefold().endswith((".rgss3a", ".rgss2a", ".rgssad")):
                data = path.read_bytes()
                for member, offset, size, key in rgssad.entries(data):
                    member = rgssad.safe_path(member).as_posix()
                    if not wanted(member):
                        continue
                    if offset + size > len(data):
                        raise ValueError(
                            "An archived file runs past the archive's end."
                        )
                    raws[member] = rgssad.decrypt(data[offset : offset + size], key)
        return {
            name: marshal_tree(ruby_marshal.load(raw)) for name, raw in raws.items()
        }

    @staticmethod
    def ace_script_order(root):
        """A VX Ace game's script files in ace_json/scripts, in the order the
        game runs them."""
        from util.ace import rv2json

        return rv2json.script_names(Path(root))

    def rpgmaker_prepare(self, source, options, data_path=None, log=None):
        """Prepares a game's RPG Maker files for translation, in one write
        to the game. A VX Ace game is first converted as Set up's Convert Ace
        data does, while it lacks ace_json or still reads an archive beside
        Game.exe, since Assistant-led has no Set up."""
        from util.ace.actions import archive_in_root
        from util.project_preparation import rpgmaker_layout

        from .game_write import write_game
        from .guided import ace_converted, convert_ace

        layout = rpgmaker_layout(source)
        if (
            layout
            and layout["engine"] == "ACE"
            and (archive_in_root(Path(source)) or not ace_converted(source))
        ):
            convert_ace(source, log or (lambda _line: None))
        with write_game(source, log=log or (lambda _line: None)) as game:
            # Formatting changes a VX Ace game's exports, which it reads once
            # packed into Data.
            game.watch(data_path or "ace_json")
            return self._prepare(source, options, data_path, log)

    def install_gameupdate(self, source, log=None):
        """Installs GameUpdate's files in a game of an engine whose patches
        GameUpdate installs (GAMEUPDATE_ENGINES), in one write to the game;
        an RPG Maker game gets them from its preparation. DazedTL writes the
        game's config once the files are there, as for RPG Maker."""
        from util.len_patch_scope import setup_files
        from util.project_preparation import install_gameupdate

        from .game_write import write_game

        root = Path(source)
        engine = self.detect(root)
        if engine in {"MVMZ", "ACE"}:
            raise ValueError(
                "An RPG Maker game gets GameUpdate from operation rpgmaker_prepare."
            )
        if engine not in GAMEUPDATE_ENGINES:
            raise ValueError(
                "GameUpdate installs only in games DazedTL recognizes as WOLF, "
                "Unity or TyranoScript, whose patches it was checked with."
            )
        from util.paths import game_git_set_up

        if refusal := gameupdate_refusal(
            engine, _tracked(root) if game_git_set_up(root) else ()
        ):
            raise ValueError(refusal)
        log = log or (lambda _line: None)
        readme = not (root / "README.md").exists()
        with write_game(root, log=log, pack=False) as game:
            copied, errors = install_gameupdate(root, wolf=engine == "WOLF", log=log)
            game.wrote(*setup_files(root), *(["README.md"] if readme else []))
            if errors:
                raise ValueError("GameUpdate copy failed. " + "; ".join(errors))
        return {"engine": engine, "files": copied}

    def rpgmaker_prepare_release(self, staged, options, baseline, log=None):
        """Prepares a new version's copy staged for a game update, which is
        not the game, as the game's files were: `baseline` names the files
        of the game as its current version's baseline was made, or is None
        when no record says. Forge is DazedTL's, not the release's, so the
        copy gets it only when that baseline had it; otherwise the update
        would read Set up's install as the release's change and bring it
        into the game. A VX Ace release is
        converted as Set up converts the game, setting its archive aside,
        and the exports formatting changes are packed into its Data, as
        preparing the game packs them."""
        from util.forge import installer as forge
        from util.project_preparation import rpgmaker_layout

        log = log or (lambda _line: None)
        layout = rpgmaker_layout(staged)
        if not layout or layout["engine"] != "ACE":
            target = forge.status(Path(staged)).get("target")
            had_forge = bool(target) and (
                baseline is None
                or Path(target).relative_to(staged).as_posix() in baseline
            )
            return self._prepare(staged, options, None, log, forge=had_forge)
        return self._convert_ace(
            staged, lambda: self._prepare(staged, options, None, log), log
        )

    def _convert_ace(self, staged, prepare, log):
        """Converts a staged VX Ace copy as Set up converts the game: its
        archive extracted and set aside, Data converted into ace_json, which
        `prepare` formats, and the formatting changes packed into its Data,
        as preparing the game packs them."""
        from util.ace import actions

        from dazedtl.translation.release import packing_inputs, packing_target

        actions.run(Path(staged), "ace_extract", log)
        native = {"source": str(staged), "data": str(Path(staged) / "ace_json")}
        before = packing_inputs(native)
        result = prepare()
        after = packing_inputs(native)
        if changed := {packing_target(n) for n in after if before.get(n) != after[n]}:
            actions.run(Path(staged), "ace_pack", log, only=changed)
        return result

    def _prepare(self, source, options, data_path, log, *, forge=True):
        from desktop.backend.cli_environment import public_values
        from util.len_translation import setup_forge
        from util.project_preparation import prepare_rpgmaker

        values = public_values(self.profile)
        path = self.profile / "translation-public-settings.env"
        write_bytes(
            path,
            "\n".join(
                key + "=" + json.dumps(str(value))
                for key, value in values.items()
                if key.casefold() not in {"key", "secret", "api_key"}
            ).encode("utf-8"),
        )
        result = prepare_rpgmaker(source, data_path=data_path, env_path=path, log=log)
        result["forge"] = (
            setup_forge(self.project(source, options))
            if forge
            else {"status": "skipped", "message": "The game's baseline has no Forge."}
        )
        return result

    def rpgmaker_prepare_patch(self, patch, source, log=None):
        """Gives a staged patch the preparation the game's own files had, or
        returns None when it needs an assistant's. A VX Ace patch that brings
        the game's archive is converted as Set up converted the game, so the
        archive never sits beside the translated Data, which the game would
        then no longer read; finishing the update keeps it for patches."""
        from util.ace import rgssad
        from util.dazedformat import format_json_files
        from util.project_preparation import prepare_rpgmaker_patch, rpgmaker_layout

        layout = rpgmaker_layout(source)
        if not layout or layout["engine"] != "ACE":
            return prepare_rpgmaker_patch(patch, source, log=log)
        if not rgssad.archives(Path(patch)):
            return None
        log = log or (lambda _line: None)

        def prepare():
            count, errors = format_json_files(Path(patch) / "ace_json", log=log)
            if errors:
                raise ValueError("Patch data formatting failed. " + "; ".join(errors))
            return {"engine": "ACE", "formatted_json": count}

        return self._convert_ace(patch, prepare, log)

    def release_inspect(self, source, release):
        from util.version_update.release_layout import inspect_release

        return asdict(inspect_release(source, release))

    def release_stage(self, source, copy, kind, destination):
        """Lays a release's private copy out as the game in `destination`, as
        `kind` or as its files suggest, and returns the layout it used."""
        from util.version_update.release_layout import inspect_release, stage_release

        layout = inspect_release(source, copy).layout(kind)
        stage_release(source, copy, destination, layout)
        return asdict(layout)

    def git_setup(self, source, options, version, original, untranslated):
        from util.len_git import setup_git

        from .game_write import write_game

        # A baseline adds DazedTL's rules to the game's .gitignore and
        # .gitattributes, which are never ace_json.
        with write_game(source, pack=False):
            return setup_git(
                self.project(source, options),
                original_game=Path(original) if original else None,
                version=version,
                current_is_untranslated=untranslated,
            )

    def line_layout(self, root):
        """The Line widths a game's RPG Maker text is fitted to: the ones
        saved for it, or its engine's stock ones, as text QA reads them, and
        the language it is translated into."""
        from util.rpgmaker_rewrap import Layout

        return Layout.of_game(root)

    def word_spacing(self, root):
        """The rule for joining a translation's words in plugin commands and
        note tags, and whether the game's main font draws U+00A0."""
        from util.project_scanner import find_data_folder
        from util.word_spacing import RULE, nbsp_drawn

        data, engine = find_data_folder(root)
        if data is None or engine != "MVMZ":
            nbsp = {"drawn": None, "unread": "This game is not RPG Maker MV or MZ."}
        else:
            nbsp = nbsp_drawn(data)
        return {"rule": RULE, "nbsp": nbsp}

    def save_line_widths(self, root, widths):
        """Saves the Line widths an assistant measured for a game, where
        Guided keeps them too, and returns them as saved."""
        from util.game_settings import (
            load_game_wrap_widths,
            save_game_wrap_widths,
            valid_line_widths,
        )

        if not valid_line_widths(widths) or widths["faceWidth"] > widths["width"]:
            raise ValueError(
                "Give the Line widths as whole numbers: width, faceWidth (at most "
                "width), listWidth and noteWidth from 20 to 300, and messageRows "
                "from 1 to 20."
            )
        save_game_wrap_widths(root, widths)
        return load_game_wrap_widths(root)

    def line_widths(self, root, widths):
        """Saves an assistant's measured Line widths and fits the text
        write_rpgmaker already wrote to them, in one write to the game."""
        from .game_write import write_game

        with write_game(root) as game:
            return {
                "widths": self.save_line_widths(root, widths),
                **self.fit_rpgmaker(root, game),
            }

    def fit_rpgmaker(self, root, game):
        """Fits the text write_rpgmaker wrote into a game's data to its Line
        widths as they are now, and says what changed and what still does
        not fit; text written before the widths changed was fitted to the
        old ones."""
        from util.len_originals import fit_game
        from util.project_preparation import rpgmaker_layout

        layout = rpgmaker_layout(Path(root))
        if layout is None or not Path(layout["data_path"]).is_dir():
            return {"fitted": 0, "files": [], "misfits": [], "misfit_count": 0}
        result = fit_game(layout["data_path"], self.line_layout(root))
        data = Path(layout["data_path"]).resolve().relative_to(game.root)
        game.wrote(*((data / name).as_posix() for name in result["files"]))
        return result

    def write_rpgmaker(self, root, source, translated, output):
        """Writes staged game JSON with its sources kept, fitted to the
        game's Line widths."""
        from util.len_originals import write_rpgmaker_json

        from dazedtl.translation.files import read_json

        from .game_write import write_game

        read_json(source)
        read_json(translated)
        relative = Path(output).resolve().relative_to(Path(root).resolve())
        with write_game(root, paths=[relative.as_posix()]) as game:
            result = write_rpgmaker_json(
                Path(source), Path(translated), Path(output), self.line_layout(root)
            )
            game.wrote(relative.as_posix())
        return {**result, "path": str(result["path"])}

    def rebase_rpgmaker(
        self, root, source, translated, output, expected_original_commit
    ):
        from util.len_originals import fit_written, preserve_originals
        from util.rpgmaker_blocks import NOTES
        from util.version_update.git_workflow import _run_git

        from dazedtl.translation.files import read_json

        from .game_write import write_game

        root, source, output = Path(root), Path(source), Path(output)
        if output.suffix.lower() != ".json":
            raise ValueError(
                "Source metadata rebasing only supports RPG Maker data JSON."
            )
        relative = output.relative_to(root).as_posix()
        commit = _run_git(root, "rev-parse", "original").stdout.strip()
        if not expected_original_commit or commit != expected_original_commit:
            raise ValueError(
                "Review the current original commit before rebasing source metadata."
            )
        original_blob = _run_git(
            root, "rev-parse", commit + ":" + relative
        ).stdout.strip()
        supplied_blob = _run_git(
            root, "hash-object", "--no-filters", str(source)
        ).stdout.strip()
        if original_blob != supplied_blob:
            raise ValueError(
                "Source bytes must match this exact file on the reviewed original branch."
            )

        def without_metadata(value):
            if isinstance(value, dict):
                return {
                    key: without_metadata(item)
                    for key, item in value.items()
                    if key not in NOTES
                }
            return (
                [without_metadata(item) for item in value]
                if isinstance(value, list)
                else value
            )

        result = preserve_originals(
            read_json(source),
            without_metadata(read_json(translated)),
            filename=output.name,
        )
        fit = fit_written(result, output.name, self.line_layout(root))
        with write_game(root, paths=[relative]) as game:
            if _run_git(root, "rev-parse", "original").stdout.strip() != commit:
                raise ValueError("The original branch changed during source rebasing.")
            write_json(output, result)
            game.wrote(relative)
        return {
            "path": str(output),
            "original_commit": commit,
            "original_blob": original_blob,
            **fit,
        }

    def runtime_paths(self, manifest):
        from util.len_patch_scope import patch_manifest

        return list(patch_manifest(manifest))

    def audit_scope(self, source, manifest):
        from util.len_patch_scope import patch_manifest, repository_files, scope_ignore
        from util.paths import GAME_REPOSITORY_METADATA, portable_game_files
        from util.version_update.git_workflow import unfinished_bootstrap

        from .game_write import write_game

        # Reuse the patch helper's rejection of secrets, work records and unsafe paths.
        entries = patch_manifest(manifest)
        ignore = Path(source) / ".gitignore"
        # Only a baseline about to be made, or made again, takes these rules.
        if not (Path(source) / ".git").exists() or unfinished_bootstrap(source):
            if ignore.is_symlink():
                raise ValueError("The game's ignore file cannot be a symbolic link.")
            previous = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
            with write_game(source, pack=False):
                # The baseline keeps the rule files, as each checkpoint does,
                # so its glossary never goes without the archive rule.
                write_bytes(
                    ignore,
                    scope_ignore(
                        previous, set(entries) | repository_files(Path(source))
                    ).encode("utf-8"),
                )
        allowed = (
            set(entries)
            | set(GAME_REPOSITORY_METADATA)
            | set(portable_game_files(source))
        )
        with system.staging_folder(
            tempfile.gettempdir(), "dazedtl-scope-"
        ) as temporary:
            _git(
                ["init", "--bare", "--quiet", temporary],
                "prepare the scope check",
            )
            listed = _git(
                [
                    "--git-dir",
                    temporary,
                    "--work-tree",
                    str(source),
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                "list the game's files",
            )
            actual = {item.decode("utf-8") for item in listed.split(b"\0") if item}
        unexpected = sorted(actual - allowed)
        if unexpected:
            raise ValueError(
                "Review the game's ignore rules before Git setup. Unscoped files would be tracked: "
                + ", ".join(unexpected[:8])
            )
        # A patch can add files the original lacks, such as a mod loader;
        # declared as translation-only additions, they may not exist yet.
        missing = sorted(
            relative
            for relative, row in entries.items()
            if relative not in actual
            and not ("original_sha256" in row and row["original_sha256"] is None)
        )
        if missing:
            raise ValueError(
                "The patch manifest lists files the game lacks or ignores: "
                + ", ".join(missing[:8])
                + '. Review the ignore rules, or declare files the patch adds as {"files": {"<path>": {"original_sha256": null}}}.'
            )

    def checkpoint(self, source, change, named=()):
        """Saves the changes waiting in the game's patch as one checkpoint,
        letting the `named` files it lacks into it."""
        from .checkpoint_commits import save

        return save(source, change, named)

    def outside_edits(self, source):
        """Saves the changes made outside DazedTL as their own checkpoint,
        when the game's Git is set up."""
        from .checkpoint_commits import outside_edits

        if _takes_checkpoints(source):
            outside_edits(source)

    def pending_checkpoint(self, source, change, named=()):
        """Saves the changes waiting in the game's patch as one checkpoint,
        letting the `named` files it lacks into it, when the game's Git is
        set up, as at an assistant's phase report."""
        from .checkpoint_commits import save

        if _takes_checkpoints(source):
            save(source, change, named)

    def _patch_scope(self, source, stamped=True):
        """The files the translation branch tracks, DazedTL's own among them,
        GameUpdate's config when the patch leaves it out and the public
        version it stamps otherwise (release.public_version); without
        `stamped`, the translation's files whatever the patch would stamp."""
        from util.gameupdate_config import CONFIG
        from util.paths import is_game_tool_file

        from dazedtl.translation.release import public_version

        tracked = _tracked(source)
        # DazedTL's own files, such as the game's glossary and a VX Ace
        # game's ace_json, are committed but never reach players, whatever
        # an older .gitattributes says.
        own = set(filter(is_game_tool_file, tracked))
        if not stamped:
            return tracked, own, set(), None
        stamp = public_version(source) if CONFIG in tracked else None
        omitted = {CONFIG} & tracked if not stamp else set()
        return tracked, own, omitted, stamp

    def patch_files(self, source, manifest, *, stamped=True):
        """What a patch ZIP built now holds, for its review: the files the
        translation branch tracks and those the runtime manifest adds at the
        build's checkpoint, without DazedTL's own, and whether it stamps the
        public version; without `stamped`, every file of the translation,
        GameUpdate's config too, which a clean game ZIP decides on itself."""
        tracked, own, omitted, stamp = self._patch_scope(Path(source), stamped)
        named = set(self.runtime_paths(manifest))
        return {
            "files": sorted((tracked | named) - own - omitted),
            "omitted": sorted(omitted),
            "updater_stamp": stamp,
        }

    def package(self, source, options, manifest, destination, *, original_names=()):
        """A local ZIP of the committed patch, the files the translation
        branch tracks, in `destination`, named by its commit. GameUpdate's
        config follows release.public_version. `original_names` lists the
        original game's files a backup holds, for plugins Git's inventory
        leaves out."""
        import zipfile

        from util.ace.actions import patch_archive
        from util.len_patch_scope import patch_manifest, patch_refusal
        from util.paths import GAME_TOOL_ARCHIVE_EXCLUDES
        from util.version_update.git_workflow import _run_git

        from dazedtl.translation.release import player_permissions

        source = Path(source)
        status = self.git_status(source, options)
        if (
            not status["worktree_clean"]
            or status["current_branch"] != status["translation_branch"]
        ):
            raise ValueError(
                "The game changed while its patch was saved, or is off the "
                "translation branch; build the patch again."
            )
        tracked, own, omitted, patch_sha = self._patch_scope(source)
        missing = sorted(set(patch_manifest(manifest)) - tracked)
        if missing:
            raise ValueError(
                "The patch lacks files its runtime manifest lists: "
                + ", ".join(missing[:8])
                + "."
            )
        if refusal := patch_refusal(source, tracked - own, original_names):
            raise ValueError(refusal)
        # Players update a patch that carries GameUpdate with it.
        if "gameupdate/patch.sh" in tracked and (
            refusal := gameupdate_refusal(self.detect(source), tracked - own)
        ):
            raise ValueError(refusal)
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / (status["translation_commit"] + ".zip")
        temporary = output.with_suffix(".zip.tmp")
        rebuilt = output.with_suffix(".archive.tmp")
        try:
            _run_git(
                source,
                "archive",
                "--format=zip",
                "--output=" + str(temporary),
                "HEAD",
                "--",
                ".",
                *(
                    ":(exclude)" + path
                    for path in [*GAME_TOOL_ARCHIVE_EXCLUDES, *sorted(omitted)]
                ),
            )
            # An encrypted game reads only its archive, so the patch carries
            # the archive rebuilt with the translated files.
            game_archive = patch_archive(source, rebuilt, tracked)
            if patch_sha or game_archive:
                with zipfile.ZipFile(
                    temporary, "a", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    if patch_sha:
                        archive.writestr(
                            "gameupdate/previous_patch_sha.txt", patch_sha + "\n"
                        )
                        player_permissions(
                            archive.getinfo("gameupdate/previous_patch_sha.txt")
                        )
                    if game_archive:
                        archive.write(
                            rebuilt, game_archive, compress_type=zipfile.ZIP_STORED
                        )
                        player_permissions(archive.getinfo(game_archive))
            system.replace(temporary, output)
        finally:
            system.unlink(temporary, ignore_errors=True)
            system.unlink(rebuilt, ignore_errors=True)
        packaged = sorted(
            (tracked - omitted - own) | ({game_archive} if game_archive else set())
        )
        write_json(
            output.with_suffix(".json"),
            {
                "commit": status["translation_commit"],
                "game_version": status["original_version"],
                "files": packaged,
                "updater_stamp": bool(patch_sha),
            },
        )
        return {
            "path": str(output),
            "commit": status["translation_commit"],
            "game_version": status["original_version"],
            "files": len(packaged),
            "updater_stamp": bool(patch_sha),
            # The game's files it was built from, which freshness compares.
            "paths": [name for name in packaged if name in tracked],
        }

    def version(self, source, action, options):
        from util import version_update as git

        def value(result):
            return {
                **asdict(result),
                **(
                    {"complete": result.complete} if hasattr(result, "complete") else {}
                ),
            }

        if action == "preview":
            from util.version_update.text_changes import text_changes

            # The update keeps its own commits, after edits made outside
            # DazedTL have theirs.
            self.outside_edits(source)
            preview = git.preview_official_update(
                source,
                options["official"],
                options["version"],
                previous_official_game=options.get("baseline") or None,
                patch_overlay=options.get("patch_overlay", False),
            )
            try:
                text = asdict(text_changes(source, preview))
            except git.GitWorkflowError, OSError, ValueError:
                # The line view only informs the review; the update itself
                # stands on the file comparison.
                text = None
            from .guided import describe_ace_update

            result = {**asdict(preview), "text": text}
            describe_ace_update(source, options["official"], result)
            return result
        if action == "apply":
            preview = options["preview"]
            return value(
                git.apply_official_update(
                    source,
                    options["official"],
                    options["version"],
                    expected_tree=preview["proposed_tree"],
                    expected_original_commit=preview["original_commit"],
                    expected_translation_commit=preview["translation_commit"],
                    expected_asset_manifest=preview["proposed_asset_manifest"],
                    previous_official_game=options.get("baseline") or None,
                    expected_baseline_asset_manifest=preview["baseline_asset_manifest"],
                    patch_overlay=options.get("patch_overlay", False),
                    prepared_record=options.get("prepared_record"),
                )
            )
        if action == "continue":
            return value(git.continue_with_official(source, options.get("release")))
        if action == "abort":
            return value(git.abort_update(source))
        raise ValueError("Unknown version-update action.")

    def applied_update(self, source):
        """The version an official update applied, once it is finished on the
        translated branch, for the task that translates its text. The
        original branch records each update once it is applied, whatever the
        translated branch's later checkpoints."""
        from util.version_update import inspect_repository, version_history

        root = Path(source).expanduser().resolve()
        status = inspect_repository(root)
        latest = next(iter(version_history(root)), None)
        if not (
            status.repo_root
            and status.translation_exists
            and status.current_branch == status.translation_branch
            and not status.pending_cherry_pick
            and not status.asset_sync_pending
            and latest
            and latest.kind == "update"
        ):
            raise ValueError(
                "Finish the official update on the registered translated branch before copying this task."
            )
        return latest.version


def finish_context(context, batch, language, users=None):
    """Completes a batch's compiled request context (util/len_translation's
    request_context) with what its plan batch adds: the language pair, its
    scene note, who uses a battle message's skill and its field template."""
    from util.skills import ctx

    from dazedtl.languages import JAPANESE, active_source

    reading = active_source()
    context["target_language"] = language
    # A Japanese source, every request's before the source became a
    # setting, keeps its requests' shape.
    if reading != JAPANESE:
        context["source_language"] = reading
    context["scene_context"] = batch.get("scene_context", "")
    if users:
        context["skill_users"] = users
    if batch.get("instruction_key"):
        context["request_instructions"] = ctx(
            batch["instruction_key"],
            language=language,
            context=batch.get("source_context", ""),
        )
    context.pop("request_sha256", None)
    context["request_sha256"] = digest(context)
    return context


def request_payload(request, configuration):
    """The provider request an Assistant-led run sends for a logical request
    (translation/requests.logical_request) under a run's configuration."""
    from util.translation import buildClaudeRequest, buildOpenAIRequest

    from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS
    from dazedtl.settings.providers import response_format

    strict_router = configuration.get("openrouterStructuredOutputs")
    if strict_router is not None and (
        strict_router != STRUCTURED_OUTPUTS or configuration["provider"] != "openrouter"
    ):
        raise ValueError(
            "This run's structured-output policy is invalid or unsupported."
        )
    context = request["context"]
    # Lines go by short keys under the run's line-key policy; see
    # requests.provider_view.
    view = provider_view(request, configuration)
    instructions = [context["request_instructions"], view["reply"]]
    references = context.get("reference_translations", {})
    if references.get("matches"):
        instructions.append(
            "Advisory reference translations; the current source and approved glossary take precedence:\n"
            + json.dumps(references["matches"], ensure_ascii=False)
        )
    if view["constraints"]:
        instructions.append(
            "Per-unit constraints (protected tokens must retain their source occurrence counts):\n"
            + json.dumps(view["constraints"], ensure_ascii=False)
        )
    if view["scene_context"]:
        instructions.append(
            "Scene and runtime substitution context (not translatable source):\n"
            + view["scene_context"]
        )
    shared = {
        "system": context["system"],
        "user": view["user"],
        "history": context["preceding_japanese_source_context"],
        "formatType": "json",
        "model": configuration["model"],
        "numLines": None,
        "vocab_text": context["glossary"] + "\n" + context["sfx_reference"],
        "request_instructions": "\n\n".join(text for text in instructions if text),
    }
    if configuration["protocol"] == "anthropic":
        # Batch requests use the five-minute cache too; see translateAI.
        params: dict[str, Any] = buildClaudeRequest(**shared)
        params.pop("temperature", None)
        params["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": output_schema(view["sources"]),
            }
        }
    else:
        params = buildOpenAIRequest(
            **shared,
            penalty=0,
            api_provider=configuration["protocol"],
            api_url=configuration["endpoint"],
        )
        params["response_format"] = response_format(
            configuration["protocol"],
            configuration["endpoint"],
            configuration["model"],
            output_schema(view["sources"]),
            "translation",
        )
    if configuration["provider"] == "openrouter":
        if strict_router:
            params = request_parameters.structured_output(
                params,
                output_schema(view["sources"]),
                name="translation",
                live=configuration["mode"] != "batch",
            )
        params = request_parameters.host_routing(
            params, configuration.get("openrouterHost", "")
        )
        if strict_router and configuration["mode"] == "batch":
            params = request_parameters.batch_routing(
                params, configuration.get("openrouterBatch")
            )
    params = request_parameters.provider_defaults(
        params, configuration.get("generationParameters")
    )
    return request_parameters.completion_budget(
        params, configuration.get("maxOutputTokens")
    )


def google_batch_client(secret):
    from google import genai

    # A lost create response is reconciled through our journal, never repeated
    # underneath it by the SDK's default retry loop.
    return genai.Client(api_key=secret, http_options={"retry_options": {"attempts": 1}})


class TranslationProvider:
    """One isolated worker's provider connection; no SDK-level paid retries."""

    @provider_errors
    def __init__(self, configuration, secret, *, receipt_root=None):
        from .provider_responses import install

        install()
        from util.batch_providers import get_client

        self.configuration = configuration
        # One of several provider SDK clients, chosen by configuration.
        self.client: Any
        if (
            configuration.get("provider", configuration["protocol"]) == "openrouter"
            and configuration["mode"] == "batch"
        ):
            from .openrouter_batch import Client

            self.provider = "openrouter"
            self.client = Client(
                secret,
                api_url=configuration["endpoint"],
                policy=configuration.get("openrouterBatch"),
                receipt_root=receipt_root,
            )
            self.google = None
            return
        # A saved Batch names its provider as the protocol.
        identity = configuration.get("provider", configuration["protocol"])
        self.provider = (
            configuration["protocol"]
            if configuration["protocol"] in {"anthropic", "gemini"}
            else "kimi"
            if identity == "kimi"
            else "openai"
        )
        self.client = get_client(
            self.provider,
            api_key=secret,
            api_url=configuration["endpoint"],
            max_retries=0,
        )
        extra: dict[str, Any] = {"timeout": 45, "max_retries": 0}
        if configuration.get("organization") and self.provider != "anthropic":
            extra["organization"] = configuration["organization"]
        self.client = self.client.with_options(**extra)
        self.google = (
            google_batch_client(secret)
            if self.provider == "gemini" and configuration["mode"] == "batch"
            else None
        )

    @provider_errors
    def live(self, params):
        from types import SimpleNamespace

        from util.batch_providers import execute_live_request

        from dazedtl.translation.refusals import refusal_reason, refused

        responses = []

        def capture(create):
            def call(**kwargs):
                response = create(**kwargs)
                responses.append(response)
                return response

            return call

        def capture_stream(stream):
            @contextmanager
            def call(**kwargs):
                with stream(**kwargs) as events:
                    yield events
                    responses.append(events.get_final_message())

            return call

        # The native normalizer drops refusal metadata. Observe the response
        # without changing SDK state or making an additional request.
        client = (
            SimpleNamespace(
                messages=SimpleNamespace(
                    stream=capture_stream(self.client.messages.stream)
                )
            )
            if self.provider == "anthropic"
            else SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=capture(self.client.chat.completions.create)
                    )
                )
            )
        )
        result = execute_live_request(self.provider, params, client=client)
        if responses and refused(responses[-1]):
            result["refusal"] = refusal_reason(responses[-1]) or True
        return result

    @provider_errors
    def submit(self, requests):
        from util.batch_providers import submit_batch

        return submit_batch(
            self.provider, requests, client=self.client, google_client=self.google
        )

    def input_tokens(self, params):
        from util.translation import _estimate_openai_batch_input_tokens

        return _estimate_openai_batch_input_tokens(params)

    @provider_errors
    def status(self, identity):
        from util.batch_providers import retrieve_batch

        value = retrieve_batch(self.provider, identity, client=self.client)
        value.pop("raw", None)
        value.pop("errors", None)
        return value

    @provider_errors
    def cancel(self, identity):
        from util.batch_providers import cancel_batch

        value = cancel_batch(self.provider, identity, client=self.client)
        return {"id": identity, "status": value["api_status"]}

    @provider_errors
    def collect(self, identity, mapping):
        from util.batch_providers import download_results

        results, errors, usage = download_results(
            self.provider,
            identity,
            mapping,
            client=self.client,
            google_client=self.google,
        )
        return results, [str(item[0]) for item in errors], usage

    @provider_errors
    def collect_terminal(self, identity, mapping):
        """Keep successful paid rows from a canceled/expired compatible Batch job."""
        from util.batch_providers import read_openai_results

        if self.provider in {"anthropic", "openrouter"}:
            return self.collect(identity, mapping)
        batch = self.client.batches.retrieve(identity)
        results, errors, usage = read_openai_results(
            self.provider,
            getattr(batch, "output_file_id", None),
            getattr(batch, "error_file_id", None),
            mapping,
            client=self.client,
            google_client=self.google,
        )
        return results, [str(item[0]) for item in errors], usage


def _wolf_documents(wolfdawn, root, workdir, names):
    """WolfDawn's strings-extract documents for a Wolf game's data: archives
    are unpacked first, and a file WolfDawn can't read is returned as None.
    The engine reads a loose file before the same file in an archive, so an
    archived file with a loose copy is left to the loose one."""
    archived = {name for name in names if wolfdawn.is_archive(root / name)}
    loose = set(names) - archived
    sources = []
    for index, name in enumerate(names):
        path = root / name
        if name in archived:
            target = workdir / "wolf" / str(index)
            if not wolfdawn.unpack_all([path], target).ok:
                raise ValueError("WolfDawn could not unpack " + name)
            parent = Path(name).parent.as_posix()
            for inner in sorted(target.rglob("*")):
                relative = inner.relative_to(target).as_posix()
                shadow = relative if parent == "." else f"{parent}/{relative}"
                if inner.is_file() and shadow not in loose:
                    sources.append((f"{name}/{relative}", inner))
        else:
            sources.append((name, path))
    documents = []
    for index, (name, path) in enumerate(sources):
        lowered = path.name.casefold()
        if not lowered.endswith((".mps", ".project")) and lowered not in {
            "commonevent.dat",
            "game.dat",
        }:
            continue
        output = workdir / "extract" / f"{index}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        if wolfdawn.strings_extract(path, output).ok and output.is_file():
            documents.append((name, json.loads(output.read_text(encoding="utf-8-sig"))))
        else:
            documents.append((name, None))
    return documents
