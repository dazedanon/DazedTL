"""Retain the outcome of the native, separately approved name translation."""

from functools import lru_cache, wraps
from pathlib import Path
import re

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest, project_path
from .process_view import saved, file_stamp, _verified_digest, _read_cached

RECEIPT = 'dazedtl-speaker-results.json'
GLOSSARY = 'dazedtl-speaker-glossary.txt'


def install(module, root):
    if module is None or not hasattr(module, 'finalizeSpeakerParse'):
        return
    original = getattr(module.finalizeSpeakerParse, '_dazedtl_native', module.finalizeSpeakerParse)
    root = Path(root)

    def record(value):
        # Reporting must not turn a completed paid call into a translation retry.
        try:
            write_json(project_path(root, 'log/' + RECEIPT, exists=False), value)
        except (OSError, ValueError):
            pass

    @wraps(original)
    def finalize():
        names = list(module.pendingSpeakerNames())
        if not names:
            return original()
        value = {'version': 1, 'planHash': digest((root / 'plan.json').read_bytes()),
                 'state': 'running', 'count': len(names)}
        record(value)
        try:
            result = original()
        except BaseException:
            record({**value, 'state': 'failed'})
            raise
        if result is not True:
            record({**value, 'state': 'failed'})
            return result
        try:
            glossary = project_path(root, 'game/.dazedtl/glossary.txt').read_bytes()
            rows = [{'source': name, 'translation': module._vocab_speaker_lookup(name)} for name in names]
            if any(not isinstance(row['translation'], str) or not module._speaker_translation_valid(row['source'], row['translation']) for row in rows):
                raise ValueError('Saved names could not be verified.')
            write_bytes(project_path(root, 'log/' + GLOSSARY, exists=False), glossary)
            record({**value, 'state': 'saved', 'glossaryHash': digest(glossary), 'rows': rows})
        except (OSError, ValueError):
            record({**value, 'state': 'unavailable'})
        return result

    finalize._dazedtl_native = original
    module.finalizeSpeakerParse = finalize


@lru_cache(maxsize=16)
def _glossary_rows(path, stamp):
    # Legacy recovery accepts exact, unambiguous saved entries only. It does
    # not guess aliases, identity, or a translation from the current project.
    rows = {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*(.+?)\s+\(([^()]+)\)(?:\s+-.*)?\s*', line)
        if match:
            source, target = match.groups()
            rows.setdefault(source, set()).add(target)
    return {source: next(iter(targets)) for source, targets in rows.items() if len(targets) == 1}


def read(root, job):
    """Read recorded evidence without preparing, mutating, or submitting work."""
    root = Path(root)
    try:
        value = saved(root, RECEIPT)
        if not isinstance(value, dict):
            raise ValueError('Name result receipt is invalid.')
        names = (job.get('estimate') or {}).get('speakers')
        plan_path = project_path(root, 'plan.json', exists=False)
        if not value and not names and not plan_path.exists():
            return None
        plan = _read_cached(str(plan_path), file_stamp(plan_path))
        if not isinstance(plan, dict):
            raise ValueError('The saved run plan is invalid.')
        if not value and not names and not plan.get('dazedtl_reused_names'):
            return None
        if _verified_digest(str(plan_path), file_stamp(plan_path)) != job.get('plan_hash'):
            raise ValueError('The name result belongs to a changed plan.')
        if value:
            if (value.get('version') != 1 or value.get('planHash') != job.get('plan_hash')
                    or type(value.get('count')) is not int or value['count'] <= 0
                    or value.get('state') not in {'running', 'saved', 'failed', 'unavailable'}):
                raise ValueError('Name result receipt changed.')
            state = value['state']
            if state == 'running' and (job.get('status') not in {'running', 'waiting'} or job.get('phase') not in {'preparing', None}):
                state = 'unavailable'
            if state != 'saved':
                return {'state': state, 'count': value['count'], 'rows': []}
            rows = value.get('rows')
            if (not isinstance(rows, list) or len(rows) != value['count']
                    or any(not isinstance(row, dict) or set(row) != {'source', 'translation'}
                           or any(not isinstance(text, str) or not text for text in row.values()) for row in rows)):
                raise ValueError('Name result mapping changed.')
            if len({row['source'] for row in rows}) != len(rows):
                raise ValueError('Name result sources are duplicated.')
            glossary = project_path(root, 'log/' + GLOSSARY)
            if _verified_digest(str(glossary), file_stamp(glossary)) != value.get('glossaryHash'):
                raise ValueError('The retained name glossary is missing or changed.')
            return {'state': 'saved', 'count': len(rows), 'rows': rows}

        # Existing in-flight workers predate the receipt. Their approved source
        # list plus native save confirmation and retained glossary can still
        # show exact results; approval or a later Batch phase alone cannot.
        if not isinstance(names, list) or not names or not all(isinstance(name, str) and name for name in names):
            return reused_summary(root, job, plan)
        if (job.get('approval') or {}).get('kind') == 'speakers':
            return None
        complete = any('Speaker translations saved to the game glossary.' in line for line in job.get('log', []))
        if complete:
            glossary = project_path(root, 'game/.dazedtl/glossary.txt')
            entries = _glossary_rows(str(glossary), file_stamp(glossary))
            if all(name in entries for name in names):
                return {'state': 'saved', 'count': len(names), 'rows': [{'source': name, 'translation': entries[name]} for name in names]}
        state = 'running' if job.get('status') == 'running' and job.get('phase') == 'preparing' else 'unavailable'
        return {'state': state, 'count': len(names), 'rows': []}
    except (OSError, ValueError, UnicodeError):
        return {'state': 'unavailable', 'count': 0, 'rows': []}


def summary(root, job):
    value = read(root, job)
    return {**value, 'rows': value['rows'][:3]} if value else None


def page(root, job, offset=0):
    if type(offset) is not int or offset < 0:
        raise ValueError('Choose a valid name result page.')
    value = read(root, job)
    if not value or value['state'] != 'saved':
        raise ValueError('Saved name translations could not be verified. Inspect this run’s log for its outcome.')
    return {'rows': value['rows'][offset:offset + 50], 'total': value['count'], 'offset': offset,
            'nextOffset': offset + 50 if offset + 50 < value['count'] else None}


def reusable(candidates):
    """Newest verified wording wins; callers enforce project/language/source ownership."""
    rows = {}
    for root, job in sorted(candidates, key=lambda candidate: (candidate[1].get('created', ''), candidate[1].get('id', '')), reverse=True):
        value = read(root, job)
        if value and value['state'] == 'saved' and not value.get('reused'):
            for row in value['rows']:
                rows.setdefault(row['source'], {**row, 'runId': job['id']})
    return list(rows.values())


def merge_missing(text, rows, parse, aliases, keys, base_separator=''):
    """Append missing names while preserving every current glossary line and note."""
    known = {key for term, _line, _category in parse(text) if isinstance(term, tuple) and len(term) == 2
             for alias in aliases(term[0]) for key in keys(alias)}
    added = []
    for row in rows:
        source, target = row['source'], row['translation']
        source_keys = set(keys(source))
        if (source_keys & known or not source_keys or not source or not target
                or any(character in source + target for character in '\r\n')):
            continue
        added.append(row)
        known.update(source_keys)
    if not added:
        return text, []
    newline = '\r\n' if '\r\n' in text else '\n'
    entries = ''.join(f"{row['source']} ({row['translation']}){newline}" for row in added)
    boundary = text.find(base_separator) if base_separator else -1
    boundary = len(text) if boundary < 0 else boundary
    section = re.search(r'(?m)^[\t ]*#+\s*Speakers\s*\r?\n', text[:boundary])
    if section:
        return text[:section.end()] + entries + text[section.end():], added
    prefix = text[:boundary]
    return prefix + (newline if prefix and not prefix.endswith('\n') else '') + newline + '# Speakers' + newline + entries + newline + text[boundary:], added


def seed(root, plan, rows):
    if not rows:
        return
    from util.translation import parseVocabWithCategories, split_vocab_source_aliases, speaker_source_lookup_keys
    from util.vocab import BASE_SEPARATOR
    root = Path(root)
    path = project_path(root, 'game/.dazedtl/glossary.txt')
    raw = path.read_bytes()
    content, added = merge_missing(raw.decode('utf-8'), rows, parseVocabWithCategories, split_vocab_source_aliases, speaker_source_lookup_keys, BASE_SEPARATOR)
    if added:
        write_bytes(path, content.encode('utf-8'))
        plan['context_hashes']['game/.dazedtl/glossary.txt'] = digest(content.encode('utf-8'))
        plan['dazedtl_reused_names'] = added


def reused_summary(root, job, plan):
    rows = plan.get('dazedtl_reused_names')
    if not rows:
        return None
    if (not isinstance(rows, list) or any(not isinstance(row, dict)
            or not all(isinstance(row.get(key), str) and row[key] for key in ('source', 'translation', 'runId')) for row in rows)):
        return {'state': 'unavailable', 'count': 0, 'rows': []}
    glossary = project_path(root, 'game/.dazedtl/glossary.txt')
    entries = _glossary_rows(str(glossary), file_stamp(glossary))
    if any(entries.get(row['source']) != row['translation'] for row in rows):
        return {'state': 'unavailable', 'count': len(rows), 'rows': []}
    return {'state': 'saved', 'count': len(rows), 'rows': [{key: row[key] for key in ('source', 'translation')} for row in rows], 'reused': True}
