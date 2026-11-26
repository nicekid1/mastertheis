"""Untrusted per-job worker. No credentials, network, host mounts or accounts DB."""
import base64
import contextlib
import errno
import json
import os
import re
from pathlib import Path
import sys


class WorkerFailure(ValueError):
    """Only fixed machine codes cross the worker error boundary."""


def error_code(exc):
    if isinstance(exc, WorkerFailure) and str(exc) in ('output_limit', 'output_link'):
        return str(exc)
    if isinstance(exc, MemoryError):
        return 'worker_memory'
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return 'temporary_storage_full'
    return 'worker_execution_failed'


def main():
    wire = sys.stdout
    def send(value):
        wire.write(json.dumps(value) + '\n')
        wire.flush()
    job = json.loads(sys.stdin.readline(80 * 1024 * 1024))
    root = Path('/tmp/job')
    root.mkdir()
    (root / 'data').mkdir()
    for name, content in job['files'].items():
        path = root / name
        if path.is_absolute() and root not in path.resolve().parents:
            raise ValueError('Invalid input path')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(content, validate=True))

    class ProxyEngine:
        supports_segmented_user = False
        def generate(self, prompt='', system_prompt=None, user_message=None, **kwargs):
            send({'type': 'llm', 'system_prompt': system_prompt or '',
                  'user_message': user_message or prompt})
            response = json.loads(sys.stdin.readline(1024 * 1024))
            if response.get('error'):
                raise RuntimeError(response['error'])
            return response

    # Agent/library print output must not be confused with the RPC protocol.
    with contextlib.redirect_stdout(sys.stderr):
        from src.agent.react_agent import GISReActAgent
        from src.agent import geo_ops
        from app.feature_selection import prepare_selection, source_version
        run_dir = root / 'run'
        run_dir.mkdir()
        groups = job.get('selection', [])
        # The coordinator checked source identity before/after snapshotting.
        # Absolute paths and mtimes change inside this disposable filesystem.
        for group in groups:
            group['version'] = source_version(str(root / group['where'] / group['path']))
        selection = prepare_selection(str(root), str(run_dir), groups)
        def operation_help(op=''):
            if op not in geo_ops.REGISTRY:
                return 'Operations: ' + ', '.join(geo_ops.REGISTRY)
            return json.dumps(next(item for group in geo_ops.catalog() for item in group['ops'] if item['op'] == op), default=str)
        def prompt(_):
            return ('You are a conversational GIS analyst. Reply EXACTLY as Thought: ...\nAction: tool\nArgs: JSON. '
                    'For greetings, explanations, questions or clarification, call respond(summary) directly. '
                    'For a greeting, respond in the user language in ONE call, without inspecting files or using other tools. '
                    'respond returns a text answer and does not require output files. Never create dummy files to answer. '
                    'For tasks requiring saved maps or datasets, use finish(summary) only after producing and verifying them. '
                    'Only source data and explicitly selected output layers are available in this job. '
                    'Unselected previous outputs are not included. If the user requests an absent previous '
                    'output, ask them to select that layer on the map or upload it as source data; do not invent it. '
                    'Inspect real data and CRS; use metric CRS for distances. Do not invent results. '
                    'Save verified outputs to pred_results/ and finish with a summary in the user language. '
                    'Tools: list_files(); load_vector(path,var_name); load_raster(path,var_name); '
                    'inspect(var_name); operation_help(op) (empty op lists operations); '
                    'geoprocess(op,inputs,params,output,save_as); execute(code); finish(summary); respond(summary). '
                    'Prefer geoprocess for supported operations: call operation_help first to learn '
                    'the operation schema. Python execution has geopandas as gpd, numpy as np, '
                    'pandas as pd, rasterio, shapely and matplotlib. Print checks after computations.')
        agent = GISReActAgent(ProxyEngine(), timeout=60, max_rounds=12, verbose=False, context_chars=4000,
                              system_prompt_builder=prompt, allow_text_response=True,
                              extra_tools={'operation_help': (operation_help, 'Operation help')})
        def step(event):
            # Only tool activity, not the model's private reasoning.
            send({'type': 'step', 'action': str(event.get('action', ''))[:100],
                  'code': str(event.get('code', ''))[:16000],
                  'observation': str(event.get('observation_full') or event.get('observation') or '')[:4000],
                  'success': event.get('success') is not False})
        result = agent.run(job['instruction'] + selection, str(root / 'data'), str(run_dir), on_step=step)
        outputs = {}
        total = 0
        for path in (run_dir / 'pred_results').rglob('*'):
            if path.is_symlink():
                raise WorkerFailure('output_link')
            if path.is_file():
                total += path.stat().st_size
                if total > job['output_limit']:
                    raise WorkerFailure('output_limit')
                outputs[str(path.relative_to(run_dir / 'pred_results'))] = base64.b64encode(path.read_bytes()).decode()
        answer = next((str(item.get('summary') or item.get('observation', '')) for item in reversed(result.history)
                       if item.get('action') in ('finish', 'respond')), '')
        # Strip toolkit bookkeeping; retain the model's complete final answer.
        answer = re.sub(r'^\s*Task complete\s*\n?', '', answer)
        answer = re.sub(r'^\s*Summary:\s*', '', answer)
        answer = re.split(r'\n(?:Output files \(\d+\):|⚠️? ?No output files)', answer)[0].strip()
    send({'type': 'done', 'success': result.success, 'answer': answer,
          'outputs': outputs, 'rounds': result.total_rounds, 'code': result.code[:100000]})


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not send raw exceptions: they may contain file contents or code.
        sys.stdout.write(json.dumps({'type': 'error', 'code': error_code(exc)}) + '\n')
        sys.stdout.flush()
