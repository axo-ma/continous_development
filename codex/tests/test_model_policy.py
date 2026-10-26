"""Synthetic settings; no user configuration or journals."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('mac_policy', Path(__file__).parents[1] / 'skills/mac/scripts/mac_settings.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ModelPolicyTests(unittest.TestCase):
    def setUp(self):
        self.allowed = ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-luna']
        self.data = {'schema_version': 1, 'mode': 'auto',
                     'model_policy': {'allowed_models': self.allowed},
                     'models': {'helper': {'model': 'gpt-6-luna'}}}

    def test_exact_allowlist_denies_legacy_terra_aliases_and_missing(self):
        for model in ['gpt-6-sol', 'gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-6.1-terra',
                      'gpt-6-luna-latest', 'Luna', '', None]:
            with self.subTest(model=model), self.assertRaises(ValueError):
                policy.authorize(self.data, model)
        for model in self.allowed:
            self.assertTrue(policy.authorize(self.data, model)['authorized'])

    def test_off_missing_policy_and_role_mismatch_fail_closed(self):
        with self.assertRaises(ValueError):
            policy.authorize({'mode': 'auto'}, 'gpt-6-luna')
        with self.assertRaises(ValueError):
            policy.authorize(self.data, 'gpt-6.1-sol', 'helper')
        self.assertTrue(policy.authorize(self.data, 'gpt-6-luna', 'helper')['authorized'])
        self.data['mode'] = 'off'
        with self.assertRaises(ValueError):
            policy.authorize(self.data, 'gpt-6-luna')

    def test_bad_role_configuration_and_enabled_pilot_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for mutate in ('role', 'pilot', 'policy'):
                data = json.loads(json.dumps(self.data))
                if mutate == 'role':
                    data['models']['helper']['model'] = 'gpt-5.6-luna'
                elif mutate == 'pilot':
                    data['local_pilot'] = {'enabled': True, 'model': 'gpt-6.1-terra'}
                else:
                    data['model_policy']['allowed_models'] = []
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    policy.load(folder)

