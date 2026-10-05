"""Durable, same-provider Batch retries for confirmed refusals only."""

from contextlib import nullcontext
from copy import deepcopy
import json

from dazedtl.storage import write_json
from .files import digest, project_path, read_json
from .refusals import clarified, clarifiable


def save(path, record):
    summary = {'original_id': record['original_id'], 'batches': [
        {**{key: batch[key] for key in ('id', 'state', 'api_status', 'counts', 'usage') if key in batch},
         'items': [{key: item[key] for key in ('key', 'custom_id')} for item in batch['items']]}
        for batch in record['batches']]}
    view = path.with_suffix('.summary.json')
    active = any(batch['state'] in {'pending', 'sending', 'submitted'} for batch in record['batches'])
    # Publish protection before sending; publish completion only after its
    # authoritative receipt. Observers read this small derived view, not prompts.
    if active:
        write_json(view, summary)
    write_json(path, record)
    if not active:
        write_json(view, summary)


def advance(root, batch_id, requests, responses, usage, provider, *,
            limits=(50_000, 200_000_000), input_tokens=lambda _: 0, commit=nullcontext, allow_submit=True):
    path = project_path(root, 'log/clarifications/' + digest(batch_id) + '.json', exists=False)
    if path.exists():
        record = read_json(path)
        if record['original_id'] != batch_id or record['requests'] != requests:
            raise ValueError('The saved clarification scope changed. Keep its provider receipts for recovery.')
    else:
        rejected = {key: value for key, value in responses.items() if key in requests and clarifiable(value)}
        if not rejected:
            return {'ready': True, 'responses': responses, 'usage': usage, 'batches': []}
        chunks, items, size, tokens = [], [], 0, 0
        token_limit = limits[2] if len(limits) > 2 else None
        for key in rejected:
            params = clarified(requests[key])
            item = {'custom_id': 'clarify-' + digest(key)[:32], 'params': params, 'key': key}
            length = len(json.dumps(item, ensure_ascii=False).encode('utf-8')) + 1024
            count = input_tokens(params)
            if length > limits[1] or token_limit and count > token_limit:
                raise ValueError('The clarification exceeds the provider Batch limit. Review a smaller request.')
            if items and (len(items) >= limits[0] or size + length > limits[1] or token_limit and tokens + count > token_limit):
                chunks.append({'state': 'pending', 'id': '', 'items': items})
                items, size, tokens = [], 0, 0
            items.append(item)
            size += length
            tokens += count
        if items:
            chunks.append({'state': 'pending', 'id': '', 'items': items})
        record = {'original_id': batch_id, 'requests': requests, 'original_responses': responses,
                  'original_usage': usage, 'batches': chunks}
        with commit():
            save(path, record)
    for batch in record['batches']:
        if batch['state'] in {'complete', 'failed'}:
            continue
        if batch['state'] == 'sending':
            return {'ready': False, 'uncertain': True, 'batches': record['batches']}
        if batch['state'] == 'pending':
            if not allow_submit:
                batch['state'] = 'failed'
                save(path, record)
                continue
            with commit():
                batch['state'] = 'sending'
                save(path, record)
            try:
                result = provider.submit([{key: item[key] for key in ('custom_id', 'params')} for item in batch['items']])
            except Exception as exc:
                status = getattr(exc, 'status_code', None)
                if type(status) is int and 400 <= status < 500:
                    batch['state'] = 'failed'
                    save(path, record)
                    continue
                raise
            # Always retain a returned paid receipt, even if the app closed
            # during submission. Ownership is checked again before consume.
            batch.update(id=result['id'], state='submitted')
            save(path, record)
            return {'ready': False, 'batches': record['batches']}
        status = provider.status(batch['id'])
        batch.update(api_status=status['api_status'], counts=status.get('counts') or {})
        save(path, record)
        if not status['ended']:
            return {'ready': False, 'batches': record['batches']}
        mapping = {item['custom_id']: item['key'] for item in batch['items']}
        collect = provider.collect_terminal if status['terminal_failure'] else provider.collect
        part, errors, used = collect(batch['id'], mapping)
        matched = set(part) | {mapping[key] for key in errors if key in mapping}
        if set(part) - set(mapping.values()) or matched != set(mapping.values()):
            return {'ready': False, 'uncertain': True, 'batches': record['batches']}
        batch.update(state='complete', responses=part, usage=used)
        save(path, record)
    merged, total = deepcopy(record['original_responses']), dict(record['original_usage'])
    for batch in record['batches']:
        for key, value in batch.get('responses', {}).items():
            original = merged[key]
            merged[key] = deepcopy(value)
            # Preserve per-request billed usage as well as the aggregate. This
            # also feeds the guided engine's existing file cost accounting.
            for name in set(original) | set(value):
                if name.endswith('tokens'):
                    merged[key][name] = (original.get(name) or 0) + (value.get(name) or 0)
        for key, value in batch.get('usage', {}).items():
            total[key] = total.get(key, 0) + (value or 0)
    return {'ready': True, 'responses': merged, 'usage': total, 'batches': record['batches']}
