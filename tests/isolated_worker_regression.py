"""Real container test, stdlib only. Run on a Docker-enabled test host.

Uses no host mounts, real user data or live model. Does not enable production
readiness: that requires rootless Docker separately.
"""
import ast
import base64
import json
import os
from pathlib import Path
import subprocess
import unittest


class WorkerRegression(unittest.TestCase):
    def test_container_boundary_and_gis(self):
        # Reuse production flags without importing the web stack on the host.
        module = ast.parse(Path('app/isolated_analysis.py').read_text())
        function = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'command')
        namespace = {'os': os}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<command>', 'exec'), namespace)
        name = 'gisclaw-isolation-regression-' + str(os.getpid())
        cmd = namespace['command'](name)
        # The installed image supplies GIS dependencies; inject current worker
        # source as program text, never mount the source or workspace.
        cmd[-2:] = ['-c', Path('app/isolated_worker.py').read_text()]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        code = """import os, socket
assert os.getuid() == 65534
assert not os.path.exists('/workspace/.gisclaw/accounts.sqlite3')
assert not os.path.exists('/var/run/docker.sock')
assert not any(k.endswith('API_KEY') for k in os.environ)
try:
    open('/app/escape-test', 'w').close()
    raise AssertionError('root filesystem is writable')
except OSError:
    pass
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('1.1.1.1', 53))
    raise AssertionError('network is available')
except OSError:
    pass
finally:
    s.close()
g = gpd.GeoDataFrame({'name':['test']}, geometry=[Point(0,0)], crs='EPSG:3857')
g['geometry'] = g.buffer(100)
assert 30000 < g.area.iloc[0] < 32000
g.to_file('pred_results/buffer.geojson', driver='GeoJSON')
"""
        replies = ['Thought: test boundary and real GIS\nAction: execute\nArgs: ' + json.dumps({'code': code}),
                   'Thought: done\nAction: finish\nArgs: {"summary":"Isolation and buffer verified"}']
        try:
            proc.stdin.write(json.dumps({'files': {}, 'instruction': 'Test isolation and make a buffer', 'output_limit': 100000}) + '\n')
            proc.stdin.flush()
            for _ in range(6):
                message = json.loads(proc.stdout.readline())
                if message['type'] == 'done':
                    self.assertTrue(message['success'], message)
                    self.assertEqual(message['answer'], 'Isolation and buffer verified')
                    self.assertIn('buffer.geojson', message['outputs'])
                    output = json.loads(base64.b64decode(message['outputs']['buffer.geojson']))
                    self.assertEqual(len(output['features']), 1)
                    break
                if message['type'] == 'step':
                    self.assertNotIn('thought', message)
                    continue
                self.assertEqual(message['type'], 'llm')
                self.assertTrue(replies, message)
                proc.stdin.write(json.dumps({'text': replies.pop(0)}) + '\n')
                proc.stdin.flush()
            else:
                self.fail('No final response')
        finally:
            proc.kill()
            proc.communicate(timeout=10)
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
