import unittest
from unittest.mock import MagicMock, patch

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

    @patch("launcher.release_single_instance_lock")
    @patch("launcher.open_browser")
    @patch("launcher.wait_for_server", return_value=True)
    @patch("launcher.init_database")
    @patch("launcher.setup_environment")
    @patch("launcher.acquire_single_instance_lock", return_value=True)
    @patch("launcher.check_port_in_use", return_value=False)
    def test_main_stops_cleanly_when_running_under_test(
        self,
        check_port_in_use,
        acquire_single_instance_lock,
        setup_environment,
        init_database,
        wait_for_server,
        open_browser,
        release_single_instance_lock,
    ):
        server = MagicMock()

        with patch("launcher.run_server", return_value=server), patch("launcher.is_running_under_test", return_value=True):
            launcher.main()

        server.terminate.assert_called_once()
        server.wait.assert_called_once_with(timeout=3)


if __name__ == "__main__":
    unittest.main()
