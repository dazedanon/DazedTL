"""Project-bound Batch cancellation and collection; never create provider work."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path
from .process_view import saved, evidence_root, queue, batch_results
from .translation import TranslationProvider

TERMINAL = {'completed', 'ended', 'failed', 'expired', 'cancelled', 'canceled'}


def no_successful_results(root):
    batches = saved(evidence_root(root), 'batch_history.json').get('batches', [])
    return bool(batches) and not batch_results(root) and all(
        batch.get('api_status') in TERMINAL and batch.get('custom_ids')
        and type((batch.get('request_counts') or {}).get('succeeded')) is int
        and batch['request_counts']['succeeded'] == 0 for batch in batches)


def receipt(root, identity):
    batch = next((row for row in saved(evidence_root(root), 'batch_history.json').get('batches', []) if row.get('id') == identity), None)
    if not batch or batch.get('provider') not in {'openai', 'anthropic', 'gemini'} or not isinstance(batch.get('custom_ids'), dict) or not batch['custom_ids']:
        raise ValueError('Choose a submitted Batch with retained request IDs.')
    return batch


def binding(batch):
    return digest({key: batch.get(key) for key in ('id', 'provider', 'key_name', 'endpoint', 'organization', 'custom_ids')})


@contextmanager
def connection(batch, resolve):
    value = resolve(batch)
    provider = TranslationProvider({**value, 'protocol': batch['provider'], 'mode': 'batch'}, value['secret'] or 'not-needed')
    try:
        yield provider
    finally:
        close = getattr(provider.client, 'close', None)
        if close:
            close()


def cancel(root, identity, expected, resolve):
    batch = receipt(root, identity)
    if binding(batch) != expected:
        raise ValueError('This Batch changed. Review cancellation again.')
    with connection(batch, resolve) as provider:
        current = provider.status(identity)
        status = current['api_status']
        if status in TERMINAL or status in {'cancelling', 'canceling'}:
            return {'id': identity, 'status': status, 'requested': False, 'counts': current.get('counts') or {}}
        result = provider.cancel(identity)
        return {**result, 'requested': True}


def collect(root, resolve, *, commit=nullcontext):
    """Retain terminal successes and prepare only a local consume pass.

    The caller excludes running workers. All provider jobs must be terminal;
    mappings, queue and prior receipts remain intact, including unsent work.
    """
    evidence = evidence_root(root)
    state = deepcopy(saved(evidence, 'batch_state.json'))
    history = deepcopy(saved(evidence, 'batch_history.json'))
    batches = history.get('batches', [])
    if not batches or state.get('status') not in {'submitted', 'partially_submitted', 'fetched'}:
        raise ValueError('This saved Batch needs its original submission records before collection.')
    original = digest({'state': state, 'history': history, 'queue': queue(root)})
    results = deepcopy(saved(evidence, 'batch_results.json'))
    results = results.get('results', results)
    for batch in batches:
        if batch.get('provider') not in {'openai', 'anthropic', 'gemini'} or not isinstance(batch.get('custom_ids'), dict) or not batch['custom_ids']:
            raise ValueError('A provider Batch is missing its request mapping.')
        with connection(batch, resolve) as provider:
            status = provider.status(batch['id'])
            if status['api_status'] not in TERMINAL:
                raise ValueError('The provider is still working. Keep monitoring until every Batch finishes or cancels.')
            part, errors, usage = provider.collect_terminal(batch['id'], batch['custom_ids'])
        if set(part) - set(batch['custom_ids'].values()):
            raise ValueError('Received results are outside this Batch’s saved scope.')
        for key, value in part.items():
            if key in results and results[key] != value:
                raise ValueError('Received results conflict with a saved response. Existing results were retained.')
            results[key] = value
        batch.update(api_status=status['api_status'], request_counts=status.get('counts') or {}, usage=usage)
        if type(batch['request_counts'].get('succeeded')) is int and batch['request_counts']['succeeded'] == len(part):
            # Complete downloaded success coverage distinguishes canceled or
            # rejected requests from a missing paid response.
            previous = {error.get('custom_id'): error for error in batch.get('provider_errors') or []}
            batch['provider_errors'] = [previous.get(custom) or {'custom_id': custom, 'message': 'This request ended without a successful response.'}
                                        for custom, key in batch['custom_ids'].items() if key not in part]
    with commit():
        if digest({'state': saved(evidence, 'batch_state.json'), 'history': saved(evidence, 'batch_history.json'), 'queue': queue(root)}) != original:
            raise ValueError('The saved Batch changed during collection. Try again after the worker stops.')
        for name in ('batch_results.json', 'batch_history.json', 'batch_state.json'):
            project_path(evidence, 'log/' + name, exists=False)
        # The final fetched marker is written last. A retry never creates requests.
        write_json(evidence/'log/batch_results.json', results)
        write_json(evidence/'log/batch_history.json', history)
        write_json(evidence/'log/batch_state.json', {**state, 'status': 'fetched', 'batch_ids': [batch['id'] for batch in batches]})
    return {'received': len(results)}
