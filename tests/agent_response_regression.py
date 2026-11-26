"""GIS conversation completion, without external model calls."""
import json
from pathlib import Path
import tempfile
import unittest
from src.agent.react_agent import GISReActAgent


class Stub:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        action, summary = next(self.replies)
        return {'text': 'Thought: test\nAction: ' + action + '\nArgs: ' + json.dumps({'summary': summary})}


class ResponseTests(unittest.TestCase):
    def run_agent(self, replies, **kwargs):
        engine = Stub(replies)
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data'
            data.mkdir()
            agent = GISReActAgent(engine, verbose=False, max_rounds=len(replies), **kwargs)
            result = agent.run('سلام', str(data), str(Path(temp) / 'run'))
        return result, engine

    def test_greeting_finishes_in_one_call_and_keeps_full_answer(self):
        answer = 'سلام!\n' + 'پاسخ کامل فارسی ' * 100
        result, engine = self.run_agent([('respond', answer)], allow_text_response=True)
        self.assertTrue(result.success)
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(result.output_files, [])
        self.assertEqual(result.history[-1]['summary'], answer.strip())

    def test_empty_response_is_not_accepted(self):
        result, engine = self.run_agent([('respond', ' '), ('respond', 'سلام')], allow_text_response=True)
        self.assertEqual(len(engine.calls), 2)
        self.assertTrue(result.success)
        self.assertIn('non-empty', engine.calls[1]['user_message'])

    def test_finish_still_requires_outputs(self):
        result, engine = self.run_agent([('finish', 'Done'), ('respond', 'Please specify the task')], allow_text_response=True)
        self.assertIn('Output Guard', engine.calls[1]['user_message'])
        self.assertEqual(result.history[-1]['action'], 'respond')

    def test_legacy_agents_cannot_use_response_only_completion(self):
        result, engine = self.run_agent([('respond', 'Hello')])
        self.assertFalse(result.success)


if __name__ == '__main__':
    unittest.main()
