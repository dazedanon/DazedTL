"""Local payload and usage evidence; recording never calls a provider."""

from functools import wraps
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from .process_view import clean_message


class Evidence:
    def __init__(self, root, mode):
        self.path = Path(root) / 'log/dazedtl-process.sqlite3'
        self.mode = mode
        self.local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, params TEXT, state TEXT, usage TEXT, error TEXT)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def prepared(self, params):
        with self.connect() as connection:
            row = connection.execute('INSERT INTO requests(params,state) VALUES (?,?)',
                                     (json.dumps(params, ensure_ascii=False), 'prepared'))
            self.local.current = row.lastrowid
            if getattr(self.local, 'call', None) is not None:
                self.local.call.append(row.lastrowid)

    def update(self, state, usage=None, error=None):
        current = getattr(self.local, 'current', None)
        if current is not None:
            with self.connect() as connection:
                connection.execute('UPDATE requests SET state=?,usage=?,error=? WHERE id=?',
                                   (state, json.dumps(usage) if usage is not None else None, error, current))

    def install(self, translation, module=None):
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
                self.update('failed' if type(status) is int and 400 <= status < 500 else 'uncertain', error=json.dumps(detail))
                raise
        translation.translateText = call
        native_ai = translation.translateAI
        @wraps(native_ai)
        def validated(*args, **kwargs):
            previous = getattr(self.local, 'call', None)
            self.local.call = []
            try:
                result = native_ai(*args, **kwargs)
                if not translation.last_translation_had_mismatch():
                    with self.connect() as connection:
                        connection.executemany("UPDATE requests SET state='validated' WHERE id=? AND state='received'",
                                               [(identity,) for identity in self.local.call])
                return result
            finally:
                self.local.call = previous
        translation.translateAI = validated
        if module is not None and hasattr(module, 'sharedtranslateAI'):
            module.sharedtranslateAI = validated
