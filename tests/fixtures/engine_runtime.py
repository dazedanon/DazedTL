"""An offline startup and parser probe using only a generated miniature game."""

import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch


root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))


def offline(*_args, **_kwargs):
    raise RuntimeError("Network access is disabled in the bundled engine probe.")


def no_external_engine(event, arguments):
    if event == "open" and isinstance(arguments[0], (str, bytes)):
        path = Path(os.fsdecode(arguments[0])).absolute()
        if any(path.is_relative_to(root.parent / name) for name in ("DazedMTLTool", "DazedMTLTool-engine")):
            raise RuntimeError("The bundled engine attempted to read a sibling checkout.")


socket.create_connection = socket.socket.connect = socket.socket.connect_ex = offline
sys.addaudithook(no_external_engine)

from dazedtl.api.server import Application
from dazedtl.compatibility.runtime import ENGINE_ROOT

game = temporary / "game"
game.mkdir()
original = json.dumps([None, {"id": 1, "name": "薬", "description": "体力を回復する。", "note": ""}], ensure_ascii=False).encode()
(game / "Items.json").write_bytes(original)
app = Application(temporary / "profile", False)
try:
    assert app.state()["project"] is None
    assert app.backend.source == ENGINE_ROOT
    with app.backend.context():
        from util.paths import PROMPT_PATH, runtime_data_file
        from util.skills import load_system_prompt, load_project_setup
        from desktop.backend.manual import signature
        # A real saved run's pre-relocation signature must still pass the native
        # resume guard. Updating engine behavior needs its own recovery decision.
        assert signature("RPG Maker MV/MZ") == "b0aa0546c511a7b996fad0dad1d62619258d5eb7ec1f23e9e0ebf113bd9284aa"
        # Real engine preparation imports must reach the LF adapter, including
        # a file whose only difference is CRLF (hidden by read_text()).
        from util.dazedformat import format_json_files
        from util.project_preparation import format_plugins_js
        prepared = temporary / "formatting"
        prepared.mkdir()
        (prepared / "Items.json").write_bytes(b'{\r\n    "name": "Potion"\r\n}')
        (prepared / "plugins.js").write_bytes(b"var $plugins = [];\r\n")
        assert format_json_files(prepared) == (1, [])
        format_plugins_js(prepared / "plugins.js")
        assert (prepared / "Items.json").read_bytes() == b'{\n    "name": "Potion"\n}'
        assert (prepared / "plugins.js").read_bytes() == b"var $plugins = [];\n"
        assert runtime_data_file(PROMPT_PATH).is_relative_to(root / "backend/dazedtl/data")
        assert load_system_prompt() and load_project_setup("rpgmaker")
        manual = app.backend.manual
        listing = manual.inspect(str(game), "RPG Maker MV/MZ")
        job = manual.start(str(game), "RPG Maker MV/MZ", ["Items.json"], listing["revision"])
    controller = manual.controller(job["id"])
    controller.worker.join(5)
    result = manual.jobs[job["id"]]
    assert result["status"] == "complete", (result["status"], result.get("message"), result.get("log"))
    assert result["estimate"]["input_tokens"] > 0
    assert (game / "Items.json").read_bytes() == original
    frozen = manual.folder(job["id"]) / "context/system.md"
    assert frozen.read_bytes() == (root / "backend/dazedtl/data/skills/system.md").read_bytes()
    # A map call can contain a malformed attempt, an accepted retry, a refused
    # chunk, and another success. Keep every body and only its own validation;
    # refusal loops must preserve source without making more provider calls.
    with app.backend.context():
        from util import translation
        from util.batch_providers import detect_batch_provider
        # Namespaced Claude/GPT IDs must stay on OpenRouter's Live transport;
        # the preset must never select a native provider or its Batch API.
        for model in ('anthropic/claude-sonnet-4.5', 'openai/gpt-4.1'):
            route = {'model': model, 'API_PROVIDER': 'openai', 'api': 'https://openrouter.ai/api/v1'}
            app.backend.validate_route(route)
            assert not app.backend.provider_defaults(route)['batch_supported']
            assert detect_batch_provider(model, api_url=route['api'], api_provider='openai') is None
            params = translation.buildOpenAIRequest('Translate.', '薬', [], 0, 'json', model,
                numLines=1, api_provider='openai', api_url=route['api'])
            assert params['model'] == model and 'max_tokens' in params and 'max_completion_tokens' not in params
        from dazedtl.compatibility.run_evidence import Evidence
        from dazedtl.compatibility.request_parameters import configure_builders
        from dazedtl.compatibility.process_view import source_values, payload, summary
        from dazedtl.settings.preferences import GENERATION_PARAMETERS
        live_root = temporary / 'live'
        live_root.mkdir()
        os.chdir(live_root)
        evidence = Evidence(live_root, 'translate')
        sent = []
        bodies = ['malformed provider JSON', '{"translations":["Potion"]}',
                  '{"translations":["I cannot translate explicit sexual content."]}',
                  '{"translations":["Heal"]}']
        def completion(**params):
            sent.append(source_values(params))
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                message=SimpleNamespace(content=bodies[len(sent)-1], refusal=None))],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7))
        config = translation.TranslationConfig(model='gpt-4', prompt='Translate the supplied text.', vocab='', batchSize=1,
            useSfxReference=False, logFilePath=str(live_root/'log/translation.txt'), mismatchLogPath=str(live_root/'log/mismatchHistory.txt'))
        evidence.install(translation)
        configure_builders(translation, GENERATION_PARAMETERS, evidence.record)
        with patch.dict(os.environ, {'BATCH_PHASE': '', 'API_PROVIDER': 'openai', 'key': 'fixture', 'api': '',
                                     'TRANSLATION_RUN_LOG': str(live_root/'log/translation.txt')}), \
                patch.object(translation.openai, 'chat', SimpleNamespace(completions=SimpleNamespace(create=completion))):
            output, tokens = translation.translateAI(['薬', '毒', '回復'], [], config, filename='Map001.json', mismatchList=[])
        assert output == ['Potion', '毒', 'Heal'], output
        assert tokens == [20, 8], tokens
        assert sent == [{'Line1': '薬'}, {'Line1': '薬'}, {'Line1': '毒'}, {'Line1': '回復'}], sent
        rows = [payload(live_root, index) for index in range(4)]
        assert [row['response']['text'] for row in rows] == bodies
        assert [row['state'] for row in rows] == ['rejected', 'validated', 'rejected', 'validated'], rows
        assert [row['translations'] for row in rows] == [None, ['Potion'], None, ['Heal']]
        result = summary(live_root, {'mode': 'translate', 'status': 'complete'})
        assert (result['received'], result['validated'], result['rejected'], result['retryBlocked']) == (4, 2, 2, False), result
        assert result['validationIssues'] == [{'file': 'Map001.json', 'rejected': 1}], result
        assert rows[0]['error']['code'] == 'replaced_response', rows[0]
        with evidence.connect() as connection:
            sources = [json.loads(row[0]) for row in connection.execute('SELECT sources FROM requests ORDER BY id')]
        assert sources[0] == sources[1] and sources[1] != sources[2] != sources[3], sources
    # Structured refusals survive the real native normalizers, including empty
    # bodies; otherwise they are indistinguishable from generic parse failures.
    from dazedtl.compatibility.provider_responses import install as retain_refusals
    from util import batch_providers, batch_history
    retain_refusals()
    refusal, error = batch_providers._openai_result({'response': {'status_code': 200, 'body': {
        'choices': [{'message': {'content': None, 'refusal': 'Cannot provide this translation.'}}],
        'usage': {'prompt_tokens': 5, 'completion_tokens': 2}}}})
    assert not error and refusal['refusal'] and refusal['prompt_tokens'] == 5
    refusal = batch_history._result_entry_from_message(SimpleNamespace(content=[], stop_reason='refusal',
        usage=SimpleNamespace(input_tokens=5, output_tokens=2, cache_read_input_tokens=0, cache_creation_input_tokens=0)))
    assert refusal['refusal'] and refusal['prompt_tokens'] == 5
    for name, module in list(sys.modules.items()):
        if name.startswith(("util.", "modules.", "desktop.backend.")) and getattr(module, "__file__", None):
            assert Path(module.__file__).is_relative_to(ENGINE_ROOT), name
    print("Bundled startup, frozen guidance, saved-run signature and isolated parser estimation passed.")
finally:
    app.guided.batch_monitor.close()
    app.translation.jobs.close()
    app.images.close()
    app.backend.close()
    app.workspace_lock.close()
