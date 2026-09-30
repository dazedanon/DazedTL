"""Public application views; legacy worker records never cross the UI boundary."""


def pick(value, names):
    return {name: value[name] for name in names if name in value}


def project(value):
    if value is None:
        return None
    return pick(value, ('id', 'name', 'source', 'engine', 'method', 'phase', 'available',
                        'status', 'detail', 'next_label', 'attention'))


def application(value):
    return {'project': project(value['project']), 'recent': [project(item) for item in value['recent']],
            'screen': value['screen'], 'running': value['running'], 'provider_ready': value['provider_ready']}


def documents(value):
    return {name: pick(document, ('text', 'revision', 'path')) for name, document in value.items()}


def job(value):
    if value is None:
        return None
    result = pick(value, ('id', 'status', 'message', 'label', 'mode', 'phase', 'model', 'files',
                          'progress', 'log', 'estimate', 'outputs', 'approval'))
    result.setdefault('log', [])
    return result


def guided(value, project_id):
    native = value['project']
    return {
        'projectId': project_id,
        'source': native['source'],
        'files': [pick(item, ('name', 'default', 'size')) for item in native['files']],
        'selection': native['selected'],
        'importedFiles': native['imported'],
        'collectionError': native.get('collection_error', ''),
        'operations': [job(item) for item in value['jobs']],
        'run': job(value['manual_job']),
        'activeJobId': value['active'] or None,
        'phase': value['phase'],
        'phaseFiles': value['phase_files'],
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
    result = pick(value, ('revision', 'values', 'engines', 'active_key', 'keys', 'draft'))
    result['keys'] = [pick(item, ('name', 'endpoint', 'keyless', 'has_secret')) for item in value['keys']]
    result['fields'] = [pick(field, ('key', 'type', 'label', 'min', 'max', 'choices', 'help'))
                        for field in value['fields']]
    return result


def preview(value):
    return {**pick(value, ('token', 'label', 'destination', 'files')),
            'options': {'files': value['options'].get('files', [])}}


def error(exc):
    if isinstance(exc, FileNotFoundError):
        return {'code': 'not_found', 'message': str(exc)}
    if isinstance(exc, ValueError):
        return {'code': 'validation', 'message': str(exc)}
    if isinstance(exc, OSError):
        return {'code': 'storage', 'message': 'The file operation could not finish.'}
    return {'code': 'internal', 'message': 'The operation could not finish.'}
