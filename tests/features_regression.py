import os
import unittest
from unittest.mock import patch
from app.features import text_chat_enabled


class FeatureTests(unittest.TestCase):
    def test_separate_text_chat_is_disabled_by_default(self):
        with patch.dict(os.environ):
            os.environ.pop('GISCLAW_TEXT_CHAT_ENABLED', None)
            self.assertFalse(text_chat_enabled())

    def test_only_explicit_operator_setting_enables_text_chat(self):
        for value, expected in [('0', False), ('1', True), ('', False), ('invalid', False)]:
            with self.subTest(value=value), patch.dict(os.environ, {'GISCLAW_TEXT_CHAT_ENABLED': value}):
                self.assertEqual(text_chat_enabled(), expected)


if __name__ == '__main__':
    unittest.main()
