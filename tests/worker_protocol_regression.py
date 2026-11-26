"""Classify worker failures without leaking payloads or inventing their cause."""
import errno
import io
import json
import unittest
from unittest.mock import patch
from app import isolated_analysis as analysis
from app.isolated_worker import WorkerFailure, error_code


class Process:
    def __init__(self, data):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(data)

    def kill(self):
        pass

    def wait(self, **kwargs):
        return 0


class Engine:
    def generate(self, **kwargs):
        raise AssertionError('Invalid worker input must not reach the provider')


class ProtocolTests(unittest.TestCase):
    def test_completed_tools_survive_a_later_model_failure(self):
        frames = [{'type': 'step', 'action': 'execute', 'code': 'print(2)', 'observation': '2', 'thought': 'private reasoning'},
                  {'type': 'llm', 'system_prompt': '', 'user_message': 'continue'}]
        wire = b''.join(json.dumps(f).encode() + b'\n' for f in frames)
        with patch.object(analysis.subprocess, 'Popen', return_value=Process(wire)), \
             patch.object(analysis.subprocess, 'run'), self.assertRaises(AssertionError) as caught:
            analysis.execute({}, Engine())
        self.assertEqual(caught.exception.analysis_steps[0]['code'], 'print(2)')
        self.assertNotIn('thought', caught.exception.analysis_steps[0])

    def execute(self, data):
        with patch.object(analysis.subprocess, 'Popen', return_value=Process(data)), \
             patch.object(analysis.subprocess, 'run'):
            return analysis.execute({}, Engine())

    def test_protocol_failures_are_distinct(self):
        cases = [(b'', 'worker_exited'), (b'secret-payload\n', 'worker_invalid_json'),
                 (b'[]\n', 'worker_invalid_message'), (b'{"type":"unknown"}\n', 'worker_invalid_message'),
                 (json.dumps({'type': 'llm', 'system_prompt': '', 'user_message': {}}).encode() + b'\n', 'analysis_context_invalid')]
        for payload, code in cases:
            with self.subTest(code=code), self.assertRaises(analysis.AnalysisError) as caught:
                self.execute(payload)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('secret-payload', str(caught.exception))

    def test_long_text_reaches_model_unchanged_without_local_character_quota(self):
        for system, question in [('s' * 16000, 'q' * 16001), ('دستور ' * 10000, 'متن تحلیل ' * 20000)]:
            with self.subTest(system_chars=len(system), question_chars=len(question)):
                frames = [dict(type='llm', system_prompt=system, user_message=question),
                          dict(type='done', success=True, answer='پاسخ', outputs={})]
                wire = b''.join(json.dumps(frame).encode() + b'\n' for frame in frames)
                calls = []
                class RecordingEngine:
                    def generate(self, **kwargs):
                        calls.append(kwargs)
                        return {'text': 'پاسخ'}
                with patch.object(analysis.subprocess, 'Popen', return_value=Process(wire)), \
                     patch.object(analysis.subprocess, 'run'):
                    result = analysis.execute({}, RecordingEngine())
                self.assertTrue(result['success'])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['system_prompt'], system)
                self.assertEqual(calls[0]['user_message'], question)

    def test_invalid_model_message_types_still_never_reach_provider(self):
        for system, question in [(None, 'valid'), ('valid', None), ([], 'valid'), ('valid', 123)]:
            with self.subTest(system=system, question=question), self.assertRaises(analysis.AnalysisError) as caught:
                self.execute(json.dumps(dict(type='llm', system_prompt=system, user_message=question)).encode() + b'\n')
            self.assertEqual(caught.exception.code, 'analysis_context_invalid')
            self.assertEqual(caught.exception.status, 502)

    def test_worker_error_codes_are_allowlisted(self):
        for code, status in [('output_limit', 413), ('temporary_storage_full', 507), ('worker_memory', 503), ('output_link', 422), ('secret', 502), ({'malicious': 'secret'}, 502)]:
            with self.subTest(code=code), self.assertRaises(analysis.AnalysisError) as caught:
                self.execute(json.dumps({'type': 'error', 'code': code, 'message': 'secret-key-prompt'}).encode() + b'\n')
            self.assertEqual(caught.exception.status, status)
            self.assertNotIn('secret', str(caught.exception))

    def test_worker_error_classification_contains_no_exception_text(self):
        self.assertEqual(error_code(WorkerFailure('output_limit')), 'output_limit')
        self.assertEqual(error_code(WorkerFailure('secret')), 'worker_execution_failed')
        self.assertEqual(error_code(OSError(errno.ENOSPC, 'secret-file')), 'temporary_storage_full')
        self.assertEqual(error_code(MemoryError('secret')), 'worker_memory')
        self.assertEqual(error_code(ValueError('secret')), 'worker_execution_failed')


if __name__ == '__main__':
    unittest.main()
