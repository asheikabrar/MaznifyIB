import os
import unittest
from unittest.mock import patch

from app import config


class DatabaseConfigTests(unittest.TestCase):
    def setUp(self):
        config.get_settings.cache_clear()

    def tearDown(self):
        config.get_settings.cache_clear()

    def test_uses_explicit_database_url_from_environment(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:////tmp/custom.db"}, clear=True):
            settings = config.get_settings()
            self.assertEqual(settings.database_url, "sqlite:////tmp/custom.db")

    def test_defaults_to_data_folder_db_path(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = config.get_settings()
            self.assertTrue(settings.database_url.endswith("data/studymate.db"))


if __name__ == "__main__":
    unittest.main()
