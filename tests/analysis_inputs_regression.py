"""Snapshot scope, bounded reads and path safety; no model/network requests."""
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import isolated_analysis as analysis


class InputSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'outputs').mkdir()

    def put(self, name, content):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def selected(self, path):
        return [{'where': 'outputs', 'path': path, 'ids': [0]}]

    def test_large_unselected_outputs_do_not_count_or_get_read(self):
        self.put('data/land.shp', b'source')
        old = self.put('outputs/large.geojson', b'')
        with old.open('r+b') as stream:
            stream.truncate(55 * 1024 * 1024)
        result = analysis.snapshot_inputs(self.root, [])
        self.assertEqual(set(result), {'data/land.shp'})
        self.assertEqual(base64.b64decode(result['data/land.shp']), b'source')
        self.assertEqual(old.stat().st_size, 55 * 1024 * 1024)

    def test_selected_outputs_include_all_shapefile_companions_and_deduplicate(self):
        for name in ('road.shp', 'road.dbf', 'road.shx', 'road.prj', 'road.cpg'):
            self.put('outputs/previous/' + name, b'member')
        self.put('data/context.geojson', b'context')
        self.put('outputs/unused.txt', b'unrelated')
        selected = self.selected('previous/road.shp') * 2
        result = analysis.snapshot_inputs(self.root, selected)
        self.assertEqual(len(result), 6)
        self.assertNotIn('outputs/unused.txt', result)
        self.assertIn('outputs/previous/road.dbf', result)

    def test_genuine_input_overflow_still_returns_actionable_413(self):
        self.put('data/context.geojson', b'x' * 8)
        self.put('outputs/selected.geojson', b'y' * 8)
        with patch.object(analysis, 'MAX_BYTES', 10):
            with self.assertRaises(analysis.AnalysisError) as error:
                analysis.snapshot_inputs(self.root, self.selected('selected.geojson'))
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(error.exception.code, 'analysis_input_too_large')
        self.assertIn('توکن نیست', str(error.exception))
        with patch.object(analysis, 'MAX_BYTES', 8):
            self.assertEqual(len(analysis.snapshot_inputs(self.root, [])), 1)

    def test_oversized_selected_output_cannot_be_silently_omitted(self):
        self.put('outputs/selected.geojson', b'x' * 11)
        with patch.object(analysis, 'MAX_BYTES', 10), self.assertRaises(analysis.AnalysisError):
            analysis.snapshot_inputs(self.root, self.selected('selected.geojson'))

    def test_symlink_inputs_and_output_target_are_rejected(self):
        self.put('data/source.txt', b'x')
        link = self.root / 'data/link.txt'
        link.symlink_to(self.root / 'data/source.txt')
        with self.assertRaises(analysis.AnalysisError):
            analysis.snapshot_inputs(self.root, [])
        link.unlink()
        (self.root / 'outputs').rmdir()
        (self.root / 'outputs').symlink_to(self.root / 'data', target_is_directory=True)
        with self.assertRaises(analysis.AnalysisError):
            analysis.snapshot_inputs(self.root, [])

    def test_selected_output_rejects_traversal_and_symlink_parent(self):
        self.put('data/private.geojson', b'data')
        (self.root / 'outputs/link').symlink_to(self.root / 'data', target_is_directory=True)
        for name in ('../data/private.geojson', 'link/private.geojson'):
            with self.subTest(name=name), self.assertRaises(analysis.AnalysisError):
                analysis.snapshot_inputs(self.root, self.selected(name))


if __name__ == '__main__':
    unittest.main()
