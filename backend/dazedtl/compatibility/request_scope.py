"""Local source identity, receipts and protection across independently saved runs.

Identity excludes model, prompt and chunk size. Legacy queues lack file/field
provenance, so their source text is matched only inside the saved phase/files.
"""

from contextlib import closing
import json

from dazedtl.translation.files import digest, read_json
from .process_view import evidence_root, ledger, queue, saved, source_values, batch_results, batch_state, ledger_records, consumed_files


def identities(filename, phase, values, locations=None):
    return [digest({'file': filename, 'phase': phase, 'source': text,
                    **({'locations': locations.get(text, [])} if locations else {})}) for text in values]


def source_locations(value, path=''):
    result = {}
    if isinstance(value, list):
        children = enumerate(value)
    elif isinstance(value, dict):
        children = ((key, value.get('_original', {}).get(key, item)) for key, item in value.items() if key != '_original')
    else:
        if isinstance(value, str):
            result[value] = [path]
        return result
    for key, item in children:
        for text, locations in source_locations(item, path + '/' + str(key)).items():
            result.setdefault(text, []).extend(locations)
    return result


def columns(connection):
    return {row[1] for row in connection.execute('PRAGMA table_info(requests)')}


def requests(root, job):
    """Only positive rejection receipts release a submitted Batch request."""
    queued = queue(root)
    if queued:
        evidence = evidence_root(root)
        batches = saved(evidence, 'batch_history.json').get('batches', [])
        state = batch_state(evidence)
        results = batch_results(evidence)
        manifests = {row['id']: row.get('custom_ids', {}) for row in state.get('batches', []) if row.get('id')}
        outcomes = {}
        for batch in batches:
            mapping = batch.get('custom_ids', {})
            counts = batch.get('request_counts') or {}
            rejected = (batch.get('api_status') in {'completed', 'ended', 'cancelled', 'canceled', 'expired'}
                        and manifests.get(batch.get('id')) == mapping
                        and all(type(counts.get(key)) is int and counts[key] == 0
                                for key in ('processing', 'succeeded'))
                        and sum(counts.get(key, 0) for key in ('errored', 'canceled', 'expired')) == len(mapping))
            for custom, key in mapping.items():
                error = next((row for row in (batch.get('provider_errors') or []) if row.get('custom_id') == custom), None)
                # Multiple submissions retain the strictest known outcome.
                pending = batch.get('api_status') in {'validating', 'in_progress', 'finalizing'} and manifests.get(batch.get('id')) == mapping
                outcome = 'received' if key in results else 'failed' if rejected or error else 'submitted' if pending else 'uncertain'
                priority = {'failed': 0, 'submitted': 1, 'received': 2, 'uncertain': 3}
                if priority[outcome] >= priority.get(outcomes.get(key), -1):
                    outcomes[key] = outcome
        for manifest in state.get('batches', []):
            for key in manifest.get('custom_ids', {}).values():
                outcomes.setdefault(key, 'uncertain')
        unknown_submission = (state.get('status') in {'submission_uncertain', 'submitting', 'corrupt'} or
                              job.get('dazedtl_submission_intent') and state.get('status') not in {'partially_submitted', 'submitted', 'fetched'})
        complete = consumed_files(root)
        for index, (key, entry) in enumerate(queued.items()):
            outcome = outcomes.get(key, 'uncertain' if unknown_submission else 'queued')
            if outcome == 'received' and entry.get('dazedtl_file') in complete:
                outcome = 'saved'
            yield {'index': index, 'state': outcome,
                   'source': json.loads(entry['payload']), 'keys': entry.get('dazedtl_sources'),
                   'file': entry.get('dazedtl_file'), 'response': results.get(key)}
        return
    rows = ledger_records(root)
    if rows is not None:
        for index, row in enumerate(rows):
            state = row['state']
            if state == 'prepared' and row['sources'] is None:
                state = 'uncertain'
            yield {'index': index, 'state': state, 'source': source_values(row['params']) or {},
                   'keys': row['sources'], 'file': row['filename'], 'response': row['response']}
        if rows:
            return
    plan_path = root / 'plan.json'
    if plan_path.exists() and job.get('mode') == 'translate' and job.get('status') in {'running', 'waiting', 'interrupted', 'stopped', 'failed'}:
        for row in read_json(plan_path).get('dazedtl_reserved_sources', []):
            yield {**row, 'state': 'uncertain'}


def overlap(estimate_root, estimate_job, previous):
    current = list(requests(estimate_root, estimate_job))
    phase = estimate_job.get('logicalPhase')
    files = set(estimate_job.get('files', []))
    matches = []
    for root, job in previous:
        if job.get('mode') not in {'batch', 'translate', 'speakers'} or job.get('logicalPhase') != phase:
            continue
        shared = files.intersection(job.get('files', [])) - set(job.get('retiredFiles', []))
        if not shared:
            continue
        rows = list(requests(root, job))
        for old in rows:
            if old['state'] not in {'submitted', 'uncertain', 'received'}:
                continue
            if old['file'] and old['file'] not in shared:
                continue
            for new in current:
                if new['file'] and (new['file'] not in shared or old['file'] and old['file'] != new['file']):
                    continue
                if old['keys'] and new['keys']:
                    hit = bool(set(old['keys']).intersection(new['keys']))
                else:
                    hit = bool(set(old['source'].values()).intersection(new['source'].values()))
                    hit = hit and (not old['file'] or old['file'] in shared) and (not new['file'] or new['file'] in shared)
                if hit:
                    matches.append({'run': job['id'], 'request': old['index'] + 1, 'state': old['state'],
                                    'files': [new['file']] if new['file'] else sorted(shared)})
                    break
        if not rows and job.get('mode') == 'translate' and job.get('status') in {'running', 'waiting', 'interrupted', 'stopped'}:
            pending_files = shared.intersection(row['file'] for row in current) if current and all(row['file'] for row in current) else shared
            if pending_files:
                matches.append({'run': job['id'], 'state': 'legacy_unknown', 'files': sorted(pending_files)})
    return matches
