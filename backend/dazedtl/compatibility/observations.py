"""Bounded display caches; execution and inspection keep their fresh readers."""

from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import stat

from dazedtl.translation.files import digest
from . import process_view


def stamp(path):
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(value.st_mode):
        raise ValueError('Observed run artifacts cannot be symbolic links.')
    return value.st_mode, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def process_stamp(root):
    """Track additions/deletions as well as in-place and atomic worker writes.

    These are the local inputs of process_view.summary, including validation
    logs, queue fragments, clarification receipts and SQLite WAL/journal files.
    Imported Batch roots use the uncached reader instead.
    """
    rows = [(str(root), stamp(root))]
    for name in ('plan.json', 'job.json', 'log', 'files', 'translated'):
        pending = [root / name]
        while pending:
            path = pending.pop()
            signature = stamp(path)
            rows.append((str(path), signature))
            if len(rows) > 4096:
                raise ValueError('Run observation exceeds the display cache limit.')
            if signature and stat.S_ISDIR(signature[0]):
                pending.extend(sorted(path.iterdir(), reverse=True))
    return tuple(rows)


class RunObservations:
    def __init__(self):
        self.session = None
        self.plans = OrderedDict()
        self.processes = OrderedDict()
        self.request_rows = 0

    @contextmanager
    def read(self):
        previous = self.session
        self.session = {} if previous is None else previous
        try:
            yield
        finally:
            self.session = previous

    def once(self, key, read):
        if self.session is None:
            return read()
        if key not in self.session:
            self.session[key] = read()
        return self.session[key]

    def configuration(self, backend, identity):
        if self.session is None:
            return backend.saved_run_configuration(identity)

        def read():
            path = backend.manual.folder(identity) / 'plan.json'
            signature = (stamp(path), backend.manual.jobs[identity].get('plan_hash'))
            cached = self.plans.get(path)
            if cached and cached[0] == signature:
                self.plans.move_to_end(path)
                return cached[1]
            plan = backend.saved_run_configuration(identity)
            # Do not retain source text, prompts or continuation payloads just
            # to display ownership and file status.
            value = {key: plan[key] for key in ('workflow', 'files', 'selected', 'mode',
                     'dazedtl_source_versions', 'batch_link') if key in plan}
            value['settings'] = {'language': plan.get('settings', {}).get('language')}
            if signature[0] == stamp(path):
                self.plans[path] = (signature, value)
                self.plans.move_to_end(path)
                while len(self.plans) > 128:
                    self.plans.popitem(last=False)
            return value

        return self.once(('plan', identity), read)

    def process(self, root, job, plan):
        if self.session is None or not plan or plan.get('batch_link'):
            return process_view.summary(root, job)
        root = Path(root)
        try:
            signature = (digest(job), process_stamp(root))
        except (OSError, ValueError):
            return process_view.summary(root, job)
        cached = self.processes.get(root)
        if cached and cached[0] == signature:
            self.processes.move_to_end(root)
            return deepcopy(cached[1])
        value = process_view.summary(root, job)
        try:
            unchanged = signature[1] == process_stamp(root)
        except (OSError, ValueError):
            unchanged = False
        previous = self.processes.pop(root, None)
        if previous:
            self.request_rows -= len(previous[1]['requests'])
        if unchanged and len(value['requests']) <= 20_000:
            self.processes[root] = (signature, deepcopy(value))
            self.request_rows += len(value['requests'])
            while len(self.processes) > 128 or self.request_rows > 20_000:
                _, removed = self.processes.popitem(last=False)
                self.request_rows -= len(removed[1]['requests'])
        return value
