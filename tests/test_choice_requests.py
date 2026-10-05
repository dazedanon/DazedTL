"""Choice collection must not repeat a physical menu during the write pass."""

from copy import deepcopy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dazedtl.compatibility.choice_requests import configure
from dazedtl.compatibility.worker_policy import configure_states
from dazedtl.settings.preferences import CHOICE_COLLECTION


class ChoiceRequestTests(unittest.TestCase):
    def test_frozen_choice_policy_keeps_first_pass_context_without_global_text_deduplication(self):
        calls = []
        module = SimpleNamespace(parseSS=lambda *_: None)
        module._choice_current = lambda command, index: command['parameters'][0][index]

        def search(page, pbar, jobList, filename):
            # The native direct choice handler runs on both visits. Collection
            # leaves Japanese in place; consume can also leave a rejected chunk.
            for command in page['list']:
                values = [module._choice_current(command, index) for index in range(len(command['parameters'][0]))]
                if all(values):
                    calls.append((values, [] if jobList else page['context'], filename))
            if not jobList:
                module.searchCodes(page, pbar, [[]] * 10, filename)
            return [0, 0]

        module.searchCodes = search
        original_current = module._choice_current
        pages = [{'context': [context], 'list': [{'code': 102, 'parameters': [['特別な品', 'やめる']]}]}
                 for context in ('Shop scene', 'Different scene')]
        frozen = deepcopy(pages)
        modules = {'modules.rpgmakermvmz': module, 'util.translation': SimpleNamespace()}
        with patch.dict('sys.modules', modules):
            configure_states({'engine': 'MVMZ'}, None, {'choiceCollection': CHOICE_COLLECTION})
            for page in pages:
                module.searchCodes(page, None, [], 'Map001.json')
            self.assertEqual(calls, [(page['list'][0]['parameters'][0], page['context'], 'Map001.json') for page in pages])
            self.assertEqual(pages, frozen)  # No synthetic translations to suppress the second visit.
            self.assertEqual(module._choice_current(pages[0]['list'][0], 0), '特別な品')
            # Reconfiguring is idempotent; legacy frozen plans retain their
            # original preparation/recovery behavior and request identities.
            configure_states({'engine': 'MVMZ'}, None, {'choiceCollection': CHOICE_COLLECTION})
            calls.clear()
            module.searchCodes(pages[0], None, [], 'Map001.json')
            self.assertEqual(len(calls), 1)
            configure_states({'engine': 'MVMZ'}, None, {})
            calls.clear()
            module.searchCodes(pages[0], None, [], 'Map001.json')
            self.assertEqual(len(calls), 2)
            self.assertIs(module.searchCodes, search)
            self.assertIs(module._choice_current, original_current)

    def test_second_pass_and_failures_do_not_suppress_choices_in_another_thread_or_call(self):
        entered, release = threading.Event(), threading.Event()
        errors, seen = [], []
        command = {'parameters': [['選択']]}
        module = SimpleNamespace(_choice_current=lambda command, index: command['parameters'][0][index])
        def search(page, pbar, jobList, filename):
            if page == 'waiting':
                entered.set()
                if not release.wait(1):
                    raise RuntimeError('Test synchronization failed')
                seen.append(module._choice_current(command, 0))
                raise ValueError('Generated parse failure')
            seen.append(module._choice_current(command, 0))
        module.searchCodes = search
        configure(module, True)
        def second_pass():
            try:
                module.searchCodes('waiting', None, [[]], 'Map001.json')
            except ValueError:
                seen.append(module._choice_current(command, 0))
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=second_pass)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            module.searchCodes('other', None, [], 'Map002.json')
        finally:
            release.set()
            worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(seen, ['選択', '', '選択'])


if __name__ == '__main__':
    unittest.main()
