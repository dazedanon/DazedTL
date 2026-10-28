"""Deterministic local tooling for AI-helper RPG Maker translation QA.

DazedTL owns inventory, compact bundles, checkpoints, context expansion,
result validation, finding propagation, correction maps, and regression.  The
AI helper only reviews immutable bundle files and writes the documented JSON
result shape; this package never calls a model provider.

The modules form layers, each importing only from the ones before it, so an
import cycle fails at once:

mechanical, pronouns, schema, storage, records, fitting, selection, interface, ledger,
bundles, scope, validation, pace, advance, reopen, findings, editorial,
acceptance, briefs, claims, apply, prepare, rebuild.

A name used only in a lower layer's type hints is imported under
TYPE_CHECKING. util.rpgmaker_qa re-exports what older callers use.
"""
