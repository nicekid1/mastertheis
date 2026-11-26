"""Server-controlled temporary feature switches."""
import os


def text_chat_enabled():
    # GIS chat is the default experience. Retain text-only chat for later use,
    # but do not expose it unless an operator explicitly enables it.
    return os.environ.get('GISCLAW_TEXT_CHAT_ENABLED', '0') == '1'
