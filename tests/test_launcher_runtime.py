import unittest
from unittest.mock import patch

import launcher


class LauncherRuntimeTests(unittest.TestCase):
    @patch("launcher.subprocess.run")
    @patch("launcher.runpy.run_module")
    def test_init_database_uses_runpy_when_frozen(self, run_module, subprocess_run):
        with patch.object(launcher.sys, "frozen", True, create=True):
            with patch("launcher.get_database_path", return_value=launcher.Path("missing.db")):
                launcher.init_database()

        subprocess_run.assert_not_called()
        run_module.assert_called_once_with("app.seed", run_name="__main__")

    @patch("launcher.subprocess.Popen")
    def test_run_server_avoids_subprocess_when_frozen(self, popen_mock):
        with patch.object(launcher.sys, "frozen", True, create=True):
            with patch("launcher.threading.Thread") as thread_mock:
                thread_mock.return_value.start.return_value = None
                launcher.run_server()

        popen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
