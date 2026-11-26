"""Real toolbox HTTP path, isolated by conftest's temporary workspace."""
import pytest
import test_urban_ops
from src.agent.urban_catalog import DEFINITIONS


@pytest.mark.parametrize('op', list(DEFINITIONS))
def test_urban_toolbox_api(client, tmp_path, op):
    fixtures = test_urban_ops.UrbanTests()
    fixtures.setUp()
    layers, params = fixtures.integration_cases()[op]
    response = client.post('/api/projects', json={'name': 'Urban API ' + op})
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    for role, data in layers.items():
        path = tmp_path / (role + '.gpkg')
        data.to_file(path, driver='GPKG')
        uploaded = client.post(f'/api/projects/{pid}/upload', params={'name': path.name}, content=path.read_bytes())
        assert uploaded.status_code == 200, uploaded.text
    response = client.post(f'/api/projects/{pid}/geoprocess', json={
        'op': op, 'inputs': {r: r + '.gpkg' for r in layers}, 'params': params, 'output': 'result'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['ok'], result
    assert {o['filename'] for o in result['outputs']} == {'result.geojson', 'result.method.json'}
    entries = client.get(f'/api/projects/{pid}/chat').json()['entries']
    assert entries[-1]['success'] is True


def test_urban_catalog_and_bad_requests(client):
    group = next(g for g in client.get('/api/tools').json() if g['category'] == 'urban_analysis')
    assert {op['op'] for op in group['ops']} == set(DEFINITIONS)
    assert all(op['title_fa'] and op['desc_fa'] for op in group['ops'])
    pid = client.post('/api/projects', json={'name': 'Urban validation'}).json()['id']
    for change in ({'inputs': []}, {'params': []}, {'output': 42}, {'inputs': {'parcels': 42}}, {'inputs': {}}):
        body = {'op': 'parcel_profile', 'inputs': {}, 'params': {}, 'output': 'result'}
        body.update(change)
        response = client.post(f'/api/projects/{pid}/geoprocess', json=body)
        assert response.status_code == 400, response.text
        assert response.json()['error']


def test_network_polygon_error_is_actionable(client, tmp_path):
    fixtures = test_urban_ops.UrbanTests()
    fixtures.setUp()
    path = tmp_path / 'roads.gpkg'
    fixtures.zones.to_file(path, driver='GPKG')
    pid = client.post('/api/projects', json={'name': 'Bad road geometry'}).json()['id']
    client.post(f'/api/projects/{pid}/upload', params={'name': path.name}, content=path.read_bytes())
    response = client.post(f'/api/projects/{pid}/geoprocess', json={
        'op': 'network_connectivity', 'inputs': {'roads': path.name}, 'output': 'network'})
    assert response.status_code == 400
    body = response.json()
    assert body['error_detail']['code'] == 'road_geometry'
    assert 'roads.gpkg' in body['error_detail']['fa']
    assert 'Polygon' in body['error_detail']['fa']
    assert 'Traceback' not in body['error']
    assert 'Traceback' in body['observation'] or 'stack trace' in body['observation']
