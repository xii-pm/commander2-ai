"""Configuration contract: strict validation, no silently ignored keys."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import std_config  # noqa: E402


class DefaultsTest(unittest.TestCase):
    def test_defaults_are_complete(self):
        self.assertGreaterEqual(len(std_config.DEFAULTS), 200)
        for key, value in std_config.DEFAULTS.items():
            self.assertIsInstance(key, str)
            self.assertTrue(key.islower() or '_' in key)
            self.assertIn(type(value), (bool, int))

    def test_empty_override_returns_defaults(self):
        self.assertEqual(std_config.validate({}), dict(std_config.DEFAULTS))

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError):
            std_config.validate({'no_such_setting': True})

    def test_wrong_type_is_rejected(self):
        with self.assertRaises(ValueError):
            std_config.validate({'every_step': 1})
        with self.assertRaises(ValueError):
            std_config.validate({'hint_weight': True})

    def test_unbounded_integer_is_rejected(self):
        with self.assertRaises(ValueError):
            std_config.validate({'hint_weight': 99999})
        with self.assertRaises(ValueError):
            std_config.validate({'hint_weight': -1})

    def test_dependent_switches_are_enforced(self):
        # Repair interception relief is meaningless without the repair pass.
        with self.assertRaises(ValueError):
            std_config.validate({'repair_preserve_interception': True})
        # The unified frontier needs the continuous arbiter behind it.
        with self.assertRaises(ValueError):
            std_config.validate({'unified_frontier': True})

    def test_override_is_applied(self):
        result = std_config.validate({'hint_weight': 40})
        self.assertEqual(result['hint_weight'], 40)
        self.assertEqual(result['approach_weight'], std_config.DEFAULTS['approach_weight'])


class ProductionConfigTest(unittest.TestCase):
    def setUp(self):
        self.params = json.loads((ROOT / 'parameters.json').read_text(encoding='utf-8'))

    def test_production_config_validates(self):
        validated = std_config.validate(self.params)
        self.assertEqual(len(validated), len(std_config.DEFAULTS))

    def test_production_config_only_uses_known_keys(self):
        self.assertFalse(set(self.params) - set(std_config.DEFAULTS))

    def test_load_reads_parameters_json(self):
        loaded = std_config.load()
        self.assertEqual(loaded['every_step'], bool(self.params.get('every_step', False)))
        self.assertEqual(loaded['hint_weight'], self.params['hint_weight'])


if __name__ == '__main__':
    unittest.main()
