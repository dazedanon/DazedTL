"""Disable native schema downgrades for runs with frozen strict output policy."""

import ast
import inspect


def configure(translation, enabled):
    configure_batch(translation, enabled)
    if not enabled and not hasattr(translation, 'translateText'):
        return
    native = inspect.unwrap(translation.translateText)
    original = getattr(native, '_dazedtl_schema_code', None)
    if not enabled:
        if original is not None:
            native.__code__ = original
        return
    if original is None:
        source, start = inspect.getsourcelines(native)
        tree = ast.parse(''.join(source))
        # Only the outer API call handlers can initiate native JSON/text
        # fallbacks. Keep errors intact for the evidence and retry guards.
        handlers = [handler for node in tree.body[0].body if isinstance(node, ast.Try)
                    for handler in node.handlers
                    if isinstance(handler.type, ast.Name) and handler.type.id in {'APIStatusError', 'Exception'}]
        if len(handlers) != 2:
            raise RuntimeError('The bundled translation fallback changed. Update its structured-output adapter.')
        for handler in handlers:
            handler.body.insert(0, ast.parse(
                'if formatType == "json" and numLines is not None: raise').body[0])
        ast.fix_missing_locations(tree)
        ast.increment_lineno(tree, start - 1)
        namespace = {}
        exec(compile(tree, native.__code__.co_filename, 'exec'), native.__globals__, namespace)
        native._dazedtl_schema_code = native.__code__
        native._dazedtl_strict_schema_code = namespace[native.__name__].__code__
    # Retain function identity: evidence wrappers and engine consumers may
    # already hold references. On-disk engine bytes and signatures stay intact.
    native.__code__ = native._dazedtl_strict_schema_code


def configure_batch(translation, enabled):
    if not hasattr(translation, '_submit_translation_batches_unlocked'):
        return
    native = inspect.unwrap(translation._submit_translation_batches_unlocked)
    original = getattr(native, '_dazedtl_schema_code', None)
    if not enabled:
        if original is not None:
            native.__code__ = original
        return
    if original is None:
        source, start = inspect.getsourcelines(native)
        tree = ast.parse(''.join(source))
        target = ast.dump(ast.parse('len(requests) >= max_requests', mode='eval').body)
        matches = [node for node in ast.walk(tree) if isinstance(node, ast.BoolOp)
                   and isinstance(node.op, ast.Or) and any(ast.dump(value) == target for value in node.values)]
        if len(matches) != 1:
            raise RuntimeError('The bundled Batch splitter changed. Update its structured-output adapter.')
        # Google derives one schema per provider batch. Split before the
        # existing journaled submission instead of submitting incompatible rows.
        matches[0].values.append(ast.parse(
            'provider == "openrouter" and str(params.get("model", "")).startswith("google/") '
            'and params.get("response_format") != requests[0]["params"].get("response_format")', mode='eval').body)
        ast.fix_missing_locations(tree)
        ast.increment_lineno(tree, start - 1)
        namespace = {}
        exec(compile(tree, native.__code__.co_filename, 'exec'), native.__globals__, namespace)
        native._dazedtl_schema_code = native.__code__
        native._dazedtl_strict_schema_code = namespace[native.__name__].__code__
    native.__code__ = native._dazedtl_strict_schema_code
