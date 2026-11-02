import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks'))
from coverage import evaluate

class CoverageBenchmarkTests(unittest.TestCase):
    def test_offline_multilingual_fixture_matrix(self):
        path = Path(__file__).resolve().parents[1] / 'benchmarks' / 'coverage_cases.json'
        report = evaluate(json.loads(path.read_text(encoding='utf-8')))
        self.assertEqual(report['total'], 8)
        self.assertEqual(report['counts']['shipping'], 6)
        self.assertEqual(report['counts']['delivery'], 6)
        self.assertEqual(report['counts']['price'], 6)
        self.assertEqual(report['counts']['product'], 7)
        self.assertTrue(report['dataset'].startswith('SYNTHETIC_'))
