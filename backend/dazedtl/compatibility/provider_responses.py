"""Retain refusal metadata discarded by the native response normalizers."""

from functools import wraps
from types import SimpleNamespace

from dazedtl.translation.refusals import refused, refusal_reason


def install():
    from util import batch_providers, batch_history
    if getattr(batch_providers._openai_result, '_dazedtl_refusals', False):
        return
    native = batch_providers._openai_result
    @wraps(native)
    def openai_result(row, *args, **kwargs):
        result, error = native(row, *args, **kwargs)
        if result is not None and refused((row.get('response') or {}).get('body') or {}):
            result['refusal'] = refusal_reason((row.get('response') or {}).get('body') or {}) or True
        return result, error
    openai_result._dazedtl_refusals = True
    batch_providers._openai_result = openai_result
    anthropic_entry = batch_history._result_entry_from_message
    @wraps(anthropic_entry)
    def entry(message):
        result = anthropic_entry(message)
        if refused(message):
            result['refusal'] = True
        return result
    batch_history._result_entry_from_message = entry
    native_download = batch_providers._download_anthropic
    @wraps(native_download)
    def download(client, batch_id, custom_ids):
        rejected = set()
        def rows(identity):
            for row in client.messages.batches.results(identity):
                if row.result.type == 'succeeded' and refused(row.result.message):
                    rejected.add(row.custom_id)
                yield row
        observed = SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(results=rows)))
        results, errors, usage = native_download(observed, batch_id, custom_ids)
        for custom in rejected:
            if custom in custom_ids and custom_ids[custom] in results:
                results[custom_ids[custom]]['refusal'] = True
        return results, errors, usage
    batch_providers._download_anthropic = download
