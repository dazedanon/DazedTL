"""Verified incremental JSON outputs and native-reader resume, without game writes."""

from functools import lru_cache, wraps
import builtins
import io
from pathlib import Path
import threading

from dazedtl.storage import write_json
from dazedtl.translation.files import decode_json, digest, project_path, read_json

INDEX = 'log/dazedtl-checkpoints.json'


def can_collect_outputs(job):
    """Batch collection writes scratch JSON; only consumption translates it.

    Keep explicit completed-file receipts and unknown legacy phases readable.
    """
    return (job.get('mode') != 'batch' or bool(job.get('completed'))
            or job.get('phase') not in {'preparing', 'collect', 'collect_done', 'submit', 'poll', 'polling', 'poll_status', 'failed', 'canceled'})


@lru_cache(maxsize=1024)
def _json_digest(path, signature):
    raw = Path(path).read_bytes()
    if not isinstance(decode_json(raw), (dict, list)):
        raise ValueError('A progress checkpoint must contain game JSON.')
    return digest(raw)


def outputs(root, plan):
    root = Path(root)
    path = project_path(root, INDEX, exists=False)
    if not path.exists():
        return {}
    record = read_json(path)
    if record.get('version') != 1 or record.get('plan_hash') != digest((root / 'plan.json').read_bytes()):
        raise ValueError('Progress checkpoints do not match this saved run.')
    allowed = {row['name'] for row in plan['files']}
    result = {}
    for name, expected in record.get('files', {}).items():
        if name not in allowed:
            raise ValueError('A progress checkpoint is outside this run’s file scope.')
        output = project_path(root, 'translated/' + name)
        stat = output.stat()
        actual = _json_digest(str(output), (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        if actual == expected:
            result[name] = expected
        # A later atomic write can precede its receipt; only matching bytes count.
    return result


def install(module, root, plan):
    if module is None or plan.get('mode') not in {'translate', 'offline', 'batch'}:
        return
    root = Path(root).resolve()
    names = {row['name'] for row in plan['files']}
    plan_hash = digest((root / 'plan.json').read_bytes())
    lock = threading.Lock()
    native_save = getattr(module.saveProgress, '_dazedtl_native', module.saveProgress)
    native_open = getattr(getattr(module, 'open', builtins.open), '_dazedtl_native', getattr(module, 'open', builtins.open))

    @wraps(native_save)
    def save(data, filename, *args, **kwargs):
        saved = native_save(data, filename, *args, **kwargs)
        if saved and filename in names:
            path = project_path(root, 'translated/' + filename)
            raw = path.read_bytes()
            if not isinstance(decode_json(raw), (dict, list)):
                raise ValueError('The engine checkpoint is not game JSON.')
            with lock:
                index = project_path(root, INDEX, exists=False)
                record = read_json(index) if index.exists() else {'version': 1, 'plan_hash': plan_hash, 'files': {}}
                if record.get('plan_hash') != plan_hash:
                    raise ValueError('The checkpoint owner changed.')
                record['files'][filename] = digest(raw)
                write_json(index, record)
        return saved

    @wraps(native_open)
    def opening(file, *args, **kwargs):
        mode = kwargs.get('mode', args[0] if args else 'r')
        # Batch consume must keep its exact frozen request grouping. It already
        # reuses provider receipts; only Live reads partially translated inputs.
        if plan.get('mode') in {'translate', 'offline'} and mode in {'r', 'rt'} and isinstance(file, (str, Path)):
            path = Path(file).resolve()
            if path.parent == root / 'files' and path.name in names:
                retained = outputs(root, plan)
                if path.name in retained:
                    raw = project_path(root, 'translated/' + path.name).read_bytes()
                    if digest(raw) != retained[path.name]:
                        raise ValueError('The saved progress changed while reopening it.')
                    stream = io.StringIO(raw.decode(kwargs.get('encoding') or 'utf-8-sig'))
                    stream.name = str(path)
                    return stream
        return native_open(file, *args, **kwargs)

    save._dazedtl_native = native_save
    opening._dazedtl_native = native_open
    module.saveProgress, module.open = save, opening
