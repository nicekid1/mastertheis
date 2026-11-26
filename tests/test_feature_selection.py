"""Selection snapshots must preserve source geometry, CRS, attributes and scope."""
import json
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon
from app.feature_selection import prepare_selection, source_version


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'data').mkdir()
        self.run = self.project / 'runs' / 'new'
        self.run.mkdir(parents=True)
        self.source = self.project / 'data' / 'areas.geojson'
        self.frame = gpd.GeoDataFrame({'name': ['A', 'B', 'C'], 'value': [10, 20, 30]},
            geometry=[Polygon([(i*100, 0), (i*100+7, 3), (i*100+10, 10),
                               (i*100, 10), (i*100, 0)]) for i in range(3)], crs=3857)
        self.source.write_text(self.frame.to_json())

    def selection(self, **changes):
        group = dict(where='data', path='areas.geojson', version=source_version(str(self.source)), ids=[2, 0, 2])
        group.update(changes)
        return [group]

    def test_full_geometry_attributes_crs_and_deduplicated_scope(self):
        original = self.source.read_bytes()
        context = prepare_selection(str(self.project), str(self.run), self.selection())
        selected = gpd.read_file(self.run / 'selection/layer_1.geojson')
        self.assertEqual(list(selected['name']), ['A', 'C'])
        self.assertEqual(list(selected['value']), [10, 30])
        self.assertEqual(selected.crs, self.frame.crs)
        self.assertTrue(selected.geometry.iloc[1].equals_exact(self.frame.geometry.iloc[2], 0))
        self.assertEqual(self.source.read_bytes(), original)
        manifest = json.loads((self.run / 'selection/manifest.json').read_text())
        self.assertEqual(manifest[0]['rows'], [0, 2])
        self.assertIn('selection/layer_1.geojson', context)

    def test_rejects_stale_layer(self):
        request = self.selection()
        self.source.write_text(self.source.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            prepare_selection(str(self.project), str(self.run), request)

    def test_rejects_traversal_invalid_ids_and_excessive_selection(self):
        for changes in ({'path': '../outside.geojson'}, {'ids': [-1]}, {'ids': [True]},
                        {'ids': ['1']}, {'ids': [99]}, {'ids': list(range(5001))}):
            with self.subTest(changes=str(changes)[:60]), self.assertRaises(ValueError):
                prepare_selection(str(self.project), str(self.run), self.selection(**changes))

    def test_previous_run_output_is_resolved(self):
        root = self.project / 'runs' / 'previous' / 'pred_results'
        root.mkdir(parents=True)
        target = root / 'areas.geojson'
        target.write_bytes(self.source.read_bytes())
        request = self.selection(where='runs', run='previous', version=source_version(str(target)), ids=[1])
        prepare_selection(str(self.project), str(self.run), request)
        self.assertEqual(list(gpd.read_file(self.run / 'selection/layer_1.geojson')['name']), ['B'])

    def test_shapefile_companion_change_invalidates_version(self):
        shp = self.project / 'data' / 'fake.shp'
        dbf = shp.with_suffix('.dbf')
        shp.write_bytes(b'shape')
        dbf.write_bytes(b'attributes')
        before = source_version(str(shp))
        dbf.write_bytes(b'new attributes')
        self.assertNotEqual(before, source_version(str(shp)))


if __name__ == '__main__':
    unittest.main()
