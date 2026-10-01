"""Public application views; legacy worker records never cross the UI boundary."""


def pick(value, names):
    return {name: value[name] for name in names if name in value}


def project(value):
    if value is None:
        return None
    return pick(value, ('id', 'name', 'source', 'engine', 'engine_label', 'method', 'phase', 'available',
                        'status', 'detail', 'operation', 'next_label', 'attention'))


def application(value):
    return {'project': project(value['project']), 'recent': [project(item) for item in value['recent']],
            'screen': value['screen'], 'running': value['running'], 'observing': value['observing'], 'provider_ready': value['provider_ready']}


def documents(value):
    return {name: pick(document, ('text', 'revision', 'path')) for name, document in value.items()}


def job(value):
    if value is None:
        return None
    result = pick(value, ('id', 'status', 'message', 'label', 'mode', 'phase', 'model', 'files',
                          'progress', 'log', 'estimate', 'outputs', 'outputsAvailable', 'approval', 'action', 'result', 'created', 'updated'))
    result.setdefault('log', [])
    return result


def guided(value, project_id):
    native = value['project']
    return {
        'projectId': project_id,
        'source': native['source'],
        'engine': native['engine'],
        'dataPath': native['data'],
        'encrypted': native['encrypted'],
        'hasPlugins': bool(native['plugins']),
        'aceAvailable': value['ace_available'],
        'step': value['step'],
        'form': value['form'],
        'preferences': value['preferences'],
        'optionsDraft': value['options_draft'],
        'engineSchema': value['engine_schema'],
        'files': [pick(item, ('name', 'default', 'size', 'group')) for item in native['files']],
        'selection': native['selected'],
        'importedFiles': native['imported'],
        'collectionError': native.get('collection_error', ''),
        'operations': [job(item) for item in value['jobs']],
        'run': job(value['manual_job']),
        'runs': [job(item) for item in value['runs']],
        'activeJobId': value['active'] or None,
        'phase': value['phase'],
        'phaseFiles': value['phase_files'],
        'sourceStatus': value['source_status'],
        'readiness': value['readiness'],
        'documents': documents(value['documents']),
        'drafts': documents(value.get('draft', {}).get('documents', {})),
        'provider': {
            'model': value['provider']['model'],
            'defaultMode': value['provider']['default_mode'],
            'batchSupported': value['provider']['batch_supported'],
            'ready': value['provider']['credential_ready'],
            'enabled': value['allow_providers'],
        },
    }


def settings(value):
    return pick(value, ('revision', 'values', 'modelOptions', 'defaultEntriesPerRequest', 'draft',
                        'activeConnectionId', 'connections', 'providers', 'checksEnabled'))


def preview(value):
    return pick(value, ('token', 'action', 'label', 'destination', 'files', 'paths', 'options', 'confirmation', 'rewrap', 'additions'))


def error(exc):
    if isinstance(exc, FileNotFoundError):
        return {'code': 'not_found', 'message': str(exc)}
    if isinstance(exc, ValueError):
        return {'code': 'validation', 'message': str(exc)}
    if isinstance(exc, OSError):
        return {'code': 'storage', 'message': 'The file operation could not finish.'}
    return {'code': 'internal', 'message': 'The operation could not finish.'}
