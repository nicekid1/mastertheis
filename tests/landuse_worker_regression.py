"""Actual isolated GIS math with synthetic data and scripted model replies."""
import base64
import csv
import io
import json
import unittest
from app.isolated_analysis import execute, AnalysisError


class LanduseTests(unittest.TestCase):
    def job(self, limit=100000):
        features = []
        for n in range(4):
            x = n * 100
            features.append({'type': 'Feature', 'properties': {'land_use': 'residential' if n < 2 else 'park'},
                             'geometry': {'type': 'Polygon', 'coordinates': [[[x, 0], [x+100, 0], [x+100, 100], [x, 100], [x, 0]]]}})
        layer = {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:3857'}}, 'features': features}
        return {'files': {'data/test.geojson': base64.b64encode(json.dumps(layer).encode()).decode()},
                'selection': [], 'instruction': 'Summarize synthetic land use in hectares and percent; save CSV.', 'output_limit': limit}

    def engine(self):
        code = """g = gpd.read_file('dataset/test.geojson')
assert g.crs.to_epsg() == 3857
assert g.geometry.is_valid.all()
g['area_ha'] = g.area / 10000
table = g.groupby('land_use').agg(count=('land_use','size'), area_ha=('area_ha','sum')).reset_index()
table['percent'] = 100 * table.area_ha / table.area_ha.sum()
assert len(g) == 4 and abs(table.area_ha.sum() - 4) < 1e-9
table.to_csv('pred_results/landuse.csv', index=False)
print(table.to_string(index=False))
"""
        plan = iter([('execute', {'code': code}), ('finish', {'summary': 'کاربری مسکونی و پارک هرکدام ۲ هکتار و ۵۰ درصد؛ داده ساختگی است.'})])
        class Engine:
            def generate(self, **kwargs):
                action, args = next(plan)
                return {'text': 'Thought: test\nAction: ' + action + '\nArgs: ' + json.dumps(args)}
        return Engine()

    def test_actual_landuse_csv_and_full_summary(self):
        result = execute(self.job(), self.engine(), timeout=45)
        self.assertTrue(result['success'], result)
        self.assertIn('۲ هکتار', result['answer'])
        rows = list(csv.DictReader(io.StringIO(base64.b64decode(result['outputs']['landuse.csv']).decode())))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(int(row['count']), 2)
            self.assertAlmostEqual(float(row['area_ha']), 2)
            self.assertAlmostEqual(float(row['percent']), 50)

    def test_real_worker_reports_output_overflow(self):
        with self.assertRaises(AnalysisError) as caught:
            execute(self.job(limit=8), self.engine(), timeout=45)
        self.assertEqual(caught.exception.code, 'output_limit')
        self.assertEqual(caught.exception.status, 413)


if __name__ == '__main__':
    unittest.main()
