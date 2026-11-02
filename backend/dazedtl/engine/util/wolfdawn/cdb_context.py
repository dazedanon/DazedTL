"""Resolve ``\\cdb[type:row:field]`` display values for translation context.

WolfDawn's normal strings extraction intentionally contains only translatable
strings.  A runtime CDB lookup can therefore point at a value (most notably an
actor name) that is absent from ``CDataBase.project.json``.  ``wolf db-json``
exposes the complete database, so the workflow stores a small hidden lookup
sidecar and the translation module can show the real value to the model while
still restoring the original control code for injection.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from util import wolfdawn
from util import system

SIDECAR_NAME = ".cdb-context.json"
SIDECAR_KIND = "wolf-cdb-context"


def lookup_from_db_json(data: dict[str, Any]) -> dict[str, str]:
    """Return ``{"type:row:field": value}`` from a ``wolf db-json`` document."""
    lookups: dict[str, str] = {}
    for type_doc in data.get("types") or []:
        if not isinstance(type_doc, dict):
            continue
        type_id = type_doc.get("id")
        fields = {
            field.get("id"): field.get("name")
            for field in type_doc.get("fields") or []
            if isinstance(field, dict)
        }
        for row in type_doc.get("rows") or []:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            values = row.get("values") or {}
            if not isinstance(values, dict):
                continue
            for field_id, field_name in fields.items():
                if not isinstance(field_name, str):
                    continue
                value = values.get(field_name)
                if isinstance(value, str) and value.strip():
                    lookups[f"{type_id}:{row_id}:{field_id}"] = value
    return lookups


def write_sidecar(project_path: str | Path, sidecar_path: str | Path, log_fn=None) -> bool:
    """Dump a complete CDB once, reduce it to display strings, and save a sidecar."""
    project = Path(project_path)
    sidecar = Path(sidecar_path)
    if not project.is_file():
        return False
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    try:
        with system.staging_folder(tempfile.gettempdir(), "dazedtl-cdb-") as temp_dir:
            full_json = Path(temp_dir) / "CDataBase.full.json"
            result = wolfdawn.db_json(project, full_json, log_fn=log_fn)
            if not result.ok or not full_json.is_file():
                return False
            data = json.loads(full_json.read_text(encoding="utf-8"))
        payload = {
            "kind": SIDECAR_KIND,
            "source": str(project),
            "lookups": lookup_from_db_json(data),
        }
        sidecar.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        return True
    except (OSError, ValueError, TypeError):
        return False


