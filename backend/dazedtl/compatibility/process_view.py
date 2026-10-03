"""Read-only, project-owned process evidence and exact retained payloads."""

from functools import lru_cache
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from dazedtl.translation.files import digest, read_json


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
        if result:
            return result
    return {}


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


def summary(root, job):
    requests = queue(root)
    batches = saved(evidence_root(root), 'batch_history.json').get('batches', [])
    submitted = set(key for batch in batches for key in batch.get('custom_ids', {}).values())
    duplicate_submissions = sum(len(batch.get('custom_ids', {})) for batch in batches) - len(submitted)
    results = saved(evidence_root(root), 'batch_results.json')
    if 'results' in results:
        results = results['results']
    failed = sum(batch.get('request_counts', {}).get('errored', 0) for batch in batches)
    errors = [clean_message(error.get('message')) for batch in batches for error in batch.get('provider_errors', []) if error.get('message')]
    received = len(results)
    prepared = len(requests)
    validated = None
    usage = None
    uncertain = 0
    recovery = fresh_start(root, job) if job.get('mode') == 'batch' else None
    with_connection = ledger(root)
    if with_connection is not None:
        with closing(with_connection) as connection:
            rows = connection.execute('SELECT state,usage,error FROM requests').fetchall()
        prepared = len(rows)
        received = sum(state in {'received', 'validated'} for state, _, _ in rows)
        validated = sum(state == 'validated' for state, _, _ in rows)
        failed = sum(state == 'failed' for state, _, _ in rows)
        interrupted = job.get('status') in {'failed', 'stopped', 'interrupted', 'canceled'}
        uncertain = sum(state == 'uncertain' or (interrupted and state in {'prepared', 'received'})
                        for state, _, _ in rows)
        errors += [clean_message(json.loads(error).get('message') or 'Provider response unavailable; submission may be uncertain.') for _, _, error in rows if error]
        usages = [json.loads(value) for _, value, _ in rows if value]
        if usages:
            usage = {key: sum(value.get(key) or 0 for value in usages) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    elif batches:
        usages = [batch['usage'] for batch in batches if batch.get('usage') is not None]
        if usages:
            usage = {key: sum(value.get(key) or 0 for value in usages) for key in ('input_tokens', 'output_tokens')}
    return {'mode': job.get('mode'), 'prepared': prepared,
            'sourceItems': sum(len(json.loads(entry['payload'])) for entry in requests.values()) if requests else None,
            'submittedItems': sum(len(json.loads(requests[key]['payload'])) for key in submitted if key in requests) if requests else None,
            'submitted': len(submitted) if batches or requests else None,
            'remaining': max(0, len(requests)-len(submitted)) if requests else None, 'received': received if requests or with_connection else None,
            'validated': validated, 'validatedFiles': len(job.get('completed', [])),
            'appliedFiles': len(job.get('appliedOutputs', [])), 'failed': failed,
            'batches': [{'id': batch['id'], 'status': batch.get('api_status', 'unknown'), 'counts': batch.get('request_counts', {})} for batch in batches],
            'errors': list(dict.fromkeys(errors)), 'usage': usage,
            'freshStart': recovery,
            'retryBlocked': failed > 0 or uncertain > 0, 'uncertain': uncertain, 'duplicateSubmissions': duplicate_submissions,
            'nextAction': ('Choose Keep failed run and start fresh, then calculate a new estimate. The submitted queue stays in Activity.'
                           if recovery and recovery['eligible'] else recovery['reason'] if recovery else
                           'Prepare a fresh estimate for corrected requests. The submitted queue is preserved; it has not been retried.') if failed else
                          'Check provider status before retrying an uncertain request. Resuming a saved run can submit remaining work.'}


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
        custom_id = next((custom for batch in saved(evidence_root(root), 'batch_history.json').get('batches', [])
                          for custom, value in batch.get('custom_ids', {}).items() if value == key), None)
        from util.batch_providers import _openai_batch_body
        params = _openai_batch_body(entry.get('provider', 'openai'), entry['params']) if entry.get('provider') != 'anthropic' else entry['params']
        exact = {'custom_id': custom_id, 'method': 'POST', 'url': '/v1/chat/completions', 'body': params} if entry.get('provider') != 'anthropic' else {'custom_id': custom_id, 'params': params}
        return {'index': index, 'total': len(keys), 'state': 'submitted' if custom_id else 'queued',
                'source': json.loads(entry['payload']), 'context': entry.get('request_context'),
                'parameters': {key: value for key, value in params.items() if key not in {'messages', 'system'}},
                'messages': params.get('messages'), 'system': params.get('system'), 'exact': exact}
    connection = ledger(root)
    if connection is None:
        raise ValueError('Exact payloads were not recorded for this older Live run.')
    with closing(connection):
        total = connection.execute('SELECT COUNT(*) FROM requests').fetchone()[0]
        row = connection.execute('SELECT params,state,error FROM requests ORDER BY id LIMIT 1 OFFSET ?', (index,)).fetchone()
    if row is None:
        raise ValueError('This request is no longer available.')
    params = json.loads(row[0])
    return {'index': index, 'total': total, 'state': row[1], 'source': source_values(params),
            'context': None, 'parameters': {key: value for key, value in params.items() if key not in {'messages', 'system'}},
            'messages': params.get('messages'), 'system': params.get('system'), 'exact': params,
            'error': json.loads(row[2]) if row[2] else None}


def provider_details(root):
    from util import batch_history, batch_providers, api_keys
    rows = []
    for batch in saved(evidence_root(root), 'batch_history.json').get('batches', []):
        client = batch_history._client_for_entry(batch)
        if hasattr(client, 'with_options'):
            client = client.with_options(timeout=20, max_retries=0)
        current = batch_providers.retrieve_batch(batch['provider'], batch['id'], client=client)
        errors = current['errors']
        if current.get('error_file_id'):
            text = batch_providers._download_file_text(batch['provider'], current['error_file_id'], client=client)
            errors = []
            for line in text.splitlines():
                value = json.loads(line)
                if value.get('custom_id') not in batch.get('custom_ids', {}):
                    continue
                error = value.get('error') or value.get('response', {}).get('body', {}).get('error') or {}
                errors.append({**error, 'custom_id': value.get('custom_id')})
        secret = api_keys.get_secret(batch.get('key_name', '')) or ''
        rows.append({'id': batch['id'], 'status': current['api_status'], 'counts': current['counts'],
                     'errors': [{key: clean_message(error.get(key), secret) for key in ('custom_id', 'code', 'param', 'message')} for error in errors[:100]]})
    return {'batches': rows}
