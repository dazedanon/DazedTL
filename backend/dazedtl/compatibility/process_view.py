"""Read-only, project-owned process evidence and exact retained payloads."""

from functools import lru_cache
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3

from dazedtl.translation.files import digest, read_json, project_path


@lru_cache(maxsize=8)
def _read_cached(path, modified, size):
    return read_json(path, limit=64_000_000)


def saved(root, name):
    path = Path(root) / 'log' / name
    if not path.exists():
        return {}
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Saved process evidence must stay inside the run workspace.')
    stat = path.stat()
    return _read_cached(str(path), stat.st_mtime_ns, stat.st_size)


def evidence_root(root):
    path = Path(root) / 'plan.json'
    if path.is_file():
        plan = read_json(path)
        if plan.get('batch_link'):
            from desktop.backend.batches import batch_root
            return batch_root(root, plan)
    return Path(root)


def ledger(root):
    path = Path(root) / 'log/dazedtl-process.sqlite3'
    if not path.is_file():
        return None
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Saved process evidence cannot follow symbolic links.')
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)


def file_stamp(path):
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=20_000)
def _verified_digest(path, signature):
    return digest(Path(path).read_bytes())


def consumed_files(root):
    """Prove local Batch completion without claiming per-request validation.

    Native cleanup may leave preparation-only ledger rows. Terminal provider
    history plus a bound completed-file receipt settles those old requests;
    a missing/changed output or native mismatch must keep its recovery guard.
    This does not exclude the file from later parsing or translate new text.
    """
    root = Path(root)
    history = saved(evidence_root(root), 'batch_history.json').get('batches', [])
    if not history or not all(batch.get('status') == 'consumed' and batch.get('api_status') in
                             {'completed', 'ended', 'failed', 'expired', 'cancelled', 'canceled'} for batch in history):
        return frozenset()
    try:
        job_path = project_path(root, 'job.json')
        plan_path = project_path(root, 'plan.json')
        job = _read_cached(str(job_path), job_path.stat().st_mtime_ns, job_path.stat().st_size)
        if job.get('mode') != 'batch' or job.get('status') != 'complete' or job.get('plan_hash') != _verified_digest(str(plan_path), file_stamp(plan_path)):
            return frozenset()
        plan = _read_cached(str(plan_path), plan_path.stat().st_mtime_ns, plan_path.stat().st_size)
        if plan.get('mode') != 'batch' or plan.get('batch_link') or set(job.get('files', [])) != set(plan.get('selected', [])):
            return frozenset()
        complete = set(job.get('completed', [])) & set(plan.get('selected', []))
        complete -= set(job.get('errors', {})) | set(job.get('mismatches', {}))
        verified = set()
        for name in complete:
            path = project_path(root, 'translated/' + name, exists=False)
            if path.is_file() and job.get('outputs', {}).get(name) == _verified_digest(str(path), file_stamp(path)):
                verified.add(name)
        return frozenset(verified)
    except (OSError, ValueError, KeyError):
        return frozenset()


def ledger_records(root):
    path = Path(root)/'log/dazedtl-process.sqlite3'
    if not path.is_file():
        return None
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Saved process evidence cannot follow symbolic links.')
    stat = path.stat()
    history = saved(evidence_root(root), 'batch_history.json').get('batches', [])
    consumed = bool(history) and all(batch.get('status') == 'consumed' for batch in history)
    rows = _ledger_records(str(root), (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns), consumed)
    complete = consumed_files(root) if consumed else frozenset()
    return [{**row, 'state': 'saved'} if row['filename'] in complete and row['state'] in {'prepared', 'uncertain', 'received'} else row for row in rows]


@lru_cache(maxsize=8)
def _ledger_records(root, signature, consumed):
    connection = ledger(root)
    if connection is None:
        return None
    with closing(connection):
        names = {row[1] for row in connection.execute('PRAGMA table_info(requests)')}
        fields = ('params', 'state', 'error', 'usage', 'sources', 'filename', 'response')
        rows = connection.execute('SELECT ' + ','.join(name if name in names else 'NULL' for name in fields) + ' FROM requests ORDER BY id').fetchall()
        validated = {}
        if consumed and connection.execute("SELECT 1 FROM sqlite_master WHERE name='validated_items'").fetchone():
            validated = {key: (source, json.loads(response)) for key, source, response in connection.execute('SELECT identity,source,response FROM validated_items')}
    result = []
    for row in rows:
        entry = dict(zip(fields, row))
        for key in ('params', 'error', 'usage', 'sources', 'response'):
            entry[key] = json.loads(entry[key]) if entry[key] is not None else None
        source = source_values(entry['params']) or {}
        keys = entry['sources'] or []
        # Older Batch workers cleared raw responses after consume. Recover only
        # exact native-validated source identities from this same saved run.
        # Never present this local translation as an original provider body.
        if consumed and entry['response'] is None and source and len(keys) == len(source) and all(
                key in validated and validated[key][0] == text for key, text in zip(keys, source.values())):
            entry.update(state='validated', response=[validated[key][1] for key in keys], responseOrigin='validated')
        elif consumed and entry['state'] == 'prepared':
            entry['state'] = 'uncertain'
        result.append(entry)
    return result


def queue(root):
    root = evidence_root(root)
    for name in ('batch_requests.json', 'estimate_requests.json'):
        result = dict(saved(root, name))
        parts = Path(root) / 'log' / (name + '.parts')
        if parts.exists():
            if parts.is_symlink() or not parts.is_dir():
                raise ValueError('Saved request fragments must be a regular directory.')
            for path in sorted(parts.iterdir()):
                if path.suffix != '.json' or path.is_symlink():
                    raise ValueError('Saved request fragments are invalid.')
                stat = path.stat()
                for key, value in _read_cached(str(path), stat.st_mtime_ns, stat.st_size).items():
                    if key in result and result[key] != value:
                        raise ValueError('Saved request fragments conflict; no submission was made.')
                    result[key] = value
        if name == 'batch_requests.json':
            from .batch_evidence import ARCHIVE, merge
            result = merge(saved(root, ARCHIVE).get('requests', {}), result)
        if result:
            return result
    return {}


def batch_results(root):
    from .batch_evidence import ARCHIVE, merge
    root = evidence_root(root)
    current = saved(root, 'batch_results.json')
    return merge(saved(root, ARCHIVE).get('results', {}), current.get('results', current))


def batch_state(root):
    from .batch_evidence import ARCHIVE
    root = evidence_root(root)
    previous, current = saved(root, ARCHIVE).get('state', {}), saved(root, 'batch_state.json')
    manifests = {batch['id']: batch for batch in previous.get('batches', [])}
    manifests.update({batch['id']: batch for batch in current.get('batches', [])})
    return {**previous, **current, 'batches': list(manifests.values())}


def clean_message(value, secret=''):
    text = str(value or '')[:2000]
    if secret:
        text = text.replace(secret, '[credential removed]')
    text = re.sub(r'(?i)(Bearer\s+|api[_-]?key[=: ]+)[^\s,;]+', r'\1[credential removed]', text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]+', '[credential removed]', text)


def source_values(params):
    for message in reversed(params.get('messages', [])):
        content = message.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(block.get('text', '') for block in content if isinstance(block, dict))
        if not isinstance(content, str):
            continue
        for match in re.finditer(r'\{', content):
            try:
                value, _ = json.JSONDecoder().raw_decode(content[match.start():])
                if isinstance(value, dict) and value and all(re.fullmatch(r'Line\d+', key) and isinstance(text, str) for key, text in value.items()):
                    return value
            except ValueError:
                pass
    return None


def fresh_start(root, job):
    """Require positive terminal rejection receipts, never infer from failure."""
    protected = {'eligible': False, 'reason': 'Reconcile saved provider work before starting fresh. Its outcome is not fully rejected and accounted for.'}
    if job.get('mode') != 'batch' or job.get('status') != 'failed' or job.get('approval'):
        return protected
    try:
        path = Path(root) / 'plan.json'
        if path.is_symlink() or digest(path.read_bytes()) != job.get('plan_hash'):
            return protected
        plan = read_json(path)
        if plan.get('batch_link') or job.get('batch_root'):
            return protected
        requests = queue(root)
        history = saved(root, 'batch_history.json')
        state = saved(root, 'batch_state.json')
        results = saved(root, 'batch_results.json')
        batches = history.get('batches', [])
        manifests = state.get('batches', [])
        if (not requests or not batches or not manifests or
                state.get('status') not in {'submitted', 'partially_submitted'} or
                job.get('completed') or job.get('outputs') or results.get('results', results)):
            return protected
        if (any(not isinstance(row, dict) or not row.get('id') or not row.get('custom_ids') for row in [*batches, *manifests]) or
                len({row['id'] for row in batches}) != len(batches) or
                len({row['id'] for row in manifests}) != len(manifests) or
                {row['id']: row['custom_ids'] for row in batches} != {row['id']: row['custom_ids'] for row in manifests}):
            return protected
        submitted = []
        for batch in batches:
            counts = batch.get('request_counts', {})
            if (batch.get('provider') not in {'openai', 'anthropic', 'gemini'} or
                    batch.get('api_status') != ('ended' if batch.get('provider') == 'anthropic' else 'completed') or
                    any(type(counts.get(key)) is not int or counts[key] != 0
                        for key in ('processing', 'succeeded', 'canceled', 'expired')) or
                    type(counts.get('errored')) is not int or counts['errored'] != len(batch['custom_ids']) or
                    batch.get('output_file_id')):
                return protected
            submitted.extend(batch['custom_ids'].values())
        if len(set(submitted)) != len(submitted) or set(submitted) - set(requests):
            return protected
        connection = ledger(root)
        if connection is not None:
            with closing(connection):
                if connection.execute('SELECT COUNT(*) FROM requests').fetchone()[0]:
                    return protected
        proof = digest({'job': job, 'plan': plan, 'requests': requests, 'history': history, 'state': state, 'results': results})
        return {'eligible': True, 'fingerprint': proof, 'failed': len(submitted),
                'remaining': len(requests)-len(submitted),
                'reason': 'Saved provider receipts confirm that every submitted request was rejected, with no successful or pending responses.'}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return protected


def file_metric(line, files):
    """Interpret the same per-file receipt used by Qt, never a total/estimate."""
    line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(line))
    match = re.match(r'^\s*(.+?):\s.*?\[Input:\s*(\d+)\].*?\[Output:\s*(\d+)\].*?\[Cost:\s*\$([\d,.]+)\].*?\[([\d.]+)s\]', line)
    if not match or match[1].strip() not in files:
        return {}
    try:
        cost, seconds = float(match[4].replace(',', '')), float(match[5])
        if not all(math.isfinite(value) and value >= 0 for value in (cost, seconds)):
            return {}
        return {match[1].strip(): {'cost': cost, 'seconds': seconds}}
    except ValueError:
        return {}


def file_metrics(job):
    # New receipts survive the native 40-line log cap. Old Live runs can still
    # show the receipts retained in their log; missing figures stay unknown.
    result = {}
    if job.get('mode') in {'translate', 'offline'}:
        for line in job.get('log', []):
            result.update(file_metric(line, job.get('files', [])))
    return {**result, **job.get('file_metrics', {})}


@lru_cache(maxsize=32)
def _prepared_files(root, signature):
    connection = ledger(root)
    if connection is None:
        return None
    with closing(connection):
        columns = {row[1] for row in connection.execute('PRAGMA table_info(requests)')}
        if not {'filename', 'sources'}.issubset(columns):
            return None
        rows = connection.execute('SELECT DISTINCT filename, sources IS NOT NULL FROM requests').fetchall()
    return frozenset(name for name, _ in rows) if all(name and recorded for name, recorded in rows) else None


def no_request_files(root, job, items):
    """Negative file evidence needs a finished, fully instrumented collection.

    Keep all builder file identities, including callers sharing a deduplicated
    request. A missing queue filename alone never proves that a file was skipped.
    """
    phase = str(job.get('phase', ''))
    if job.get('mode') != 'batch':
        return []
    complete = phase.startswith('poll') or phase in {'collect_done', 'submit', 'consume', 'done', 'no_work'}
    if not complete and batch_state(root).get('status') not in {'submitted', 'partially_submitted', 'fetched'}:
        return []
    root = Path(root)
    plan_path, ledger_path = root/'plan.json', root/'log/dazedtl-process.sqlite3'
    if not plan_path.is_file() or plan_path.is_symlink() or not ledger_path.is_file():
        return []
    stat = plan_path.stat()
    plan = _read_cached(str(plan_path), stat.st_mtime_ns, stat.st_size)
    from dazedtl.settings.preferences import GENERATION_PARAMETERS
    files = set(job.get('files', []))
    if ((plan.get('dazedtl_request_policy') or {}).get('generationParameters') != GENERATION_PARAMETERS
            or files != set(plan.get('selected', [])) or any(item.get('file') not in files for item in items)):
        return []
    stat = ledger_path.stat()
    prepared = _prepared_files(str(root), (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    if prepared is None or not prepared.issubset(files):
        return []
    return sorted(files - prepared - {item['file'] for item in items} - set(job.get('errors', {})))


def summary(root, job):
    requests = queue(root)
    batches = saved(evidence_root(root), 'batch_history.json').get('batches', [])
    submitted = set(key for batch in batches for key in batch.get('custom_ids', {}).values())
    duplicate_submissions = sum(len(batch.get('custom_ids', {})) for batch in batches) - len(submitted)
    results = batch_results(root)
    failed = sum((batch.get('request_counts') or {}).get('errored') or 0 for batch in batches)
    errors = [clean_message(error.get('message')) for batch in batches for error in (batch.get('provider_errors') or []) if error.get('message')]
    received = len(results)
    prepared = len(requests)
    validated = None
    usage = None
    uncertain = 0
    records = ledger_records(root) if not requests else None
    if records is not None:
        rows = [(row['state'], row['usage'], row['error']) for row in records]
        prepared = len(rows)
        received = sum(state in {'received', 'validated'} for state, _, _ in rows)
        validated = sum(state == 'validated' for state, _, _ in rows)
        failed = sum(state == 'failed' for state, _, _ in rows)
        interrupted = job.get('status') in {'failed', 'stopped', 'interrupted', 'canceled'}
        has_intent = 'sources' in {row[1] for row in ledger_columns(root)}
        uncertain = sum(state in {'submitted', 'uncertain'} or (interrupted and not has_intent and state == 'prepared')
                        for state, _, _ in rows)
        errors += [clean_message(error.get('message') or 'Provider response unavailable; submission may be uncertain.') for _, _, error in rows if error]
        usages = [value for _, value, _ in rows if value]
        if usages:
            usage = {key: sum(value.get(key) or 0 for value in usages) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    elif batches:
        usages = [batch['usage'] for batch in batches if batch.get('usage') is not None]
        if usages:
            usage = {key: sum(value.get(key) or 0 for value in usages) for key in ('input_tokens', 'output_tokens')}
    from .request_scope import requests as source_requests
    items = list(source_requests(root, job))
    uncertain = max(uncertain, sum(row['state'] == 'uncertain' for row in items))
    polls = {row['id']: row for row in job.get('batch_detail', []) if isinstance(row, dict) and row.get('id')} if isinstance(job.get('batch_detail'), list) and str(job.get('phase', '')).startswith('poll') else {}
    receipts = []
    for batch in batches:
        current = polls.get(batch['id'], {}) if batch.get('api_status') not in {'completed', 'ended', 'failed', 'expired', 'cancelled', 'canceled'} else {}
        status = current.get('api_status') or batch.get('api_status') or 'unknown'
        counts = current.get('counts') or batch.get('request_counts') or {}
        cancellation = job.get('dazedtl_batch_cancellations', {}).get(batch['id'])
        if cancellation and status not in {'completed', 'ended', 'failed', 'expired', 'cancelled', 'canceled'}:
            status = cancellation['status']
            if status in {'completed', 'ended', 'failed', 'expired', 'cancelled', 'canceled'}:
                counts = cancellation.get('counts') or {}
        receipts.append({'id': batch['id'], 'status': status, 'provider': batch.get('provider'),
                         'total': len(batch['custom_ids']) if isinstance(batch.get('custom_ids'), dict) else None,
                         'counts': counts})
    return {'mode': job.get('mode'), 'prepared': prepared,
            'resultsCollected': batch_state(root).get('status') == 'fetched',
            'sourceItems': sum(len(json.loads(entry['payload'])) for entry in requests.values()) if requests else None,
            'submittedItems': sum(len(json.loads(requests[key]['payload'])) for key in submitted if key in requests) if requests else None,
            'submitted': len(submitted) if batches or requests else sum(row['state'] != 'prepared' for row in records) if records is not None else None,
            'remaining': max(0, len(requests)-len(submitted)) if requests else None, 'received': received if requests or records is not None else None,
            'validated': validated, 'validatedFiles': len(job.get('completed', [])),
            'appliedFiles': len(job.get('appliedOutputs', [])), 'failed': failed,
            'batches': receipts,
            'noRequestFiles': no_request_files(root, job, items),
            'errors': list(dict.fromkeys(errors)), 'usage': usage, 'fileMetrics': file_metrics(job),
            'requests': [{'index': row['index'], 'state': row['state'], 'file': row['file'], 'sourceItems': len(row['source'])} for row in items],
            'retryBlocked': bool(uncertain or any(row['state'] in {'submitted', 'received'} for row in items)
                                 or not items and job.get('mode') == 'translate' and job.get('status') in {'running', 'waiting', 'interrupted', 'stopped'}),
            'uncertain': uncertain, 'duplicateSubmissions': duplicate_submissions,
            'nextAction': 'Use Translate for remaining work with current settings. All saved requests and verified results remain in History.'}


def phase_feedback(job):
    """Current phase wins over an earlier scan's status and file progress."""
    approval = job.get('approval') or {}
    if job.get('status') == 'waiting' and approval.get('kind') == 'batch':
        return {'message': 'Batch requests are ready. Review the cost before submitting.', 'progress': None}
    if job.get('status') == 'waiting' and approval.get('kind') == 'speakers':
        return {'message': 'Speaker check finished. Review unresolved names before translating them.', 'progress': None}
    if job.get('mode') != 'batch' or job.get('status') not in {'running', 'waiting', 'stopped', 'interrupted'}:
        return {}
    phase = str(job.get('phase', ''))
    if phase.startswith('poll'):
        paused = job.get('status') in {'stopped', 'interrupted'}
        batches = (job.get('process') or {}).get('batches', [])
        counts = [row.get('counts') or {} for row in batches]
        done = sum(row.get('succeeded') or 0 for row in counts)
        pending = sum(row.get('processing') or 0 for row in counts)
        detail = f' Last saved provider status: {done} completed, {pending} processing.' if counts and any(counts) else ''
        terminal = bool(batches) and all(row.get('status') in {'completed', 'ended', 'failed', 'expired', 'cancelled', 'canceled'} for row in batches)
        message = 'Provider work has finished. Results are collected automatically.' if terminal else 'Batch submitted. Waiting for provider results.'
        return {'message': message + detail,
                'progress': None}
    if phase in {'collect', 'collect_done', 'submit'}:
        return {'message': 'Preparing Batch requests locally.'}
    if phase == 'consume':
        return {'message': 'Validating received Batch results and saving translated files.'}
    return {}


def ledger_columns(root):
    connection = ledger(root)
    if connection is None:
        return []
    with closing(connection):
        return connection.execute('PRAGMA table_info(requests)').fetchall()


def token_usage(value):
    """Expose only recorded, finite token counts; missing usage is not zero."""
    if not isinstance(value, dict):
        return None
    aliases = {'input_tokens': 'prompt_tokens', 'output_tokens': 'completion_tokens'}
    result = {}
    for key in ('input_tokens', 'output_tokens', 'total_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'thinking_tokens'):
        count = value.get(key, value.get(aliases.get(key)))
        if type(count) in (int, float) and math.isfinite(count) and count >= 0:
            result[key] = count
    return result or None


def payload(root, index):
    if type(index) is not int or index < 0:
        raise ValueError('Choose a valid request index.')
    requests = queue(root)
    if requests:
        keys = list(requests)
        if index >= len(keys):
            raise ValueError('This request is no longer available.')
        key = keys[index]
        entry = requests[key]
        from .request_scope import requests as source_requests
        row = next(item for item in source_requests(root, {}) if item['index'] == index)
        custom_id = next((custom for batch in saved(evidence_root(root), 'batch_history.json').get('batches', [])
                          for custom, value in batch.get('custom_ids', {}).items() if value == key), None)
        from util.batch_providers import _openai_batch_body
        params = _openai_batch_body(entry.get('provider', 'openai'), entry['params']) if entry.get('provider') != 'anthropic' else entry['params']
        exact = {'custom_id': custom_id, 'method': 'POST', 'url': '/v1/chat/completions', 'body': params} if entry.get('provider') != 'anthropic' else {'custom_id': custom_id, 'params': params}
        error = next((error for batch in saved(evidence_root(root), 'batch_history.json').get('batches', []) for error in (batch.get('provider_errors') or [])
                      if error.get('custom_id') == custom_id), None)
        return {'index': index, 'total': len(keys), 'state': row['state'], 'response': row['response'], 'error': error,
                'source': json.loads(entry['payload']), 'context': entry.get('request_context'),
                'parameters': {key: value for key, value in params.items() if key not in {'messages', 'system'}},
                'messages': params.get('messages'), 'system': params.get('system'), 'exact': exact,
                'usage': token_usage(row['response'])}
    rows = ledger_records(root)
    if rows is None:
        raise ValueError('Exact payloads were not recorded for this older Live run.')
    if index >= len(rows):
        raise ValueError('This request is no longer available.')
    row = rows[index]
    params = row['params']
    return {'index': index, 'total': len(rows), 'state': row['state'], 'source': source_values(params),
            'context': None, 'parameters': {key: value for key, value in params.items() if key not in {'messages', 'system'}},
            'messages': params.get('messages'), 'system': params.get('system'), 'exact': params,
            'error': row['error'], 'usage': token_usage(row['usage']), 'response': row['response'],
            'responseOrigin': row.get('responseOrigin')}


def provider_details(root, resolve_connection):
    from util import batch_providers
    rows = []
    for batch in saved(evidence_root(root), 'batch_history.json').get('batches', []):
        binding = resolve_connection(batch)
        client = batch_providers.get_client(batch['provider'], api_key=binding['secret'] or 'not-needed',
                                            api_url=binding['endpoint'], max_retries=0)
        if hasattr(client, 'with_options'):
            options = {'organization': binding['organization'] or None} if batch['provider'] in {'openai', 'gemini'} else {}
            client = client.with_options(timeout=20, max_retries=0, **options)
        try:
            current = batch_providers.retrieve_batch(batch['provider'], batch['id'], client=client)
            errors = current.get('errors') or []
            if current.get('error_file_id'):
                text = batch_providers._download_file_text(batch['provider'], current['error_file_id'], client=client)
                errors = []
                for line in text.splitlines():
                    value = json.loads(line)
                    if value.get('custom_id') not in batch.get('custom_ids', {}):
                        continue
                    error = value.get('error') or value.get('response', {}).get('body', {}).get('error') or {}
                    errors.append({**error, 'custom_id': value.get('custom_id')})
            secret = binding['secret']
            rows.append({'id': batch['id'], 'status': current['api_status'], 'counts': current.get('counts') or {},
                         'errors': [{key: clean_message(error.get(key), secret) for key in ('custom_id', 'code', 'param', 'message')} for error in errors[:100]]})
        finally:
            close = getattr(client, 'close', None)
            if close:
                close()
    return {'batches': rows}
