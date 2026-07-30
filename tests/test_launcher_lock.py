import os
import tempfile
import unittest
from unittest import mock

import launcher


class LauncherLockTests(unittest.TestCase):
    def setUp(self):
        launcher.release_single_instance_lock()

    def tearDown(self):
        launcher.release_single_instance_lock()

    def test_acquire_lock_creates_lock_file(self):
        self.assertTrue(launcher.acquire_single_instance_lock())
        self.assertTrue(launcher.get_lock_path().exists())

    def test_acquire_lock_replaces_stale_lock(self):
        launcher.get_lock_path().write_text("999999999", encoding="utf-8")
        self.assertTrue(launcher.acquire_single_instance_lock())
        self.assertEqual(launcher.get_lock_path().read_text(encoding="utf-8").strip(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
