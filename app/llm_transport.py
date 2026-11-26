"""Interactive request policy, independent of account token accounting."""
import math
import os


def configure_engine(engine):
    timeout = float(os.environ.get('GISCLAW_LLM_TIMEOUT_SECONDS', '60'))
    if not math.isfinite(timeout) or not 1 <= timeout <= 300:
        raise ValueError('GISCLAW_LLM_TIMEOUT_SECONDS must be between 1 and 300')
    client = getattr(engine, 'client', None)
    if client is not None and hasattr(client, 'with_options'):
        # No invisible SDK retries, even when account metering is disabled.
        engine.client = client.with_options(timeout=timeout, max_retries=0)
    if hasattr(engine, '_send_temperature'):
        # Avoid a second call for providers rejecting optional temperature.
        engine._send_temperature = False
    return engine
