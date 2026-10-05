"""Versioned MV/MZ speaker fixes without changing frozen engine signatures."""

import ast
from functools import wraps
import inspect
import re


def standalone_speaker(module, name):
    # Re-exported [Name] lines are implicit nameplates, unlike explicit 101
    # fields. Apply discovery's prose rejection before routing them to the
    # short-name prompt. Keep resolved runtime names and short Latin labels.
    display = module._speaker_display_name(name)
    if re.fullmatch(r"\\[nNvV]\[\d+\]", display):
        return True
    if module._has_japanese_text(display):
        return module._is_plausible_speaker(display)
    return bool(len(display) <= 40 and len(display.split()) <= 4
                and re.fullmatch(r"[^\W\d_][\w '\u2019\-]*", display))


def message_end(module, commands, start, allowed):
    end = module._text_group_end(commands, start, allowed)
    nameplate = re.fullmatch(rf'\[({module.SPEAKER_BRACKET_INNER})\]\s*', module._param_source(commands[start], 0))
    if nameplate and standalone_speaker(module, nameplate[1]):
        # An English [Name] line still needs the following Japanese dialogue
        # in the eligibility preview; the native name handler advances to it.
        return end
    # Each retained scalar original owns an independently translated unit.
    # In particular, rejecting a former [prose] nameplate must not merge it
    # into the already-translated line after it and discard either original.
    return next((index - 1 for index in range(start + 1, end + 1)
                 if module._scalar_original(commands[index]) is not None), end)


def corrected_parser(native):
    # searchCodes keeps speaker state in local variables inside its two-pass
    # writer. Adapt only these five syntax nodes, leaving every other parser
    # branch and the engine's on-disk bytes intact. Fail before execution if
    # the bundled parser changes instead of silently applying a partial fix.
    source, start = inspect.getsourcelines(native)
    tree = ast.parse(''.join(source))
    targets = [ast.parse(value).body[0] for value in (
        'if "code" in codeList[i] and codeList[i]["code"] == 101 and '
        '(CODE101 or AUTONAMEPOPUP101 or SPEAKER_PARSE_MODE): pass',
        'currentName = _101_speaker_name(_101_name_current(codeList[i], isVar))',
        'if inlineFmtMatch: pass',
        'previewEnd = _text_group_end(codeList, i, (401, 405, -1))',
    )]
    target_shapes = [ast.dump(node.test if isinstance(node, ast.If) else node) for node in targets]
    group_shape = ast.dump(ast.parse('codeList[i + 1]["code"] in [401, 405, -1]', mode='eval').body)
    found = [0, 0, 0, 0, 0]
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and ast.dump(node.test) == target_shapes[0]:
            node.body.insert(0, ast.copy_location(ast.parse('speaker = ""').body[0], node))
            found[0] += 1
        elif isinstance(node, ast.Assign) and ast.dump(node) == target_shapes[1]:
            # Chained assignment retains the current display name even when
            # skip-translated prevents getSpeaker from running below it.
            node.targets.append(ast.copy_location(ast.Name(id='speaker', ctx=ast.Store()), node))
            found[1] += 1
        elif isinstance(node, ast.If) and ast.dump(node.test) == target_shapes[2]:
            node.test = ast.copy_location(ast.parse(
                'inlineFmtMatch and _dazedtl_standalone_speaker(inlineFmtMatch.group(1))', mode='eval').body, node.test)
            found[2] += 1
        elif isinstance(node, ast.Assign) and ast.dump(node) == target_shapes[3]:
            node.value.func.id = '_dazedtl_message_end'
            found[3] += 1
        elif isinstance(node, ast.While) and isinstance(node.test, ast.BoolOp) and ast.dump(node.test.values[0]) == group_shape:
            node.test.values.append(ast.copy_location(ast.parse(
                '_scalar_original(codeList[i + 1]) is None', mode='eval').body, node.test))
            found[4] += 1
    if found != [1, 1, 1, 1, 1]:
        raise RuntimeError('The bundled MV/MZ speaker parser changed. Update its compatibility adapter.')
    ast.fix_missing_locations(tree)
    ast.increment_lineno(tree, start - 1)
    namespace = {}
    exec(compile(tree, native.__code__.co_filename, 'exec'), native.__globals__, namespace)
    return wraps(native)(namespace[native.__name__])


def configure(module, enabled):
    previous = getattr(module, '_dazedtl_speaker_context', None)
    if not enabled:
        if previous:
            module.searchCodes = previous
            del module._dazedtl_speaker_context
        return
    if previous:
        return
    native = module.searchCodes
    corrected = corrected_parser(native)
    module._dazedtl_standalone_speaker = lambda name: standalone_speaker(module, name)
    module._dazedtl_message_end = lambda commands, start, allowed: message_end(module, commands, start, allowed)
    module._dazedtl_speaker_context = native
    module.searchCodes = corrected
