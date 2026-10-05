"""One durable clarification allowance for a guided Live translation request."""

from inspect import signature
import json
from types import SimpleNamespace

from dazedtl.translation.files import digest
from dazedtl.translation.refusals import MESSAGE, clarified, clarifiable, field, refused
from .process_view import source_values


USAGE = ('prompt_tokens', 'completion_tokens', 'total_tokens',
         'cache_read_input_tokens', 'cache_creation_input_tokens')


def receipt(response):
    choice = response.choices[0]
    message = choice.message
    usage = field(response, 'usage')
    return {'content': field(message, 'content'), 'refusal': field(message, 'refusal'),
            'finish_reason': field(choice, 'finish_reason'),
            'usage': {key: field(usage, key, 0) or 0 for key in USAGE}}


def restored(value, *, replay=False):
    usage = {key: 0 if replay else count for key, count in value['usage'].items()}
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=value['finish_reason'],
        message=SimpleNamespace(content=value['content'], refusal=value['refusal']))], usage=SimpleNamespace(**usage))


def send_once(translation, evidence, params):
    """Send the extra paid call without native fallback or SDK retry loops."""
    evidence.record(params, clarification_of=evidence.local.current)
    from util.batch_providers import get_client
    provider = 'anthropic' if 'system' in params else 'openai'
    client = get_client(provider, api_key=translation.openai.api_key,
                        api_url=None if provider == 'anthropic' else str(translation.openai.base_url or ''), max_retries=0)
    options = {'timeout': 45, 'max_retries': 0}
    organization = getattr(translation.openai, 'organization', None)
    if provider != 'anthropic' and organization:
        options['organization'] = organization
    client = client.with_options(**options)
    try:
        if provider == 'anthropic':
            raw = client.messages.create(**params)
            usage = raw.usage
            cached = field(usage, 'cache_read_input_tokens', 0) or 0
            created = field(usage, 'cache_creation_input_tokens', 0) or 0
            response = restored({'content': translation._anthropic_content_text(raw.content),
                'refusal': MESSAGE if refused(raw) else None, 'finish_reason': field(raw, 'stop_reason'),
                'usage': {'prompt_tokens': (field(usage, 'input_tokens', 0) or 0) + cached + created,
                          'completion_tokens': field(usage, 'output_tokens', 0) or 0,
                          'cache_read_input_tokens': cached, 'cache_creation_input_tokens': created}})
        else:
            response = client.chat.completions.create(**params)
        translation._write_request_debug_log(provider, params, response.usage)
        value = receipt(response)
        with evidence.connect() as connection:
            connection.execute('UPDATE requests SET raw_response=? WHERE id=?',
                (json.dumps({'text': value['content'], 'refusal': value['refusal'], 'finish_reason': value['finish_reason']},
                            ensure_ascii=False), evidence.local.current))
        return response
    finally:
        client.close()


class RefusalRetry:
    def __init__(self, evidence, native, *, allow_clarification=False, translation=None):
        self.evidence, self.native, self.signature = evidence, native, signature(native)
        self.allow_clarification = allow_clarification
        self.translation = translation
        with evidence.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS clarification_retries '
                               '(identity TEXT PRIMARY KEY, response TEXT, request_id INTEGER)')

    def reject(self, response):
        evidence = self.evidence
        value = receipt(response)
        evidence.update('rejected', value['usage'], json.dumps({'message': MESSAGE}))
        with evidence.connect() as connection:
            connection.execute('UPDATE requests SET response=? WHERE id=?',
                               (json.dumps(value, ensure_ascii=False), evidence.local.current))

    def __call__(self, *args, **kwargs):
        evidence = self.evidence
        bound = self.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        source = source_values({'messages': [{'content': bound.arguments['user']}]})
        # Native validation retries prepend a correction to user. Key the source
        # separately so those retries cannot reset the clarification allowance.
        identity = digest({**bound.arguments, 'user': source or bound.arguments['user'],
                           'filename': getattr(evidence.local, 'filename', None)})
        evidence.local.request_identity = identity
        cursors = getattr(evidence.local, 'request_cursors', {})
        cursor = cursors.setdefault(identity, getattr(evidence.local, 'cursor', 0))
        evidence.local.cursor = cursor
        with evidence.connect() as connection:
            saved = connection.execute('SELECT response,request_id FROM clarification_retries WHERE identity=?', (identity,)).fetchone()
        if saved:
            if saved[0] is None:
                raise RuntimeError('The clarification request has no saved response. Reconcile it before further paid work.')
            evidence.local.current = saved[1]
            evidence.local.cursor = cursor + len(source or {})
            if getattr(evidence.local, 'call', None) is not None:
                evidence.local.call.append(saved[1])
            return restored(json.loads(saved[0]), replay=True)
        response = self.native(*args, **kwargs)
        if not refused(response, (source or {}).values()):
            return response
        self.reject(response)
        first = receipt(response)
        first_usage = first['usage']
        # the characters or retry that passage with an age clarification.
        if not self.allow_clarification or not clarifiable(response, (source or {}).values()):
            first.update(content=None, refusal=MESSAGE)
            with evidence.connect() as connection:
                connection.execute('INSERT INTO clarification_retries VALUES (?,?,?)',
                                   (identity, json.dumps(first, ensure_ascii=False), evidence.local.current))
            return restored(first)
        with evidence.connect() as connection:
            connection.execute('INSERT INTO clarification_retries VALUES (?,NULL,?)', (identity, evidence.local.current))
        with evidence.connect() as connection:
            row = connection.execute('SELECT params FROM requests WHERE id=?', (evidence.local.current,)).fetchone()
        params = clarified(json.loads(row[0]))
        evidence.local.cursor = cursor
        print('Provider declined a translation; clarifying the fictional adult context once.', flush=True)
        response = send_once(self.translation, evidence, params)
        value = receipt(response)
        if refused(response, (source or {}).values()):
            self.reject(response)
            # Force native validation failure even for a refusal in valid JSON.
            value.update(content=None, refusal=MESSAGE)
        value['usage'] = {key: first_usage[key] + value['usage'][key] for key in USAGE}
        with evidence.connect() as connection:
            connection.execute('UPDATE clarification_retries SET response=?,request_id=? WHERE identity=?',
                               (json.dumps(value, ensure_ascii=False), evidence.local.current, identity))
        return restored(value)
