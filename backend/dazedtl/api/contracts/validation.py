"""Strict checks of real API values against the contracts, for tests and development.

Values are checked as the JSON the renderer receives, so a field the contracts
omit, a missing required field, or a wrong type fails instead of drifting.
"""

import json
from functools import cache
from typing import TypeAliasType

import typing_extensions
from pydantic import ConfigDict, TypeAdapter, ValidationError

from dazedtl.api.contracts import ContractViolation
from dazedtl.api.contracts.methods import METHODS
from dazedtl.api.contracts.typescript import declarations


@cache
def _close_contracts():
    """Reject undeclared fields, except where a contract allows further keys."""
    for value in declarations():
        if not isinstance(value, TypeAliasType):
            # Open contracts declare their own extra items; without their own
            # config they would inherit "forbid" from the enclosing contract.
            closed = (
                getattr(value, "__extra_items__", typing_extensions.NoExtraItems)
                is typing_extensions.NoExtraItems
            )
            value.__pydantic_config__ = ConfigDict(extra="forbid") if closed else {}


@cache
def _adapters(name):
    _close_contracts()
    method = METHODS[name]
    return TypeAdapter(method.request), TypeAdapter(method.response)


def _check(name, side, adapter, value):
    try:
        adapter.validate_json(json.dumps(value), strict=True)
    except ValidationError as error:
        raise ContractViolation(f"{name} {side}: {error}") from None


def check_request(name, params):
    _check(name, "request", _adapters(name)[0], params)


def check_response(name, value):
    _check(name, "response", _adapters(name)[1], value)
