"""Preserved image operations, without importing a GUI or provider modules."""

import hashlib
import os
import sys
import tempfile
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path

from dazedtl.storage import write_bytes
from dazedtl.translation.files import project_path, read_json


class ImageCompatibility:
    def __init__(self, backend):
        self.backend = backend

    def context(self):
        return (
            self.backend.context()
            if hasattr(self.backend, "context")
            else nullcontext()
        )

    def profile(self, root, engine, image_root=""):
        from util.image_manager import (
            detect_image_engine,
            get_image_profile,
            normalize_generic_image_root,
        )

        if engine == "MVMZ":
            identity, image_root = "rpgmaker_mvmz", ""
        else:
            identity = "generic"
            if not image_root:
                found = detect_image_engine(root)
                image_root = str(found.suggested_image_root or "")
            if image_root:
                image_root = (
                    normalize_generic_image_root(root, image_root)
                    .relative_to(root)
                    .as_posix()
                )
        value = get_image_profile(identity)
        return {
            "id": identity,
            "label": value.label,
            "imageRoot": image_root,
            "context": value.translation_skill_context,
            "supported": bool(identity == "rpgmaker_mvmz" or image_root),
            "reason": "Choose a folder containing loose PNGs."
            if not image_root and identity == "generic"
            else "",
        }

    @staticmethod
    def _walk(root, stopped):
        if not root.is_dir() or root.is_symlink():
            return
        for directory, folders, names in os.walk(root, followlinks=False):
            if stopped():
                return
            folders[:] = sorted(
                name
                for name in folders
                if name not in {".git", ".dazedtl", "__pycache__"}
                and not (Path(directory) / name).is_symlink()
            )
            for name in sorted(names):
                if stopped():
                    return
                path = Path(directory) / name
                if not path.is_symlink() and path.is_file():
                    yield path

    def inventory(self, root, profile, stopped=lambda: False):
        """Stream metadata instead of constructing the Qt manager's complete asset list."""
        from util.rpgmaker_images import resolve_content_root

        base = resolve_content_root(root) if profile["id"] == "rpgmaker_mvmz" else root
        image_root = (
            base / "img"
            if profile["id"] == "rpgmaker_mvmz"
            else root / profile["imageRoot"]
        )
        editable_base = root / ".dazedtl/images" / base.relative_to(root)
        for path in self._walk(image_root, stopped):
            extension = path.suffix.casefold()
            if extension not in (
                {".png", ".png_", ".rpgmvp"}
                if profile["id"] == "rpgmaker_mvmz"
                else {".png"}
            ):
                continue
            logical = path.with_suffix(".png")
            identity = logical.relative_to(base).as_posix()
            yield {
                "id": identity,
                "path": identity,
                "profile": profile["id"],
                "runtime": path.relative_to(root).as_posix(),
                "destination": path.relative_to(root).as_posix(),
                "editable": (editable_base / logical.relative_to(base))
                .relative_to(root)
                .as_posix(),
                "encrypted": extension != ".png",
            }
        workspace_root = editable_base / image_root.relative_to(base)
        for path in self._walk(workspace_root, stopped):
            if path.suffix.casefold() != ".png":
                continue
            identity = path.relative_to(editable_base).as_posix()
            # Merging is done by the index; editable-only assets remain visible and blocked.
            yield {
                "id": identity,
                "path": identity,
                "profile": profile["id"],
                "runtime": "",
                "destination": (base / identity).relative_to(root).as_posix(),
                "editable": path.relative_to(root).as_posix(),
                "encrypted": False,
            }

    def key(self, root, profile):
        if profile["id"] != "rpgmaker_mvmz":
            return None
        from util.rpgmaker_images import read_encryption_key

        try:
            return read_encryption_key(root)
        except (ValueError, OSError, KeyError, TypeError):
            return None

    def source_bytes(self, root, asset, key):
        path = project_path(root, asset["runtime"])
        if path.stat().st_size > 128_000_000:
            raise ValueError("Image exceeds the supported 128 MB size limit.")
        value = path.read_bytes()
        if asset["encrypted"]:
            if key is None:
                raise ValueError(
                    "The encryption key is unavailable. Restore System.json before preparing this asset."
                )
            from util.rpgmaker_images import decrypt_image_bytes

            value = decrypt_image_bytes(value, key)
        return value

    def original_bytes(self, root, row, key):
        """Adopt the Qt publisher's preserved original without changing its backup."""
        backup = project_path(
            root, ".dazedtl/image_backups/" + row["runtime"], exists=False
        )
        original = backup if backup.exists() else project_path(root, row["runtime"])
        if original.stat().st_size > 128_000_000:
            raise ValueError(
                "The preserved original exceeds the supported image size limit."
            )
        raw = original.read_bytes()
        plain = raw
        if row["encrypted"]:
            if key is None:
                raise ValueError(
                    "The encryption key is required to verify this preserved original."
                )
            from util.rpgmaker_images import decrypt_image_bytes

            plain = decrypt_image_bytes(raw, key)
        return (
            plain,
            raw,
            "Preserved Qt image backup"
            if backup.exists()
            else "Runtime source before image preparation",
        )

    @staticmethod
    def _asset(root, row):
        from util.image_manager import ImageAsset

        runtime = project_path(root, row["runtime"]) if row.get("runtime") else None
        return ImageAsset(
            row["id"],
            Path(row["id"]),
            project_path(root, row["editable"], exists=False),
            runtime if row["encrypted"] else None,
            runtime if not row["encrypted"] else None,
            row["profile"],
        )

    @staticmethod
    def _manifest(root):
        path = project_path(root, ".dazedtl/image_manager/manifest.json", exists=False)
        if path.exists():
            value = read_json(path)
            if (
                not isinstance(value, dict)
                or value.get("version") != 1
                or not isinstance(value.get("assets"), dict)
            ):
                raise ValueError(
                    "The image baseline manifest is invalid. Preserve it and resolve it before changing images."
                )

    def prepare(self, root, profile, rows, key, progress=lambda _: None):
        from util.image_manager import make_profile_assets_editable

        self._manifest(root)
        with self.context():
            result = make_profile_assets_editable(
                profile["id"],
                root,
                [self._asset(root, row) for row in rows],
                key,
                progress=progress,
            )
        return self._result(root, result)

    def apply(self, root, profile, rows, key, progress=lambda _: None):
        from util.image_manager import prepare_profile_assets_for_patch

        self._manifest(root)
        auxiliary = [
            project_path(root, relative, exists=False)
            for relative in (".gitignore", ".dazedtl/image_manager/manifest.json")
        ]
        previous = {
            path: path.read_bytes() if path.exists() else None for path in auxiliary
        }
        try:
            # Freeze the approved bytes outside editable copies before the preserved
            # publisher reads them. Concurrent assistant writes cannot change this batch.
            stage = project_path(
                root, ".dazedtl/image_manager/guided/stage/placeholder", exists=False
            ).parent
            stage.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="reviewed-", dir=stage
            ) as temporary:
                frozen = []
                for row in rows:
                    raw = project_path(root, row["editable"]).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != row["candidateHash"]:
                        raise ValueError(
                            "An included candidate changed after review. Nothing was applied."
                        )
                    if (
                        hashlib.sha256(
                            project_path(root, row["runtime"]).read_bytes()
                        ).hexdigest()
                        != row["sourceHash"]
                    ):
                        raise ValueError(
                            "An included runtime source changed after review. Nothing was applied."
                        )
                    staged = Path(temporary) / row["id"]
                    write_bytes(staged, raw)
                    frozen.append(
                        self._asset(
                            root,
                            {**row, "editable": staged.relative_to(root).as_posix()},
                        )
                    )
                with self.context():
                    result = prepare_profile_assets_for_patch(
                        profile["id"], root, frozen, key, progress=progress
                    )
            if result.errors:
                self._restore_auxiliary(previous, result.errors)
            return self._result(root, result)
        except Exception:
            self._restore_auxiliary(previous, [])
            raise

    @staticmethod
    def _restore_auxiliary(previous, errors):
        for path, value in previous.items():
            try:
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    write_bytes(path, value)
            except OSError:
                errors.append(
                    "Image patch metadata rollback failed; inspect the saved baseline and ignore rules."
                )

    @staticmethod
    def _result(root, result):
        value = asdict(result)
        for key in ("patch_files", "gitignore_files"):
            value[key] = [str(Path(path).relative_to(root)) for path in value[key]]
        return value

    def skill(self, root, profile):
        """Read skill templates without context migration or other game writes."""
        source = Path(self.backend.source)
        from util.paths import SKILLS_DIR, runtime_data_file

        path = runtime_data_file(
            SKILLS_DIR / "image_translation.md", self.backend.workspace
        )
        value = path.read_text(encoding="utf-8")
        folder = root / ".dazedtl/images"
        from desktop.backend.guidance import documents

        glossary = documents(root)["glossary"]["path"]
        replacements = {
            "{{ENGINE_NAME}}": profile["label"],
            "{{ENGINE_CONTEXT}}": profile["context"],
            "{{GAME_ROOT}}": str(root),
            "{{EDITABLE_IMAGES_FOLDER}}": str(folder),
            "{{VOCAB_FILE}}": glossary,
            "{{IMAGE_TOOL_PYTHON}}": str(Path(sys.executable).resolve()),
            "{{IMAGE_INPAINT_CLI}}": str(source / "scripts/image_inpaint.py"),
        }
        for name, replacement in replacements.items():
            value = value.replace(name, replacement)
        return value

    def census_reference(self):
        return str(
            Path(self.backend.source)
            / "data/skills/game-translation/references/image-translation.md"
        )

    def output_hash(self, root, row, key):
        raw = project_path(root, row["editable"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["candidateHash"]:
            raise ValueError(
                "The edited image changed before publication was prepared."
            )
        if row["encrypted"]:
            from util.rpgmaker_images import encrypt_image_bytes

            if key is None:
                raise ValueError("The encryption key is required for this image.")
            raw = encrypt_image_bytes(raw, key)
        return hashlib.sha256(raw).hexdigest()

    def restore(self, root, rows):
        """Restore the reviewed exact batch, with rollback and baseline refresh."""
        from util.image_manager import record_asset_baselines

        before, original_bytes = {}, {}
        auxiliary = project_path(
            root, ".dazedtl/image_manager/manifest.json", exists=False
        )
        old_manifest = auxiliary.read_bytes() if auxiliary.exists() else None
        for row in rows:
            target = project_path(root, row["runtime"])
            backup = project_path(root, row["runtimeBackup"])
            raw = backup.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["runtimeBackupHash"]:
                raise ValueError(
                    "An original image backup changed. Nothing was restored."
                )
            current = target.read_bytes()
            if hashlib.sha256(current).hexdigest() != row["sourceHash"]:
                raise ValueError(
                    "A runtime image changed after restore review. Nothing was restored."
                )
            before[target], original_bytes[target] = current, raw
        published = []
        try:
            for row in rows:
                target = project_path(root, row["runtime"])
                write_bytes(target, original_bytes[target])
                published.append(target)
            record_asset_baselines(root, [self._asset(root, row) for row in rows])
        except Exception as exc:  # noqa: BLE001
            errors = ["Restore failed; runtime rollback was attempted: " + str(exc)]
            for path in reversed(published):
                try:
                    write_bytes(path, before[path])
                except OSError:
                    errors.append(
                        "Runtime rollback failed: " + path.relative_to(root).as_posix()
                    )
            self._restore_auxiliary({auxiliary: old_manifest}, errors)
            return {"completed": 0, "errors": errors}
        return {"completed": len(rows), "errors": []}
