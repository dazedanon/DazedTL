"""Len's maintained skills and engine helpers behind the migration boundary."""

from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from functools import wraps

from dazedtl.storage import write_json, write_bytes
from dazedtl.translation.files import digest
from dazedtl.translation.requests import output_schema


class ProviderFailure(RuntimeError):
    def __init__(self, operation, error):
        status = getattr(error, "status_code", None)
        self.status_code = status if type(status) is int else None
        detail = "HTTP " + str(status) if self.status_code else type(error).__name__
        super().__init__(operation + " failed (" + detail + "). No automatic paid retry was made.")


def provider_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ProviderFailure:
            raise
        except Exception as error:
            raise ProviderFailure(function.__name__, error) from error
    return call


class TranslationEngine:
    def __init__(self, source, profile):
        self.source = Path(source).resolve(strict=True)
        self.profile = Path(profile).resolve()
        if not (self.source / "util/len_translation.py").is_file():
            raise ValueError("Choose the preserved DazedMTLTool checkout.")
        if str(self.source) not in sys.path:
            sys.path.insert(0, str(self.source))

    @contextmanager
    def context(self):
        from util.paths import runtime_data_profile
        # Engine helpers may print. Never mix them into the application's RPC stream.
        with open(os.devnull, "w") as sink, runtime_data_profile(self.profile), redirect_stdout(sink):
            yield

    def project(self, source, options):
        from util.len_translation import LenProject
        return LenProject(Path(source).resolve(), mode="local" if options["mode"] == "agent" else "api",
                          **{key: value for key, value in options.items() if key != "mode"})

    def detect(self, source):
        from util.project_preparation import rpgmaker_layout
        layout = rpgmaker_layout(source)
        if layout:
            return layout["engine"]
        root = Path(source)
        if any(root.glob("*.wolf*")) or (root / "Data/BasicData/CommonEvent.dat").is_file():
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
        from util.len_translation import shared_context, _prepare_local_work, _validate_skill, BUNDLED_SKILL
        from util.len_progress import initialize_progress
        from util.skills import load_project_setup, load_generic_project_setup
        from util.project_preparation import rpgmaker_layout
        project = self.project(source, options)
        _validate_skill(BUNDLED_SKILL)
        shared = shared_context(project)
        _prepare_local_work(project)
        layout = rpgmaker_layout(source)
        setup = load_project_setup("rpgmaker", prepend=(
            "Selected game: " + json.dumps(str(project.game_root)) + "\n"
            "Reviewed RPG Maker JSON directory: " + json.dumps(str(layout["data_path"])) + "\n"
            "For Ace, complete decryption and conversion before applying the RPG Maker methodology. "
            "Collect source speakers without paid API calls in Agent mode."
        )) if layout else load_generic_project_setup(source)
        write_json(project.workspace / "context.json", shared)
        write_bytes(project.workspace / "setup.md", setup.encode("utf-8"))
        initialize_progress(project)
        return {"skill": str(BUNDLED_SKILL / "SKILL.md"), "setup": str(project.workspace / "setup.md")}

    def progress(self, source, options, report=None, *, verify=False):
        from util.len_progress import read_progress, update_progress
        project = self.project(source, options)
        return update_progress(project, report) if report is not None else read_progress(project, check_hashes=verify)

    def compile(self, source, options, plan, language):
        from util.len_translation import request_contexts
        from util.skills import ctx
        batches = [{key: item for key, item in batch.items()
                    if key in {"id", "sources", "speakers", "source_context", "instruction_key"}} for batch in plan["batches"]]
        compiled = request_contexts(self.project(source, options), batches)
        for original, result in zip(plan["batches"], compiled):
            context = result["context"]
            # Match the shared engine's target-language substitution without touching source text.
            context["system"] = context["system"].replace("English", language)
            context["target_language"] = language
            context["scene_context"] = original.get("scene_context", "")
            if original.get("instruction_key"):
                context["request_instructions"] = ctx(original["instruction_key"], language=language,
                                                       context=original.get("source_context", ""))
            context.pop("request_sha256", None)
            context["request_sha256"] = digest(context)
        return compiled, self.compiler_fingerprint()

    def compiler_fingerprint(self):
        from util.len_api import _compiler_fingerprint
        from dazedtl.translation import requests, compilation
        return digest({"engine": _compiler_fingerprint(), "bridge": digest(Path(__file__).read_bytes()),
                       "contract": digest(Path(requests.__file__).read_bytes()),
                       "compilation": digest(Path(compilation.__file__).read_bytes())})

    def payload(self, request, configuration):
        from util.translation import buildClaudeRequest, buildOpenAIRequest
        context = request["context"]
        instructions = [context["request_instructions"],
                        "Return only a JSON object mapping each supplied source ID to its translated string. "
                        "Do not add, remove, merge, or rename IDs. Speaker labels and surrounding source are context only."]
        references = context.get("reference_translations", {})
        if references.get("matches"):
            instructions.append("Advisory reference translations; the current source and approved glossary take precedence:\n" +
                                json.dumps(references["matches"], ensure_ascii=False))
        if request["constraints"]:
            instructions.append("Per-unit constraints (protected tokens must retain their source occurrence counts):\n" +
                                json.dumps(request["constraints"], ensure_ascii=False))
        if context.get("scene_context"):
            instructions.append("Scene and runtime substitution context (not translatable source):\n" + context["scene_context"])
        shared = dict(system=context["system"], user=context["user"], history=context["preceding_japanese_source_context"],
                      formatType="json", model=configuration["model"], numLines=None,
                      vocab_text=context["glossary"] + "\n" + context["sfx_reference"],
                      request_instructions="\n\n".join(text for text in instructions if text))
        if configuration["protocol"] == "anthropic":
            params = buildClaudeRequest(**shared, cache_ttl="1h" if configuration["mode"] == "batch" else "5m")
            params.pop("temperature", None)
            params["output_config"] = {"format": {"type": "json_schema", "schema": output_schema(request["sources"])}}
        else:
            params = buildOpenAIRequest(**shared, penalty=0, api_provider=configuration["protocol"], api_url=configuration["endpoint"])
            params["response_format"] = ({"type": "json_object"} if configuration["provider"] in {"custom", "mistral"} else
                                         {"type": "json_schema", "json_schema": {"name": "translation", "strict": True,
                                                                                 "schema": output_schema(request["sources"])}})
        return params

    def token_count(self, text):
        import tiktoken
        return len(tiktoken.encoding_for_model("gpt-4").encode(text, disallowed_special=()))

    def batch_supported(self, configuration):
        from util.batch_providers import detect_batch_provider
        return detect_batch_provider(configuration["model"], api_url=configuration["endpoint"], api_provider=configuration["protocol"])

    def batch_limits(self, configuration):
        from util.batch_providers import batch_limits
        from util.translation import _openai_batch_token_limit
        from urllib.parse import urlsplit
        native_openai = configuration["protocol"] == "openai" and urlsplit(configuration["endpoint"]).hostname == "api.openai.com"
        return [*batch_limits(self.batch_supported(configuration)), _openai_batch_token_limit() if native_openai else None]

    def input_tokens(self, parameters):
        from util.translation import _estimate_openai_batch_input_tokens
        return _estimate_openai_batch_input_tokens(parameters)

    def git_status(self, source, options):
        from util.len_git import git_status
        return git_status(self.project(source, options))

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
            if separator and relative in wanted and not relative.startswith(".dazedtl/") and len(fields) == 3 and fields[1] == "blob" and fields[0] != "120000":
                result[relative] = fields[2]
        return result

    def verify_bindings(self, source, bindings):
        if self.source_bindings(source, list(bindings)) != bindings:
            raise ValueError("The untranslated source baseline changed. Prepare a new request plan for this game version.")

    def original_bytes(self, source, blob):
        import re
        if not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40,64}", blob):
            raise ValueError("Choose a verified original source blob.")
        return subprocess.run(["git", "-C", str(source), "cat-file", "blob", blob],
                              check=True, capture_output=True, timeout=30).stdout

    def error_message(self, error):
        from util.version_update import GitWorkflowError
        if isinstance(error, (ValueError, OSError, GitWorkflowError, ProviderFailure)):
            return str(error)
        return "Operation needs attention (" + type(error).__name__ + "). Saved receipts were retained."

    def rpgmaker_prepare(self, source, options, data_path=None, log=None):
        from util.project_preparation import prepare_rpgmaker
        from util.len_translation import setup_forge
        from desktop.backend.cli_environment import public_values
        values = public_values(self.profile)
        path = self.profile / "translation-public-settings.env"
        write_bytes(path, "\n".join(key + "=" + json.dumps(str(value)) for key, value in values.items()
                                      if key.casefold() not in {"key", "secret", "api_key"}).encode("utf-8"))
        result = prepare_rpgmaker(source, data_path=data_path,
                                 env_path=path, log=log)
        result["forge"] = setup_forge(self.project(source, options))
        return result

    def git_setup(self, source, options, version, original, untranslated):
        from util.len_git import setup_git
        return setup_git(self.project(source, options), original_game=Path(original) if original else None,
                         version=version, current_is_untranslated=untranslated)

    def write_rpgmaker(self, source, translated, output):
        from util.len_originals import write_rpgmaker_json
        from dazedtl.translation.files import read_json
        read_json(source)
        read_json(translated)
        return str(write_rpgmaker_json(Path(source), Path(translated), Path(output)))

    def rebase_rpgmaker(self, root, source, translated, output, expected_original_commit):
        from util.len_originals import preserve_originals
        from util.version_update.git_workflow import _run_git
        from dazedtl.translation.files import read_json
        root, source, output = Path(root), Path(source), Path(output)
        if output.suffix.lower() != ".json":
            raise ValueError("Source metadata rebasing only supports RPG Maker data JSON.")
        relative = output.relative_to(root).as_posix()
        commit = _run_git(root, "rev-parse", "original").stdout.strip()
        if not expected_original_commit or commit != expected_original_commit:
            raise ValueError("Review the current original commit before rebasing source metadata.")
        original_blob = _run_git(root, "rev-parse", commit + ":" + relative).stdout.strip()
        supplied_blob = _run_git(root, "hash-object", "--no-filters", str(source)).stdout.strip()
        if original_blob != supplied_blob:
            raise ValueError("Source bytes must match this exact file on the reviewed original branch.")
        def without_metadata(value):
            if isinstance(value, dict):
                return {key: without_metadata(item) for key, item in value.items() if key != "_original"}
            return [without_metadata(item) for item in value] if isinstance(value, list) else value
        result = preserve_originals(read_json(source), without_metadata(read_json(translated)), filename=output.name)
        if _run_git(root, "rev-parse", "original").stdout.strip() != commit:
            raise ValueError("The original branch changed during source rebasing.")
        write_json(output, result)
        return {"path": str(output), "original_commit": commit, "original_blob": original_blob}

    def git_scope(self, source, options, manifest, original, dry_run):
        from util.len_patch_scope import sync_patch_scope
        return sync_patch_scope(self.project(source, options), manifest, original_game=Path(original) if original else None, dry_run=dry_run)

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
            subprocess.run(["git", "init", "--bare", "--quiet", temporary], check=True, capture_output=True)
            result = subprocess.run(["git", "--git-dir", temporary, "--work-tree", str(source),
                                     "ls-files", "--others", "--exclude-standard", "-z"], check=True, capture_output=True)
            actual = {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}
        unexpected = sorted(actual - allowed)
        if unexpected:
            raise ValueError("Review the game's ignore rules before Git setup. Unscoped files would be tracked: " + ", ".join(unexpected[:8]))
        missing = set(entries) - actual
        if missing:
            raise ValueError("The patch manifest contains missing or ignored files. Review the manifest and ignore rules.")

    def commit(self, source, message):
        from util.version_update.git_workflow import _run_git, _TOOL_NAME, _TOOL_EMAIL
        if not isinstance(message, str) or not message.strip() or len(message) > 500 or "\0" in message:
            raise ValueError("Use a short checkpoint message.")
        if _run_git(Path(source), "diff", "--cached", "--quiet", check=False).returncode:
            flags = []
            for key, fallback in (("user.name", _TOOL_NAME), ("user.email", _TOOL_EMAIL)):
                if not _run_git(Path(source), "config", "--get", key, check=False).stdout.strip():
                    flags += ["-c", key + "=" + fallback]
            _run_git(Path(source), *flags, "commit", "-m", message)
        return _run_git(Path(source), "rev-parse", "HEAD").stdout.strip()

    def package(self, source, options, manifest, destination):
        from util.len_patch_scope import patch_manifest
        from util.version_update.git_workflow import _run_git
        from util.release_package import _release_patch_sha, ReleasePackageError
        import zipfile
        source = Path(source)
        status = self.git_status(source, options)
        if not status["worktree_clean"] or status["current_branch"] != status["translation_branch"]:
            raise ValueError("Commit reviewed changes on the translation branch before packaging.")
        allowed = set(patch_manifest(manifest)) | {".gitignore", ".gitattributes", "README.md"}
        tracked = set(_run_git(source, "ls-files", "-z").stdout.rstrip("\0").split("\0"))
        if tracked - allowed or set(patch_manifest(manifest)) - tracked:
            raise ValueError("The committed files do not match the reviewed runtime patch manifest.")
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / (status["translation_commit"] + ".zip")
        temporary = output.with_suffix(".zip.tmp")
        try:
            patch_sha = _release_patch_sha(source) if "gameupdate/patch-config.txt" in allowed else None
        except ReleasePackageError:
            # Local delivery does not require publishing a remote branch.
            patch_sha = None
        try:
            _run_git(source, "archive", "--format=zip", "--output=" + str(temporary), "HEAD")
            if patch_sha:
                with zipfile.ZipFile(temporary, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("gameupdate/previous_patch_sha.txt", patch_sha + "\n")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        write_json(output.with_suffix(".json"), {"commit": status["translation_commit"], "game_version": status["original_version"],
                                                "files": sorted(tracked), "updater_stamp": bool(patch_sha)})
        return {"path": str(output), "commit": status["translation_commit"], "game_version": status["original_version"],
                "files": len(tracked), "updater_stamp": bool(patch_sha)}

    def version(self, source, action, options):
        from util import version_update as git
        def value(result):
            return {**asdict(result), **({"complete": result.complete} if hasattr(result, "complete") else {})}
        if action == "preview":
            return asdict(git.preview_official_update(source, options["official"], options["version"],
                          previous_official_game=options.get("baseline") or None, patch_overlay=options.get("patch_overlay", False)))
        if action == "apply":
            preview = options["preview"]
            return value(git.apply_official_update(source, options["official"], options["version"],
                expected_tree=preview["proposed_tree"], expected_original_commit=preview["original_commit"],
                expected_translation_commit=preview["translation_commit"], expected_asset_manifest=preview["proposed_asset_manifest"],
                previous_official_game=options.get("baseline") or None, expected_baseline_asset_manifest=preview["baseline_asset_manifest"],
                patch_overlay=options.get("patch_overlay", False)))
        if action == "continue":
            return value(git.continue_with_official(source))
        if action == "abort":
            return value(git.abort_update(source))
        if action == "handoff":
            from util.version_update.handoff import post_update_handoff
            return post_update_handoff(source)
        raise ValueError("Unknown version-update action.")


class TranslationProvider:
    """One isolated worker's provider connection; no SDK-level paid retries."""
    @provider_errors
    def __init__(self, configuration, secret):
        from util.batch_providers import get_client, _google_client
        self.configuration = configuration
        self.provider = configuration["protocol"] if configuration["protocol"] in {"anthropic", "gemini"} else "openai"
        self.client = get_client(self.provider, api_key=secret, api_url=configuration["endpoint"], max_retries=0)
        extra = {"timeout": 45, "max_retries": 0}
        if configuration.get("organization") and self.provider != "anthropic":
            extra["organization"] = configuration["organization"]
        self.client = self.client.with_options(**extra)
        self.google = _google_client(secret) if self.provider == "gemini" and configuration["mode"] == "batch" else None

    @provider_errors
    def live(self, params):
        from util.batch_providers import execute_live_request
        return execute_live_request(self.provider, params, client=self.client)

    @provider_errors
    def submit(self, requests):
        from util.batch_providers import submit_batch
        return submit_batch(self.provider, requests, client=self.client, google_client=self.google)

    @provider_errors
    def status(self, identity):
        from util.batch_providers import retrieve_batch
        value = retrieve_batch(self.provider, identity, client=self.client)
        value.pop("raw", None)
        value.pop("errors", None)
        return value

    @provider_errors
    def collect(self, identity, mapping):
        from util.batch_providers import download_results
        results, errors, usage = download_results(self.provider, identity, mapping, client=self.client, google_client=self.google)
        return results, [str(item[0]) for item in errors], usage

    @provider_errors
    def collect_terminal(self, identity, mapping):
        """Keep successful paid rows from a canceled/expired compatible Batch job."""
        from util.batch_providers import _download_file_text, _openai_result
        if self.provider == "anthropic":
            return self.collect(identity, mapping)
        batch = self.client.batches.retrieve(identity)
        results, errors, usage = {}, [], {"input_tokens": 0, "output_tokens": 0}
        for name in ("output_file_id", "error_file_id"):
            content = _download_file_text(self.provider, getattr(batch, name, None), client=self.client, google_client=self.google)
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

    @provider_errors
    def cancel(self, identity):
        from util.batch_providers import cancel_batch
        result = cancel_batch(self.provider, identity, client=self.client)
        result.pop("raw", None)
        return result
