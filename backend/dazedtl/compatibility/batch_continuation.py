"""Continue an approved, unchanged queue through the original Batch runner."""
from contextlib import closing
from copy import deepcopy
from functools import wraps
from pathlib import Path
import json

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path, read_json
from .process_view import ledger, queue, saved

APPROVAL = 'dazedtl_batch_approval'
JOURNAL = 'dazedtl-batch-submission.json'


class BatchContinuationError(ValueError):
    pass


def binding(root, job, plan, *, quote=None):
    """Bind the paid review to exact requests, frozen inputs and provider route."""
    root = Path(root)
    state = saved(root, 'batch_state.json')
    requests = queue(root)
    estimate = quote if quote is not None else job.get('estimate') or {}
    if (job.get('mode') != 'batch' or plan.get('mode') != 'batch' or plan.get('batch_link')
            or job.get('plan_hash') != digest(project_path(root, 'plan.json').read_bytes())
            or not requests or not state.get('run_id')
            or set(state.get('file_set') or []) != set(plan.get('selected') or [])
            or set(job.get('files') or []) != set(plan.get('selected') or [])
            or estimate.get('requests') != len(requests)
            or estimate.get('model') != plan.get('settings', {}).get('model')
            or state.get('model') != estimate.get('model')
            or state.get('provider') != estimate.get('provider')
            or state.get('endpoint') != plan.get('settings', {}).get('api')
            or any(entry.get('provider') != state['provider'] or entry.get('params', {}).get('model') != state['model']
                   for entry in requests.values())):
        raise BatchContinuationError('The saved Batch queue no longer matches its approved scope or connection.')
    return {'version': 1, 'plan_hash': job['plan_hash'], 'run_id': state['run_id'],
            'digest': digest(requests), 'requests': len(requests)}


def approved_binding(root, job, plan):
    value = binding(root, job, plan)
    if job.get(APPROVAL):
        if job[APPROVAL] != value:
            raise BatchContinuationError('The approved Batch requests changed. No remaining requests were submitted.')
        return value
    # Older app runs retain their approved quote and preparation ledger. Only
    # adopt that exact, already-paid queue; a speaker approval is insufficient.
    state = saved(root, 'batch_state.json')
    history = saved(root, 'batch_history.json').get('batches', [])
    if (not job.get('dazedtl_approved') or not job.get('dazedtl_submission_intent')
            or not history or state.get('cost_estimate') != job.get('estimate')
            or state.get('queued_request_count') != value['requests']):
        raise BatchContinuationError('This queue has no matching saved Batch approval.')
    connection = ledger(root)
    if connection is None:
        raise BatchContinuationError('The approved Batch preparation receipts are unavailable.')
    with closing(connection):
        prepared = {digest(json.loads(row[0])) for row in connection.execute('SELECT params FROM requests')}
    if any(digest(entry['params']) not in prepared for entry in queue(root).values()):
        raise BatchContinuationError('A Batch request differs from its saved preparation receipt.')
    return value


def validate_submission_records(root):
    state = saved(root, 'batch_state.json')
    history = saved(root, 'batch_history.json').get('batches', [])
    actual = {row['id']: row.get('custom_ids') or {} for row in state.get('batches', [])}
    recorded = {row['id']: row.get('custom_ids') or {} for row in history}
    intent = saved(root, JOURNAL).get('intent')
    if intent and not intent.get('receipt'):
        raise BatchContinuationError('A Batch submission has an uncertain provider outcome. It cannot be sent again automatically.')
    if intent:
        receipt = intent['receipt']
        for mappings in (actual, recorded):
            if receipt['id'] in mappings and mappings[receipt['id']] != receipt['custom_ids']:
                raise BatchContinuationError('The returned Batch receipt conflicts with its saved submission.')
            mappings.setdefault(receipt['id'], receipt['custom_ids'])
    keys = [key for mapping in recorded.values() for key in mapping.values()]
    if (state.get('status') not in {'queued', 'submitted', 'partially_submitted', 'fetched'}
            or actual != recorded or len(keys) != len(set(keys)) or not set(keys).issubset(queue(root))):
        raise BatchContinuationError('The Batch submission receipts conflict. No requests were resubmitted.')
    return state


def prepare_continuation(root, job, plan, *, explicit=False):
    """Repair only the partial/fetched marker; never clear paid responses."""
    if job.get('dazedtl_batch_stopped') and not explicit or job.get('dazedtl_batch_cancellations') or job.get('status') == 'canceled':
        raise BatchContinuationError('This Batch was explicitly stopped or canceled.')
    approval = approved_binding(root, job, plan)
    state = validate_submission_records(root)
    if explicit:
        job.pop('dazedtl_batch_stopped', None)
    job[APPROVAL] = approval
    job.pop('dazedtl_consume_only', None)
    job['dazedtl_continue_batch'] = True
    if state['status'] == 'fetched':
        write_json(project_path(root, 'log/batch_state.json'), {**state, 'status': 'partially_submitted'})
    return approval


def install_worker(root, plan):
    """Journal native creates without changing parsing, chunking or consume."""
    if plan.get('mode') != 'batch' or plan.get('batch_link'):
        return
    import util.translation as translation
    import util.batch_providers as providers
    from util.translation_task import TranslationTask
    from util.batch_history import record_submit
    root = Path(root)
    native = getattr(providers.submit_batch, '_dazedtl_native', providers.submit_batch)

    def approved():
        job = read_json(project_path(root, 'job.json'))
        value = approved_binding(root, job, plan)
        translation.BATCH_QUEUE_EXPECTED = {'run_id': value['run_id'], 'digest': value['digest']}
        return value

    def recover_receipt():
        intent = saved(root, JOURNAL).get('intent')
        if not intent:
            return
        value = approved()
        if intent.get('approval') != value or not intent.get('receipt'):
            raise BatchContinuationError('A Batch submission is uncertain or changed; it will not be repeated.')
        info = intent['receipt']
        history = saved(root, 'batch_history.json').get('batches', [])
        known = next((row for row in history if row['id'] == info['id']), None)
        state = deepcopy(saved(root, 'batch_state.json'))
        current = next((row for row in state.get('batches', []) if row['id'] == info['id']), None)
        if known and known.get('custom_ids') != info['custom_ids'] or current and current.get('custom_ids') != info['custom_ids']:
            raise BatchContinuationError('The returned Batch receipt conflicts with its saved submission.')
        if known and (current or state.get('status') == 'fetched'):
            return
        if any(set(row.get('custom_ids', {}).values()) & set(info['custom_ids'].values())
               for row in history if row['id'] != info['id']):
            raise BatchContinuationError('The returned Batch receipt overlaps another provider submission.')
        if not current:
            state.setdefault('batches', []).append(info)
            submitted = {key for row in state['batches'] for key in row['custom_ids'].values()}
            state.update(status='submitted' if len(submitted) == value['requests'] else 'partially_submitted',
                         request_count=len(submitted))
            write_json(project_path(root, 'log/batch_state.json'), state)
        if not known:
            record_submit([info], model=state['model'], provider=state['provider'], file_set=state['file_set'],
                          cost_estimate=state.get('cost_estimate'), key_name=plan['key_name'], endpoint=state['endpoint'])

    @wraps(native)
    def submit(provider, requests, **kwargs):
        input_tokens = kwargs.pop('_dazedtl_input_tokens', None)
        # Clarifications already have their own durable submission journal.
        if not requests or not all(str(row.get('custom_id', '')).startswith('req-') for row in requests):
            return native(provider, requests, **kwargs)
        approval = approved()
        recover_receipt()
        queued = queue(root)
        keys = list(queued)
        mapping = {}
        for row in requests:
            key = keys[int(row['custom_id'].removeprefix('req-'))]
            if row['params'] != queued[key]['params']:
                raise BatchContinuationError('The submitted Batch differs from its approved request.')
            mapping[row['custom_id']] = key
        submitted = {key for batch in saved(root, 'batch_history.json').get('batches', []) for key in batch.get('custom_ids', {}).values()}
        if submitted.intersection(mapping.values()):
            raise BatchContinuationError('This Batch request already has a provider receipt.')
        path = project_path(root, 'log/' + JOURNAL, exists=False)
        state = saved(root, 'batch_state.json')
        intent = {'approval': approval, 'custom_ids': mapping, 'receipt': None,
                  'key_name': plan['key_name'], 'endpoint': state['endpoint'], 'model': state['model'],
                  'estimated_input_tokens': input_tokens}
        write_json(path, {'intent': intent})
        client = kwargs.get('client') or providers.get_client(provider)
        kwargs['client'] = client.with_options(max_retries=0)
        result = native(provider, requests, **kwargs)
        state = saved(root, 'batch_state.json')
        info = {**result, 'custom_ids': mapping, 'provider': provider, 'run_id': approval['run_id'], 'model': state['model'],
                'key_name': plan['key_name'], 'endpoint': state['endpoint'], 'cache_key_version': state.get('cache_key_version')}
        if input_tokens is not None:
            info['estimated_input_tokens'] = input_tokens
        intent['receipt'] = info
        write_json(path, {'intent': intent})
        return result

    submit._dazedtl_native = native
    providers.submit_batch = submit
    native_wait = getattr(TranslationTask._wait_batch_submit, '_dazedtl_native', TranslationTask._wait_batch_submit)

    @wraps(native_wait)
    def wait(task, estimate):
        if read_json(project_path(root, 'job.json')).get(APPROVAL):
            approved()
            task._batch_pending_estimate = estimate
            return not task.should_stop
        return native_wait(task, estimate)
    wait._dazedtl_native = native_wait
    TranslationTask._wait_batch_submit = wait
    # A crash after the returned job ID but before native checkpointing is
    # repaired from the journal; an unknown HTTP outcome remains protected.
    with translation._batch_submit_lock():
        recover_receipt()
    from .batch_window import install_worker as install_batch_window
    install_batch_window(root, plan, translation, providers, TranslationTask, approved, recover_receipt, record_submit)
