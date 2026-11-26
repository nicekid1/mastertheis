import json
import os
import tempfile
import unittest

import geopandas as gpd
from shapely.geometry import box, Point, LineString
from src.agent import geo_ops, urban_ops
from src.agent.urban_catalog import DEFINITIONS


def frame(geometries, **columns):
    return gpd.GeoDataFrame(columns, geometry=geometries, crs=32639)


class UrbanTests(unittest.TestCase):
    def setUp(self):
        self.zones = frame([box(0, 0, 10, 10)], population=[100])
        self.buildings = frame([box(1, 1, 3, 3)], floors=[2])
        self.half = frame([box(0, 0, 5, 10)])
        self.roads = frame([LineString([(0, 0), (100, 0)]), LineString([(200, 0), (300, 0)])])
        self.origins = frame([Point(0, 0)])

    def run_op(self, op, inputs, **params):
        return urban_ops.run(op, inputs, params)

    def test_profile_density_and_far(self):
        profile = self.run_op('parcel_profile', {'parcels': self.zones})
        self.assertEqual(profile.area_m2.iloc[0], 100)
        self.assertEqual(profile.perimeter_m.iloc[0], 40)
        density = self.run_op('urban_density', {'zones': self.zones, 'buildings': self.buildings}, population_field='population')
        self.assertEqual(density.building_count.iloc[0], 1)
        self.assertEqual(density.population_km2.iloc[0], 1_000_000)
        result = self.run_op('coverage_far', {'parcels': self.zones, 'buildings': self.buildings}, floors_field='floors')
        self.assertEqual(result.coverage_pct.iloc[0], 4)
        self.assertAlmostEqual(result.estimated_far.iloc[0], .08)
        self.assertNotIn('coverage_pct', self.zones)

    def test_service_and_population_coverage_no_double_counting(self):
        duplicate = frame([box(0, 0, 5, 10), box(0, 0, 5, 10)])
        result = self.run_op('population_coverage', {'zones': self.zones, 'coverage': duplicate}, population_field='population')
        self.assertEqual(result.estimated_covered_population.iloc[0], 50)
        supply = self.run_op('service_provision', {'zones': self.zones, 'services': duplicate}, population_field='population', target_per_person=1)
        self.assertEqual(supply.supply_total.iloc[0], 50)
        self.assertEqual(supply.supply_deficit.iloc[0], 50)
        zero = self.zones.copy(); zero['population'] = 0
        supply = self.run_op('service_provision', {'zones': zero, 'services': self.half}, population_field='population', target_per_person=1)
        self.assertTrue(supply.supply_per_person.isna().all())

    def test_nearest_and_hazard(self):
        result = self.run_op('nearest_service', {'subjects': self.origins, 'services': frame([Point(10, 0), Point(20, 0)])})
        self.assertEqual(result.distance_m.iloc[0], 10)
        self.assertEqual(result.nearest_service_row.iloc[0], 0)
        result = self.run_op('hazard_exposure', {'subjects': self.zones, 'hazards': self.half})
        self.assertEqual(result.exposed_pct.iloc[0], 50)

    def test_suitability_and_green_priority(self):
        data = frame([Point(0, 0), Point(1, 0)], heat=[10, 20], canopy=[80, 20])
        for op in ('urban_suitability', 'green_priority'):
            result = self.run_op(op, {'candidates': data}, weights={'heat': .5, 'canopy': -.5})
            self.assertEqual(list(result.suitability_score), [0, 100])
            self.assertEqual(list(result.priority_rank), [2, 1])
        with self.assertRaises(ValueError):
            self.run_op('urban_suitability', {'candidates': data}, weights={'heat': 0})

    def test_allocation_respects_capacity_and_demand(self):
        demand = frame([Point(0, 0), Point(100, 0)], pop=[100, 80])
        sites = frame([Point(0, 0), Point(100, 0)], capacity=[50, 60])
        result = self.run_op('location_allocation', {'demand': demand, 'candidates': sites}, demand_field='pop', capacity_field='capacity', radius_m=10, facility_count=2)
        self.assertEqual(list(result.allocated_demand), [50, 60])
        self.assertEqual(result.remaining_demand_total.iloc[0], 70)
        self.assertEqual(list(result.selection_order), [2, 1])

    def test_compatibility_and_rules(self):
        uses = frame([box(0, 0, 10, 10), box(10, 0, 20, 10)], use=['residential', 'industrial'], height=[10, 15])
        result = self.run_op('landuse_compatibility', {'landuse': uses}, class_field='use', incompatible_pairs=[['residential', 'industrial']], distance_m=0)
        self.assertEqual(list(result.conflict_count), [1, 1])
        result = self.run_op('zoning_check', {'parcels': uses}, rules={'height': {'max': 12}})
        self.assertEqual(list(result.compliant), [True, False])
        self.assertEqual(json.loads(result.violation_fields.iloc[1]), ['height'])

    def test_development_and_mix(self):
        parcels = self.zones.copy(); parcels['existing'] = 20
        result = self.run_op('development_capacity', {'parcels': parcels}, existing_floor_field='existing', allowed_far=2, floor_m2_per_unit=60)
        self.assertEqual(result.additional_floor_m2.iloc[0], 180)
        self.assertEqual(result.estimated_additional_units.iloc[0], 3)
        uses = frame([box(0, 0, 5, 10), box(5, 0, 10, 10)], use=['A', 'B'])
        result = self.run_op('landuse_mix', {'zones': self.zones, 'landuse': uses}, class_field='use')
        self.assertAlmostEqual(result.landuse_mix_index.iloc[0], 1)
        self.assertEqual(result.mapped_area_pct.iloc[0], 100)
        with self.assertRaises(ValueError):
            self.run_op('landuse_mix', {'zones': self.zones, 'landuse': frame([box(0, 0, 10, 10)]*2, use=['A', 'B'])}, class_field='use')

    def test_walking_partial_edges_and_disconnected_network(self):
        result = self.run_op('walking_access', {'roads': self.roads, 'origins': self.origins}, minutes=.5, walking_kmh=6, snap_m=1)
        self.assertAlmostEqual(result.length.sum(), 50)
        self.assertEqual(list(result.source_road_row), [0])
        result = self.run_op('network_connectivity', {'roads': self.roads})
        self.assertEqual(result.component_id.nunique(), 2)
        self.assertTrue(result.dead_end.all())
        with self.assertRaises(ValueError):
            self.run_op('walking_access', {'roads': self.roads, 'origins': frame([Point(50, 0)])}, minutes=1, snap_m=1)

    def test_changes_and_scenarios(self):
        before = frame([box(0, 0, 10, 10)], use=['A'], key=[1], population=['10'])
        after = frame([box(0, 0, 10, 10)], use=['B'], key=[1], population=['15'])
        result = self.run_op('urban_change', {'before': before, 'after': after}, class_field='use')
        self.assertEqual(result.area_m2.sum(), 100)
        self.assertTrue(result.changed.all())
        result = self.run_op('scenario_comparison', {'before': before, 'after': after}, id_field='key', metrics=['population'])
        self.assertEqual(result.population_delta.iloc[0], 5)
        after['key'] = 2
        result = self.run_op('scenario_comparison', {'before': before, 'after': after}, id_field='key', metrics=['population'])
        self.assertEqual(set(result.scenario_status), {'added', 'removed'})
        self.assertTrue(result.population_delta.isna().all())

    def test_missing_data_and_crs_are_not_guessed(self):
        with self.assertRaises(ValueError):
            self.run_op('parcel_profile', {'parcels': self.zones.set_crs(None, allow_override=True)})
        with self.assertRaises(ValueError):
            self.run_op('coverage_far', {'parcels': self.zones, 'buildings': self.buildings}, floors_field='missing')
        invalid = self.zones.copy(); invalid['population'] = float('nan')
        with self.assertRaises(ValueError):
            self.run_op('population_coverage', {'zones': invalid, 'coverage': self.half}, population_field='population')

    def test_geometry_errors_have_localized_diagnostics(self):
        from src.agent.validation import GISValidationError
        cases = [
            (self.zones, 'road_geometry'),
            (self.roads.set_crs(None, allow_override=True), 'missing_crs'),
            (frame([LineString([(0, 0), (0, 0)])]), 'invalid_geometry'),
            (self.roads.iloc[:0], 'empty_layer'),
        ]
        for roads, code in cases:
            with self.subTest(code=code), self.assertRaises(GISValidationError) as caught:
                self.run_op('network_connectivity', {'roads': roads})
            self.assertEqual(caught.exception.detail['code'], code)
            self.assertEqual(caught.exception.detail['role'], 'roads')
            self.assertTrue(caught.exception.detail['fa'])

    def test_agent_toolkit_executes_registered_urban_tool(self):
        from src.agent.sandbox import PythonSandbox
        from src.agent.tools import GISToolkit
        with tempfile.TemporaryDirectory() as folder:
            sandbox = PythonSandbox(work_dir=folder, timeout=60)
            sandbox.namespace['parcels'] = self.zones
            toolkit = GISToolkit(sandbox)
            self.assertIn('urban_analysis', toolkit.tool_descriptions)
            observation = toolkit.geoprocess('parcel_profile', inputs={'parcels': 'parcels'}, output='urban_result')
            self.assertNotIn('❌', observation, observation)
            self.assertTrue(os.path.isfile(os.path.join(folder, 'pred_results/urban_result.geojson')))

    def integration_cases(self):
        parcels = self.zones.assign(existing=20, height=15, key=1)
        uses = frame([box(0, 0, 5, 10), box(5, 0, 10, 10)], use=['A', 'B'])
        candidates = frame([Point(0, 0), Point(100, 0)], heat=[10, 20], canopy=[80, 20], capacity=[50, 60])
        return {
            'parcel_profile': ({'parcels': parcels}, {}),
            'urban_density': ({'zones': parcels, 'buildings': self.buildings}, {'population_field': 'population'}),
            'coverage_far': ({'parcels': parcels, 'buildings': self.buildings}, {'floors_field': 'floors'}),
            'service_provision': ({'zones': parcels, 'services': self.half}, {'population_field': 'population', 'target_per_person': 1}),
            'nearest_service': ({'subjects': self.origins, 'services': candidates}, {}),
            'walking_access': ({'roads': self.roads, 'origins': self.origins}, {'minutes': .5, 'walking_kmh': 6, 'snap_m': 1}),
            'population_coverage': ({'zones': parcels, 'coverage': self.half}, {'population_field': 'population'}),
            'urban_suitability': ({'candidates': candidates}, {'weights': {'heat': .5, 'canopy': -.5}}),
            'location_allocation': ({'demand': candidates.assign(pop=100), 'candidates': candidates}, {'demand_field': 'pop', 'capacity_field': 'capacity', 'radius_m': 10}),
            'landuse_compatibility': ({'landuse': uses}, {'class_field': 'use', 'incompatible_pairs': [['A', 'B']]}),
            'zoning_check': ({'parcels': parcels}, {'rules': {'height': {'max': 12}}}),
            'development_capacity': ({'parcels': parcels}, {'existing_floor_field': 'existing', 'allowed_far': 2}),
            'landuse_mix': ({'zones': parcels, 'landuse': uses}, {'class_field': 'use'}),
            'network_connectivity': ({'roads': self.roads}, {}),
            'hazard_exposure': ({'subjects': parcels, 'hazards': self.half}, {}),
            'green_priority': ({'candidates': candidates}, {'weights': {'heat': .5, 'canopy': -.5}}),
            'urban_change': ({'before': uses, 'after': uses.assign(use=['B', 'B'])}, {'class_field': 'use'}),
            'scenario_comparison': ({'before': parcels, 'after': parcels.assign(population=120)}, {'id_field': 'key', 'metrics': ['population']}),
        }

    def test_every_urban_tool_through_model_action_and_file_outputs(self):
        from src.agent.sandbox import PythonSandbox
        from src.agent.tools import GISToolkit
        from src.agent.react_agent import _parse_action
        cases = self.integration_cases()
        self.assertEqual(set(cases), set(DEFINITIONS), 'New tools require an integration fixture')
        for op, (layers, params) in cases.items():
            with self.subTest(op=op), tempfile.TemporaryDirectory() as folder:
                sandbox = PythonSandbox(work_dir=folder, timeout=60)
                toolkit = GISToolkit(sandbox)
                for role, data in layers.items():
                    path = os.path.join(folder, role + '.gpkg')
                    data.to_file(path, driver='GPKG')
                    observation = toolkit.load_vector(path, role)
                    self.assertNotIn('❌', observation, observation)
                args = dict(op=op, inputs={role: role for role in layers}, params=params, output='result')
                _, action, parsed = _parse_action('Thought: تحلیل داده\nAction: geoprocess\nArgs: ' + json.dumps(args))
                self.assertEqual(action, 'geoprocess')
                observation = toolkit.geoprocess(**parsed)
                self.assertNotIn('❌', observation, observation)
                self.assertNotIn('Traceback', observation, observation)
                result_path = os.path.join(folder, 'pred_results/result.geojson')
                saved = gpd.read_file(result_path)
                self.assertFalse(saved.empty)
                self.assertTrue(saved.geometry.is_valid.all())
                self.assertEqual(saved.crs.to_epsg(), 4326)
                with open(os.path.join(folder, 'pred_results/result.method.json')) as f:
                    report = json.load(f)
                self.assertEqual(report['operation'], op)
                self.assertEqual(report['input_counts'], {r: len(d) for r, d in layers.items()})
                expected = urban_ops.run(op, layers, params)
                from geopandas.testing import assert_geodataframe_equal
                # File drivers move geometry after attributes; column order is not data.
                assert_geodataframe_equal(sandbox.namespace['result'], expected, check_like=True)

    def test_model_request_errors_are_recoverable(self):
        from src.agent.sandbox import PythonSandbox
        from src.agent.tools import GISToolkit
        with tempfile.TemporaryDirectory() as folder:
            sandbox = PythonSandbox(work_dir=folder, timeout=60)
            sandbox.namespace['parcels'] = self.zones
            toolkit = GISToolkit(sandbox)
            for overrides in ({'inputs': {}}, {'inputs': {'parcels': 'bad-name'}},
                              {'output': 'class'}, {'output': 42}, {'params': []},
                              {'inputs': []}, {'params': {'typo': 1}},
                              {'inputs': {'parcels': 'not_loaded'}}):
                with self.subTest(overrides=overrides):
                    args = dict(op='parcel_profile', inputs={'parcels': 'parcels'}, output='result')
                    args.update(overrides)
                    self.assertIn('❌', toolkit.geoprocess(**args))
            self.assertNotIn('❌', toolkit.geoprocess('parcel_profile', {'parcels': 'parcels'}, output='recovered'))

    def test_full_agent_loop_for_every_urban_operation(self):
        from src.agent.react_agent import GISReActAgent

        class ScriptedModel:
            def __init__(self, actions):
                self.actions = iter(actions)
                self.prompts = []

            def generate(self, **kwargs):
                self.prompts.append(kwargs)
                action, args = next(self.actions)
                return {'text': 'Thought: تحلیل شهری\nAction: ' + action + '\nArgs: ' + json.dumps(args)}

        for op, (layers, params) in self.integration_cases().items():
            with self.subTest(op=op), tempfile.TemporaryDirectory() as folder:
                data_dir = os.path.join(folder, 'input')
                os.mkdir(data_dir)
                actions = []
                for role, data in layers.items():
                    data.to_file(os.path.join(data_dir, role + '.gpkg'), driver='GPKG')
                    actions.append(('load_vector', {'path': 'dataset/' + role + '.gpkg', 'var_name': role}))
                actions.append(('geoprocess', dict(op=op, inputs={r: r for r in layers}, params=params, output='result')))
                actions.append(('finish', {'summary': 'تحلیل انجام شد.'}))
                model = ScriptedModel(actions)
                agent = GISReActAgent(model, verbose=False, max_rounds=len(actions))
                result = agent.run('تحلیل شهری با ' + op, data_dir, os.path.join(folder, 'work'))
                self.assertTrue(result.success, result.history)
                self.assertEqual(result.total_rounds, len(actions))
                self.assertTrue(any('result.geojson' in p for p in result.output_files), result.output_files)
                self.assertIn(op, model.prompts[0]['system_prompt'])
                self.assertIn('working_crs', model.prompts[-1]['user_message'])

    def test_metric_crs_and_mixed_input_crs(self):
        from shapely.affinity import translate
        local = frame([translate(box(0, 0, 100, 100), xoff=500000, yoff=3950000)])
        for crs in (4326, 3857):
            result = self.run_op('parcel_profile', {'parcels': local.to_crs(crs)})
            self.assertAlmostEqual(result.area_m2.iloc[0], 10000, places=3)
        result = self.run_op('hazard_exposure', {'subjects': local.to_crs(4326), 'hazards': local})
        self.assertAlmostEqual(result.exposed_pct.iloc[0], 100, places=5)

    def test_catalog_agent_and_generated_execution(self):
        group = next(g for g in geo_ops.catalog() if g['category'] == 'urban_analysis')
        self.assertEqual(group['title'], 'Urban analysis')
        self.assertEqual(len(group['ops']), 18)
        for op, spec in DEFINITIONS.items():
            self.assertIn(op, geo_ops.describe_ops())
            code = geo_ops.build_code(op, {r: r for r in spec['inputs']}, {}, 'result')
            compile(code, '<urban-tool>', 'exec')
        with tempfile.TemporaryDirectory() as folder:
            old = os.getcwd()
            try:
                os.chdir(folder)
                namespace = {'parcels': self.zones}
                exec(geo_ops.build_code('parcel_profile', {'parcels': 'parcels'}, {}, 'result'), namespace)
                self.assertTrue(os.path.isfile('pred_results/result.geojson'))
                with open('pred_results/result.method.json') as f:
                    report = json.load(f)
                self.assertEqual(report['operation'], 'parcel_profile')
                self.assertEqual(report['input_counts']['parcels'], 1)
                self.assertEqual(gpd.read_file('pred_results/result.geojson').crs.to_epsg(), 4326)
            finally:
                os.chdir(old)


if __name__ == '__main__':
    unittest.main()
