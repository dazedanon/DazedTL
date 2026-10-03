"""Local payload and usage evidence; recording never calls a provider."""

from functools import wraps
from contextlib import contextmanager
import json
from inspect import signature
from pathlib import Path
import sqlite3
import threading
from .process_view import clean_message, source_values
from .request_scope import identities, columns, source_locations
from dazedtl.translation.files import digest


class Evidence:
    def __init__(self, root, mode, plan=None):
        self.path = Path(root) / 'log/dazedtl-process.sqlite3'
        self.mode = mode
        self.local = threading.local()
        self.plan = plan or {}
        self.reused = self.plan.get('dazedtl_continuation', {})
        self.root, self.locations = Path(root), {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, params TEXT, state TEXT, usage TEXT, error TEXT)')
            for name in ('sources', 'filename', 'response'):
                if name not in columns(connection):
                    connection.execute('ALTER TABLE requests ADD COLUMN ' + name + ' TEXT')
            connection.execute('CREATE TABLE IF NOT EXISTS validated_items (identity TEXT PRIMARY KEY, source TEXT, response TEXT)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def prepared(self, params, state='prepared'):
        with self.connect() as connection:
            row = connection.execute('INSERT INTO requests(params,state,sources,filename) VALUES (?,?,?,?)',
                                     (json.dumps(params, ensure_ascii=False), state,
                                      json.dumps(getattr(self.local, 'sources', [])), getattr(self.local, 'filename', None)))
            self.local.current = row.lastrowid
            if getattr(self.local, 'call', None) is not None:
                self.local.call.append(row.lastrowid)

    def record(self, params):
        # Durable intent precedes the SDK call; merely built estimate payloads
        # never acquire an uncertain/submitted state.
        values = source_values(params) or {}
        keys = getattr(self.local, 'all_sources', [])
        cursor = getattr(self.local, 'cursor', 0)
        self.local.sources = keys[cursor:cursor+len(values)] or keys
        self.local.cursor = cursor + len(values)
        self.prepared(params, 'submitted' if self.mode == 'translate' else 'prepared')

    def update(self, state, usage=None, error=None):
        current = getattr(self.local, 'current', None)
        if current is not None:
            with self.connect() as connection:
                connection.execute('UPDATE requests SET state=?,usage=?,error=? WHERE id=?',
                                   (state, json.dumps(usage) if usage is not None else None, error, current))

    def install(self, translation, module=None):
        native_queue = translation.queue_batch_request
        @wraps(native_queue)
        def queued(*args, **kwargs):
            key = native_queue(*args, **kwargs)
            with translation.BATCH_LOCK:
                entry = translation._batch_queue_pending.get(key)
                if entry is not None:
                    entry.update(dazedtl_sources=getattr(self.local, 'sources', []),
                                 dazedtl_file=getattr(self.local, 'filename', None))
            return key
        translation.queue_batch_request = queued
        native_debug = translation._write_request_debug_log
        @wraps(native_debug)
        def received(provider, params, usage):
            current = getattr(self.local, 'current', None)
            with self.connect() as connection:
                row = connection.execute('SELECT params FROM requests WHERE id=?', (current,)).fetchone()
            if row and json.loads(row[0]) != params:
                self.update('uncertain', error=json.dumps({'message': 'The engine generated a different fallback payload; the earlier attempt remains retained.'}))
                self.prepared(params)
            self.update('received', {key: getattr(usage, key, None) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
            return native_debug(provider, params, usage)
        translation._write_request_debug_log = received
        native_call = translation.translateText
        @wraps(native_call)
        def call(*args, **kwargs):
            self.local.current = None
            try:
                return native_call(*args, **kwargs)
            except Exception as error:
                # SDK exceptions can contain credentials or source text. Retain
                # only structured status/code/param, never str(exception).
                body = getattr(error, 'body', {}) or {}
                if isinstance(body, dict):
                    body = body.get('error', body)
                detail = {key: body.get(key) for key in ('code', 'param', 'type')} if isinstance(body, dict) else {}
                detail['status'] = getattr(error, 'status_code', None)
                if isinstance(body, dict) and body.get('message'):
                    secret = getattr(getattr(translation, 'openai', None), 'api_key', '') or ''
                    detail['message'] = clean_message(body['message'], secret)
                status = detail['status']
                self.update('failed' if status in {400, 401, 403, 404, 405, 413, 415, 422, 429} else 'uncertain', error=json.dumps(detail))
                raise
        translation.translateText = call
        native_ai = translation.translateAI
        call_signature = signature(native_ai)
        @wraps(native_ai)
        def validated(*args, **kwargs):
            bound = call_signature.bind(*args, **kwargs)
            text = bound.arguments.get('text')
            filename = bound.arguments.get('filename')
            values = text if isinstance(text, list) else [text]
            if not all(isinstance(value, str) for value in values):
                return native_ai(*args, **kwargs)
            if filename not in self.locations:
                path = self.root / 'files' / str(filename)
                try:
                    self.locations[filename] = source_locations(json.loads(path.read_text(encoding='utf-8-sig'))) if path.is_file() else {}
                except (OSError, ValueError):
                    self.locations[filename] = {}
            locations = self.locations[filename]
            keys = identities(filename, (self.plan.get('workflow') or {}).get('phase'), values, locations)
            # A duplicated source string has ambiguous field provenance. Retain
            # separate response context instead of silently substituting one
            # field's translation into a different context.
            history = bound.arguments.get('history')
            reuse_keys = [key if len(locations.get(value, [])) <= 1 else
                          digest([key, history])
                          for key, value in zip(keys, values)]
            self.local.all_sources, self.local.sources, self.local.filename, self.local.cursor = keys, keys, filename, 0
            reused = [self.reused.get(key) for key in reuse_keys]
            if values and all(row is not None and row.get('source') == value for row, value in zip(reused, values)):
                translation._thread_local.last_translation_had_mismatch = False
                output = [row['response'] for row in reused]
                return [output if isinstance(text, list) else output[0], [0, 0]]
            if isinstance(text, list) and any(row is not None and row.get('source') == value for row, value in zip(reused, values)):
                output, tokens = [], [0, 0]
                cursor = 0
                while cursor < len(values):
                    row = reused[cursor]
                    if row is not None and row.get('source') == values[cursor]:
                        output.append(row['response']); cursor += 1
                        continue
                    end = cursor + 1
                    while end < len(values) and reused[end] is None:
                        end += 1
                    segment = call_signature.bind(*args, **kwargs)
                    segment.arguments['text'] = values[cursor:end]
                    history = segment.arguments.get('history')
                    if cursor and isinstance(history, list):
                        limit = getattr(segment.arguments.get('config'), 'maxHistory', 10)
                        segment.arguments['history'] = (history + values[:cursor])[-limit:]
                    translated, used = validated(*segment.args, **segment.kwargs)
                    if translation.last_translation_had_mismatch():
                        return [values, tokens]
                    output.extend(translated)
                    tokens = [a+b for a,b in zip(tokens, used)]
                    cursor = end
                return [output, tokens]
            previous = getattr(self.local, 'call', None)
            self.local.call = []
            try:
                result = native_ai(*args, **kwargs)
                if not translation.last_translation_had_mismatch():
                    with self.connect() as connection:
                        connection.executemany("UPDATE requests SET state='validated' WHERE id=? AND state='received'",
                                               [(identity,) for identity in self.local.call])
                        output = result[0] if isinstance(result[0], list) else [result[0]]
                        if len(output) == len(values) and (self.mode in {'translate', 'offline'} or translation.get_batch_phase() == 'consume'):
                            connection.executemany('INSERT OR REPLACE INTO validated_items VALUES (?,?,?)',
                                                   [(key, source, json.dumps(response, ensure_ascii=False)) for key, source, response in zip(reuse_keys, values, output)])
                            connection.executemany('UPDATE requests SET response=? WHERE id=?',
                                                   [(json.dumps(output, ensure_ascii=False), identity) for identity in self.local.call])
                return result
            finally:
                self.local.call = previous
        translation.translateAI = validated
        if module is not None and hasattr(module, 'sharedtranslateAI'):
            module.sharedtranslateAI = validated
