#!/usr/bin/env python3
"""
StudyMate Single-Click Launcher
Runs FastAPI server and opens browser automatically
Works on Windows, Mac, and Linux
"""
import os
import runpy
import sys
import threading
import time
import webbrowser
import subprocess
from pathlib import Path

# Fix Windows encoding issues
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'

def check_port_in_use():
    """Check if port 8000 is already in use."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8000))
    sock.close()
    return result == 0

def get_project_root():
    """Find the project root directory."""
    return Path(__file__).parent.absolute()


LOCK_FILE_NAME = ".studymate.launcher.lock"


def get_lock_path() -> Path:
    return get_project_root() / LOCK_FILE_NAME


def acquire_single_instance_lock() -> bool:
    """Prevent multiple launcher windows from starting duplicate app instances."""
    lock_path = get_lock_path()
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None

        if pid is not None and pid != os.getpid():
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError, OSError):
                lock_path.unlink(missing_ok=True)
            else:
                print("[INFO] StudyMate is already running in another window")
                return False

        if lock_path.exists():
            lock_path.unlink(missing_ok=True)

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        print("[INFO] StudyMate is already running in another window")
        return False
    except OSError as exc:
        print(f"[WARNING] Could not create launcher lock file: {exc}")
        return False
    return True


def release_single_instance_lock() -> None:
    try:
        get_lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def setup_environment():
    """Set up Python path and environment."""
    root = get_project_root()
    sys.path.insert(0, str(root))
    os.chdir(root)
    
    # Create .env if it doesn't exist
    env_file = root / ".env"
    env_example = root / ".env.example"
    
    if not env_file.exists() and env_example.exists():
        print("[*] Creating .env from .env.example...")
        env_content = env_example.read_text()
        env_file.write_text(env_content)
        print("[WARNING] Please edit .env and add ANTHROPIC_API_KEY if needed")

def get_database_path():
    """Resolve the database file path from the app settings."""
    from app.config import get_settings

    settings = get_settings()
    database_url = settings.database_url
    if not database_url.startswith("sqlite"):
        return None

    path_part = database_url.removeprefix("sqlite:///")
    if not path_part or path_part == ":memory:":
        return None

    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = (Path.cwd() / db_path).resolve()
    return db_path


class ServerHandle:
    """Small compatibility wrapper for local/dev and packaged server modes."""

    def __init__(self, process=None, server=None, thread=None):
        self.process = process
        self.server = server
        self.thread = thread

    def communicate(self, timeout=None):
        if self.process is None:
            return b"", b""
        return self.process.communicate(timeout=timeout)

    def terminate(self):
        if self.process is not None:
            self.process.terminate()
        elif self.server is not None:
            self.server.should_exit = True

    def wait(self, timeout=None):
        if self.process is not None:
            self.process.wait(timeout=timeout)
        elif self.thread is not None:
            self.thread.join(timeout=timeout)

    def kill(self):
        if self.process is not None:
            self.process.kill()
        elif self.server is not None:
            self.server.should_exit = True


def init_database():
    """Initialize database if needed."""
    root = get_project_root()
    db_file = get_database_path()

    if db_file and db_file.exists():
        return

    print("[*] Initializing database...")
    try:
        if getattr(sys, "frozen", False):
            runpy.run_module("app.seed", run_name="__main__")
            print("[OK] Database initialized")
        else:
            result = subprocess.run(
                [sys.executable, "-m", "app.seed"],
                cwd=root,
                capture_output=True,
                timeout=30,
                text=True
            )
            if result.returncode == 0:
                print("[OK] Database initialized")
            else:
                print(f"[WARNING] Database init returned code {result.returncode}")
                if result.stderr:
                    print(f"[WARNING] {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("[WARNING] Database init timed out (non-fatal)")
    except Exception as e:
        print(f"[WARNING] Database init error (non-fatal): {e}")


def run_server() -> ServerHandle:
    """Start the FastAPI server without recursively spawning the packaged exe."""
    root = get_project_root()

    try:
        print("[*] Starting StudyMate server...")

        if getattr(sys, "frozen", False):
            from uvicorn import Config, Server

            config = Config("app.main:app", host="127.0.0.1", port=8000, log_level="info")
            server = Server(config)

            def _run_uvicorn() -> None:
                server.run()

            thread = threading.Thread(target=_run_uvicorn, daemon=True)
            thread.start()
            return ServerHandle(server=server, thread=thread)

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000"
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
        )

        return ServerHandle(process=process)
    except Exception as e:
        print(f"[ERROR] Failed to start server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def wait_for_server(max_attempts=30):
    """Wait for server to be ready."""
    import socket
    
    for attempt in range(max_attempts):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', 8000))
            sock.close()
            
            if result == 0:
                print("[OK] Server is ready")
                return True
        except:
            pass
        
        if attempt == 0:
            print("[...] Waiting for server to start...", end="", flush=True)
        else:
            print(".", end="", flush=True)
        
        time.sleep(0.5)
    
    print("\n[ERROR] Server failed to start")
    return False

def open_browser():
    """Open browser to the app."""
    url = "http://127.0.0.1:8000"
    print(f"\n[INFO] Opening {url}...")
    print("[INFO] Please open the URL manually if the browser doesn't start")
    
    # Only try to open browser once with a short timeout
    try:
        import threading
        def open_in_thread():
            try:
                webbrowser.open(url, new=0, autoraise=False)
            except Exception:
                pass
        
        thread = threading.Thread(target=open_in_thread, daemon=True)
        thread.start()
        thread.join(timeout=2)  # Wait max 2 seconds
    except Exception as e:
        print(f"[WARNING] Could not auto-open browser: {e}")


def is_running_under_test() -> bool:
    """Return True when the launcher is being exercised by a test runner."""
    if os.getenv("STUDYMATE_TEST_MODE", "").lower() in {"1", "true", "yes", "on"}:
        return True

    if os.getenv("PYTEST_CURRENT_TEST"):
        return True

    return "pytest" in sys.modules or "unittest" in sys.modules


def main():
    """Main entry point."""
    print("=" * 50)
    print("  StudyMate - Single Click Launcher")
    print("=" * 50 + "\n")

    if check_port_in_use():
        print("[INFO] StudyMate is already running on http://127.0.0.1:8000")
        print("[INFO] Opening in browser...\n")
        open_browser()
        return

    if not acquire_single_instance_lock():
        print("[INFO] Exiting because another launcher instance is already active")
        return

    try:
        setup_environment()
        init_database()

        server = run_server()

        if not wait_for_server():
            print("\n[ERROR] Server failed to start. Checking logs...")
            try:
                _, stderr = server.communicate(timeout=2)
                if stderr:
                    print("[STDERR]:", stderr.decode('utf-8', errors='replace')[:500])
            except:
                pass
            try:
                server.terminate()
            except:
                pass
            sys.exit(1)

        open_browser()

        print("\n[OK] StudyMate is running!")
        if is_running_under_test():
            print("[INFO] Test mode detected; stopping launcher after startup check")
            try:
                server.terminate()
                server.wait(timeout=3)
            except Exception:
                pass
            return

        print("     Press Ctrl+C to stop the server\n")

        try:
            server.wait()
        except KeyboardInterrupt:
            print("\n\n[*] Stopping server...")
            try:
                server.terminate()
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    server.kill()
                except:
                    pass
            except Exception as e:
                print(f"[WARNING] Error stopping server: {e}")
            print("[OK] Server stopped")
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
            try:
                server.terminate()
            except:
                pass
            sys.exit(1)
    finally:
        release_single_instance_lock()

if __name__ == "__main__":
    main()
