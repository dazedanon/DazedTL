"""Render the API contracts as TypeScript and the shared protocol manifest.

Run through scripts/contracts.mjs, which formats and writes the output.
"""

import hashlib
import json
import sys
import types
import typing
from importlib import import_module

import typing_extensions

from dazedtl.api.contracts.methods import METHODS

MODULES = (
    "common",
    "runs",
    "guided",
    "translation",
    "settings",
    "images",
    "plugins",
    "workspace",
    "methods",
)
PRIMITIVES = {str: "string", int: "number", float: "number", bool: "boolean"}


def declarations():
    """Contract classes and aliases, in module and definition order."""
    for name in MODULES:
        module = import_module(f"dazedtl.api.contracts.{name}")
        for value in vars(module).values():
            if getattr(value, "__module__", None) != module.__name__:
                continue
            if typing_extensions.is_typeddict(value) or isinstance(
                value, typing.TypeAliasType
            ):
                yield value


class Renderer:
    def __init__(self):
        self.names = {value.__name__ for value in declarations()}

    def type(self, value):
        if value in PRIMITIVES:
            return PRIMITIVES[value]
        if value is None or value is type(None):
            return "null"
        if value is object:
            return "unknown"
        if typing_extensions.is_typeddict(value) or isinstance(
            value, typing.TypeAliasType
        ):
            if value.__name__ not in self.names:
                raise TypeError(f"{value.__name__} is not a declared API contract.")
            return value.__name__
        origin, args = typing.get_origin(value), typing.get_args(value)
        if origin is typing.Literal:
            return " | ".join(json.dumps(item) for item in args)
        if origin in (typing.Union, types.UnionType):
            return " | ".join(self.type(item) for item in args)
        if origin is list:
            item = self.type(args[0])
            return f"({item})[]" if " | " in item else f"{item}[]"
        if origin is tuple:
            return "[" + ", ".join(self.type(item) for item in args) + "]"
        if origin is dict:
            key, item = args
            if key is str:
                return f"Record<string, {self.type(item)}>"
            # Literal keys describe a sparse map, such as values per phase.
            return f"Partial<Record<{self.type(key)}, {self.type(item)}>>"
        raise TypeError(f"Unsupported API contract type: {value!r}")

    def field(self, name, value):
        optional = typing.get_origin(value) is typing.NotRequired
        if optional:
            value = typing.get_args(value)[0]
        doc = ""
        if typing.get_origin(value) is typing.Annotated:
            value, *notes = typing.get_args(value)
            doc = "".join(f"  /** {note} */\n" for note in notes)
        return f"{doc}  {name}{'?' if optional else ''}: {self.type(value)};"

    def declaration(self, value):
        if isinstance(value, typing.TypeAliasType):
            return f"export type {value.__name__} = {self.type(value.__value__)};"
        doc = f"/** {value.__doc__} */\n" if value.__doc__ else ""
        bases = [
            base
            for base in getattr(value, "__orig_bases__", ())
            if typing_extensions.is_typeddict(base)
        ]
        inherited = {
            name for base in bases for name in typing_extensions.get_type_hints(base)
        }
        hints = typing_extensions.get_type_hints(value, include_extras=True)
        fields = [
            self.field(name, hint)
            for name, hint in hints.items()
            if name not in inherited
        ]
        extra = getattr(value, "__extra_items__", typing_extensions.NoExtraItems)
        if extra is not typing_extensions.NoExtraItems:
            fields.append(f"  [key: string]: {self.type(extra)};")
        if not fields and not bases:
            return f"{doc}export type {value.__name__} = Record<string, never>;"
        # Object type aliases, unlike interfaces, stay assignable to
        # Record<string, unknown> for generic JSON views.
        body = "{\n" + "\n".join(fields) + "\n}"
        shape = " & ".join([*(base.__name__ for base in bases), body])
        return f"{doc}export type {value.__name__} = {shape};"

    def methods(self):
        rows = "\n".join(
            f"  {name}: {{ request: {self.type(method.request)}; "
            f"response: {self.type(method.response)} }};"
            for name, method in METHODS.items()
        )
        return f"export type RpcContract = {{\n{rows}\n}};"


def render():
    renderer = Renderer()
    parts = [renderer.declaration(value) for value in declarations()]
    source = "\n\n".join([*parts, renderer.methods()]) + "\n"
    methods = {
        name: {"refresh": method.refresh, "duringClose": method.during_close}
        for name, method in METHODS.items()
    }
    # Any contract change gives the renderer and backend a new version, so a
    # stale build is refused instead of exchanging mismatched shapes.
    digest = hashlib.sha256(
        (source + json.dumps(methods, sort_keys=True)).encode()
    ).hexdigest()
    header = (
        "// Generated from backend/dazedtl/api/contracts by scripts/contracts.mjs.\n"
        "// Edit the Python contracts and run that script instead of this file.\n\n"
    )
    return {
        "typescript": header + source,
        "protocol": {"version": digest[:16], "methods": methods},
    }


def main():
    json.dump(render(), sys.stdout)
