"""Len's maintained skills and engine helpers behind the migration boundary."""

import json
import os
import subprocess
import tempfile
from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import Any

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest
from dazedtl.translation.git_status_cache import RepositoryStatusCache
from dazedtl.translation.requests import output_schema

from . import request_parameters
from .openrouter_batch import ResultsUnavailable


def _git(arguments, purpose, timeout=120):
    """Runs Git for its raw output; a failure says what it was for in words."""
    try:
        result = subprocess.run(
            ["git", *arguments], capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Git could not {purpose} within {timeout} seconds.") from exc
    except OSError as exc:
        raise ValueError(f"Git could not {purpose}: {exc.strerror or exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Git could not {purpose}: {detail or f'exit status {result.returncode}'}"
        )
    return result.stdout


class ProviderFailure(RuntimeError):
    def __init__(self, operation, error):
        status = getattr(error, "status_code", None)
        self.status_code = status if type(status) is int else None
        detail = "HTTP " + str(status) if self.status_code else type(error).__name__
        super().__init__(
            operation + " failed (" + detail + "). No automatic paid retry was made."
        )


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


class TranslationEngine:
    def __init__(self, profile):
        from .runtime import activate

        self.source = activate()
        self.profile = Path(profile).resolve()
        self.repository_status = RepositoryStatusCache()

    @contextmanager
    def context(self):
        from util.paths import runtime_data_profile

        # Engine helpers may print. Never mix them into the application's RPC stream.
        with (
            open(os.devnull, "w") as sink,
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

        layout = rpgmaker_layout(source)
        if layout:
            return layout["engine"]
        root = Path(source)
        if (
            any(root.glob("*.wolf*"))
            or (root / "Data/BasicData/CommonEvent.dat").is_file()
        ):
            return "WOLF"
        if (root / "tyrano").is_dir() or (root / "resources/app/tyrano").is_dir():
            return "TyranoScript"
        if any(root.glob("*_Data")):
            return "Unity"
        return "Investigation pending"

    def documents(self, source):
        from desktop.backend.guidance import documents

        return documents(source)

    def document_save(self, source, name, revision, text):
        from desktop.backend.guidance import document_save

        return document_save(source, name, revision, text)

    def valid_document(self, name):
        from desktop.backend.guidance import valid_document_name

        return valid_document_name(name)

    def prepare(self, source, options):
        from util.len_progress import initialize_progress
        from util.len_translation import (
            BUNDLED_SKILL,
            _prepare_local_work,
            _validate_skill,
            shared_context,
        )
        from util.project_preparation import rpgmaker_layout
        from util.skills import load_generic_project_setup, load_project_setup

        project = self.project(source, options)
        _validate_skill(BUNDLED_SKILL)
        shared = shared_context(project)
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
            )
            if layout
            else load_generic_project_setup(source)
        )
        write_json(project.workspace / "context.json", shared)
        write_bytes(project.workspace / "setup.md", setup.encode("utf-8"))
        initialize_progress(project)
        return {
            "skill": str(BUNDLED_SKILL / "SKILL.md"),
            "setup": str(project.workspace / "setup.md"),
        }

    def progress(self, source, options, report=None, *, verify=False):
        from util.len_progress import read_progress, update_progress

        project = self.project(source, options)
        return (
            update_progress(project, report)
            if report is not None
            else read_progress(project, check_hashes=verify)
        )

    def compile(self, source, options, plan, language):
        from util.len_translation import request_contexts
        from util.skills import ctx

        batches = [
            {
                key: item
                for key, item in batch.items()
                if key
                in {"id", "sources", "speakers", "source_context", "instruction_key"}
            }
            for batch in plan["batches"]
        ]
        compiled = request_contexts(self.project(source, options), batches)
        for original, result in zip(plan["batches"], compiled):
            context = result["context"]
            # Match the shared engine's target-language substitution without touching source text.
            context["system"] = context["system"].replace("English", language)
            context["target_language"] = language
            context["scene_context"] = original.get("scene_context", "")
            if original.get("instruction_key"):
                context["request_instructions"] = ctx(
                    original["instruction_key"],
                    language=language,
                    context=original.get("source_context", ""),
                )
            context.pop("request_sha256", None)
            context["request_sha256"] = digest(context)
        return compiled, self.compiler_fingerprint()

    def compiler_fingerprint(self):
        from dazedtl.translation import compilation, requests

        # Retain the compiler's code identity without hashing obsolete prompt
        # copies in its checkout. Actual guidance also binds each logical request.
        engine_files = (
            "util/len_api.py",
            "util/len_translation.py",
            "util/paths.py",
            "util/translation.py",
            "util/skills/__init__.py",
            "util/skills/contexts.py",
            "util/skills/system.py",
            "util/sfx_reference.py",
            "util/vocab.py",
            "util/reference_games.py",
        )
        return digest(
            {
                "engine": {
                    name: digest((self.source / name).read_bytes())
                    for name in engine_files
                },
                "bridge": digest(Path(__file__).read_bytes()),
                "contract": digest(Path(requests.__file__).read_bytes()),
                "compilation": digest(Path(compilation.__file__).read_bytes()),
                "parameters": digest(Path(request_parameters.__file__).read_bytes()),
            }
        )

    def payload(self, request, configuration):
        from util.translation import buildClaudeRequest, buildOpenAIRequest

        from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS

        strict_router = configuration.get("openrouterStructuredOutputs")
        if strict_router is not None and (
            strict_router != STRUCTURED_OUTPUTS
            or configuration["provider"] != "openrouter"
        ):
            raise ValueError(
                "This run's structured-output policy is invalid or unsupported."
            )
        context = request["context"]
        instructions = [
            context["request_instructions"],
            (
                "Return only a JSON object mapping each supplied source ID to its translated string. "
                "Do not add, remove, merge, or rename IDs. Speaker labels and surrounding source are context only."
            ),
        ]
        references = context.get("reference_translations", {})
        if references.get("matches"):
            instructions.append(
                "Advisory reference translations; the current source and approved glossary take precedence:\n"
                + json.dumps(references["matches"], ensure_ascii=False)
            )
        if request["constraints"]:
            instructions.append(
                "Per-unit constraints (protected tokens must retain their source occurrence counts):\n"
                + json.dumps(request["constraints"], ensure_ascii=False)
            )
        if context.get("scene_context"):
            instructions.append(
                "Scene and runtime substitution context (not translatable source):\n"
                + context["scene_context"]
            )
        shared = {
            "system": context["system"],
            "user": context["user"],
            "history": context["preceding_japanese_source_context"],
            "formatType": "json",
            "model": configuration["model"],
            "numLines": None,
            "vocab_text": context["glossary"] + "\n" + context["sfx_reference"],
            "request_instructions": "\n\n".join(text for text in instructions if text),
        }
        if configuration["protocol"] == "anthropic":
            params: dict[str, Any] = buildClaudeRequest(
                **shared, cache_ttl="1h" if configuration["mode"] == "batch" else "5m"
            )
            params.pop("temperature", None)
            params["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": output_schema(request["sources"]),
                }
            }
        else:
            params = buildOpenAIRequest(
                **shared,
                penalty=0,
                api_provider=configuration["protocol"],
                api_url=configuration["endpoint"],
            )
            params["response_format"] = (
                {"type": "json_object"}
                if configuration["provider"] in {"custom", "mistral", "openrouter"}
                else {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "translation",
                        "strict": True,
                        "schema": output_schema(request["sources"]),
                    },
                }
            )
        if configuration["provider"] == "openrouter":
            if strict_router:
                params = request_parameters.structured_output(
                    params,
                    output_schema(request["sources"]),
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

    def token_count(self, text):
        import tiktoken

        return len(
            tiktoken.encoding_for_model("gpt-4").encode(text, disallowed_special=())
        )

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

    def batch_limits(self, configuration):
        if configuration.get("provider") == "openrouter":
            from dazedtl.settings.openrouter import validate_policy

            policy = validate_policy(
                configuration.get("openrouterBatch"), configuration["model"]
            )
            return [policy["max_requests"], policy["max_bytes"] - 4096, None]
        from urllib.parse import urlsplit

        from util.batch_providers import batch_limits
        from util.translation import _openai_batch_token_limit

        native_openai = (
            configuration["protocol"] == "openai"
            and urlsplit(configuration["endpoint"]).hostname == "api.openai.com"
        )
        from dazedtl.settings.preferences import batch_input_tokens

        allowance = batch_input_tokens(configuration.get("batchInputTokens"))
        return [
            *batch_limits(self.batch_supported(configuration) or ""),
            (allowance or _openai_batch_token_limit()) if native_openai else None,
        ]

    def input_tokens(self, parameters):
        from util.translation import _estimate_openai_batch_input_tokens

        return _estimate_openai_batch_input_tokens(parameters)

    def git_status(self, source, options):
        from util.len_git import git_status

        # The UI polls status twice a second while work runs; a full inspection
        # launches a dozen Git processes, which Windows starts slowly.
        project = self.project(source, options)
        return self.repository_status.get(
            (str(project.game_root), digest(options)),
            project.game_root,
            lambda: git_status(project),
        )

    def source_bindings(self, source, paths):
        """Tracked source inputs follow original, so normal English injection is not source drift."""
        from util.version_update.git_workflow import _run_git

        result = {}
        tree = _run_git(Path(source), "ls-tree", "-r", "-z", "original", check=False)
        if tree.returncode:
            return result
        wanted = set(paths)
        for entry in tree.stdout.split("\0"):
            header, separator, relative = entry.partition("\t")
            fields = header.split()
            if (
                separator
                and relative in wanted
                and not relative.startswith(".dazedtl/")
                and len(fields) == 3
                and fields[1] == "blob"
                and fields[0] != "120000"
            ):
                result[relative] = fields[2]
        return result

    def verify_bindings(self, source, bindings):
        if self.source_bindings(source, list(bindings)) != bindings:
            raise ValueError(
                "The untranslated source baseline changed. Prepare a new request plan for this game version."
            )

    def original_bytes(self, source, blob):
        import re

        if not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40,64}", blob):
            raise ValueError("Choose a verified original source blob.")
        return _git(
            ["-C", str(source), "cat-file", "blob", blob],
            "read the game's original files",
            timeout=30,
        )

    def error_message(self, error):
        from util.version_update import GitWorkflowError

        if isinstance(error, (ValueError, OSError, GitWorkflowError, ProviderFailure)):
            return str(error)
        return (
            "Operation failed ("
            + type(error).__name__
            + "). Saved receipts were retained."
        )

    def rpgmaker_prepare(self, source, options, data_path=None, log=None):
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
        result["forge"] = setup_forge(self.project(source, options))
        return result

    def git_setup(self, source, options, version, original, untranslated):
        from util.len_git import setup_git

        return setup_git(
            self.project(source, options),
            original_game=Path(original) if original else None,
            version=version,
            current_is_untranslated=untranslated,
        )

    def write_rpgmaker(self, source, translated, output):
        from util.len_originals import write_rpgmaker_json

        from dazedtl.translation.files import read_json

        read_json(source)
        read_json(translated)
        return str(write_rpgmaker_json(Path(source), Path(translated), Path(output)))

    def rebase_rpgmaker(
        self, root, source, translated, output, expected_original_commit
    ):
        from util.len_originals import preserve_originals
        from util.version_update.git_workflow import _run_git

        from dazedtl.translation.files import read_json

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
                    if key != "_original"
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
        if _run_git(root, "rev-parse", "original").stdout.strip() != commit:
            raise ValueError("The original branch changed during source rebasing.")
        write_json(output, result)
        return {
            "path": str(output),
            "original_commit": commit,
            "original_blob": original_blob,
        }

    def git_scope(self, source, options, manifest, original, dry_run):
        from util.len_patch_scope import sync_patch_scope

        return sync_patch_scope(
            self.project(source, options),
            manifest,
            original_game=Path(original) if original else None,
            dry_run=dry_run,
        )

    def runtime_paths(self, manifest):
        from util.len_patch_scope import patch_manifest

        return list(patch_manifest(manifest))

    def audit_scope(self, source, manifest):
        from util.len_patch_scope import patch_manifest, scope_ignore

        # Reuse the patch helper's rejection of secrets, work records and unsafe paths.
        entries = patch_manifest(manifest)
        ignore = Path(source) / ".gitignore"
        if not (Path(source) / ".git").exists():
            if ignore.is_symlink():
                raise ValueError("The game's ignore file cannot be a symbolic link.")
            previous = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
            write_bytes(ignore, scope_ignore(previous, set(entries)).encode("utf-8"))
        allowed = set(entries) | {".gitignore", ".gitattributes", "README.md"}
        with tempfile.TemporaryDirectory(prefix="dazedtl-scope-") as temporary:
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
        missing = set(entries) - actual
        if missing:
            raise ValueError(
                "The patch manifest contains missing or ignored files. Review the manifest and ignore rules."
            )

    def commit(self, source, message):
        from util.version_update.git_workflow import _TOOL_EMAIL, _TOOL_NAME, _run_git

        if (
            not isinstance(message, str)
            or not message.strip()
            or len(message) > 500
            or "\0" in message
        ):
            raise ValueError("Use a short checkpoint message.")
        if _run_git(
            Path(source), "diff", "--cached", "--quiet", check=False
        ).returncode:
            flags = []
            for key, fallback in (
                ("user.name", _TOOL_NAME),
                ("user.email", _TOOL_EMAIL),
            ):
                if not _run_git(
                    Path(source), "config", "--get", key, check=False
                ).stdout.strip():
                    flags += ["-c", key + "=" + fallback]
            _run_git(Path(source), *flags, "commit", "-m", message)
        return _run_git(Path(source), "rev-parse", "HEAD").stdout.strip()

    def package(self, source, options, manifest, destination):
        import zipfile

        from util.ace.actions import patch_archive
        from util.len_patch_scope import patch_manifest
        from util.release_package import ReleasePackageError, _release_patch_sha
        from util.version_update.git_workflow import _run_git

        source = Path(source)
        status = self.git_status(source, options)
        if (
            not status["worktree_clean"]
            or status["current_branch"] != status["translation_branch"]
        ):
            raise ValueError(
                "Commit reviewed changes on the translation branch before packaging."
            )
        allowed = set(patch_manifest(manifest)) | {
            ".gitignore",
            ".gitattributes",
            "README.md",
        }
        tracked = set(
            _run_git(source, "ls-files", "-z").stdout.rstrip("\0").split("\0")
        )
        if tracked - allowed or set(patch_manifest(manifest)) - tracked:
            raise ValueError(
                "The committed files do not match the reviewed runtime patch manifest."
            )
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / (status["translation_commit"] + ".zip")
        temporary = output.with_suffix(".zip.tmp")
        rebuilt = output.with_suffix(".archive.tmp")
        try:
            patch_sha = (
                _release_patch_sha(source)
                if "gameupdate/patch-config.txt" in allowed
                else None
            )
        except ReleasePackageError:
            # Local delivery does not require publishing a remote branch.
            patch_sha = None
        try:
            _run_git(
                source, "archive", "--format=zip", "--output=" + str(temporary), "HEAD"
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
                    if game_archive:
                        archive.write(
                            rebuilt, game_archive, compress_type=zipfile.ZIP_STORED
                        )
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
            rebuilt.unlink(missing_ok=True)
        packaged = sorted(tracked | ({game_archive} if game_archive else set()))
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
            return asdict(
                git.preview_official_update(
                    source,
                    options["official"],
                    options["version"],
                    previous_official_game=options.get("baseline") or None,
                    patch_overlay=options.get("patch_overlay", False),
                )
            )
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
                )
            )
        if action == "continue":
            return value(git.continue_with_official(source))
        if action == "abort":
            return value(git.abort_update(source))
        if action == "handoff":
            from util.version_update.handoff import post_update_handoff

            return post_update_handoff(source)
        raise ValueError("Unknown version-update action.")


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
        self.provider = (
            configuration["protocol"]
            if configuration["protocol"] in {"anthropic", "gemini"}
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
        from util.batch_providers import _download_file_text, _openai_result

        if self.provider in {"anthropic", "openrouter"}:
            return self.collect(identity, mapping)
        batch = self.client.batches.retrieve(identity)
        results, errors, usage = {}, [], {"input_tokens": 0, "output_tokens": 0}
        for name in ("output_file_id", "error_file_id"):
            content = _download_file_text(
                self.provider,
                getattr(batch, name, None) or "",
                client=self.client,
                google_client=self.google,
            )
            for line in content.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                custom = row.get("custom_id")
                if custom not in mapping:
                    continue
                result, error = _openai_result(row, self.provider)
                if result is not None and not error:
                    results[mapping[custom]] = result
                    usage["input_tokens"] += result.get("prompt_tokens", 0)
                    usage["output_tokens"] += result.get("completion_tokens", 0)
                else:
                    errors.append(custom)
        return results, errors, usage
