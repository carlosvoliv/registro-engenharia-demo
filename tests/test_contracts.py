import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_versioned_configuration_is_parseable(self):
        files = sorted((ROOT / "config").rglob("*.yml"))
        self.assertEqual(len(files), 4)
        for path in files:
            with self.subTest(path=path.name):
                self.assertIsInstance(yaml.safe_load(path.read_text()), dict)


if __name__ == "__main__":
    unittest.main()
