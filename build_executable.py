#!/usr/bin/env python3
"""
Build standalone executables for Windows and Mac using PyInstaller
Run: python build_executable.py

NOTE: PyInstaller support:
- Python 3.8-3.12: Works with PyInstaller 6.x
- Python 3.13+: Currently not supported by PyInstaller (wait for PyInstaller 7.x)
"""
import subprocess
import sys
from pathlib import Path

def check_python_version():
    """Check if current Python version is compatible with PyInstaller."""
    version_info = sys.version_info
    if version_info.major == 3 and version_info.minor >= 13:
        print("❌ Python 3.13+ is not yet supported by PyInstaller")
        print("\nOptions:")
        print("  1. Downgrade to Python 3.12: https://www.python.org")
        print("  2. Wait for PyInstaller 7.x support")
        print("  3. Use the .bat launcher instead (doesn't require PyInstaller)")
        print("\nFor now, you can use StudyMate.bat - it works great without executable build!")
        return False
    return True

def check_pyinstaller():
    """Check if PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"✓ PyInstaller version {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        return True

def build():
    """Build the executable."""
    root = Path(__file__).parent
    
    print("\n" + "=" * 50)
    print("  Building StudyMate Executable")
    print("=" * 50 + "\n")
    
    if not check_python_version():
        sys.exit(1)
    
    if not check_pyinstaller():
        sys.exit(1)
    
    # Determine OS
    import platform
    system = platform.system()
    
    if system == "Windows":
        build_windows(root)
    elif system == "Darwin":
        build_macos(root)
    else:
        build_linux(root)

def build_windows(root):
    """Build Windows executable."""
    print("🔨 Building Windows executable...")
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name=StudyMate",
        "--icon=app/templates/favicon.ico" if (root / "app" / "templates" / "favicon.ico").exists() else None,
        "--hidden-import=app",
        "--hidden-import=app.main",
        "--hidden-import=app.db",
        "--hidden-import=app.models",
        "--hidden-import=app.config",
        "--hidden-import=sqlalchemy",
        "--hidden-import=uvicorn",
        "--hidden-import=fastapi",
        "--collect-all=app",
        "--add-data=app/templates:app/templates",
        "--add-data=.env.example:.",
        str(root / "launcher.py"),
    ]
    
    cmd = [c for c in cmd if c]  # Remove None values
    
    subprocess.run(cmd, cwd=root, check=True)
    print("✓ Windows executable created: dist/StudyMate.exe")

def build_macos(root):
    """Build macOS app."""
    print("🔨 Building macOS app...")
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name=StudyMate",
        "--hidden-import=app",
        "--hidden-import=app.main",
        "--hidden-import=app.db",
        "--hidden-import=app.models",
        "--hidden-import=app.config",
        "--hidden-import=sqlalchemy",
        "--hidden-import=uvicorn",
        "--hidden-import=fastapi",
        "--collect-all=app",
        "--add-data=app/templates:app/templates",
        "--add-data=.env.example:.",
        str(root / "launcher.py"),
    ]
    
    subprocess.run(cmd, cwd=root, check=True)
    print("✓ macOS app created: dist/StudyMate.app")

def build_linux(root):
    """Build Linux executable."""
    print("🔨 Building Linux executable...")
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name=StudyMate",
        "--hidden-import=app",
        "--hidden-import=app.main",
        "--hidden-import=app.db",
        "--hidden-import=app.models",
        "--hidden-import=app.config",
        "--hidden-import=sqlalchemy",
        "--hidden-import=uvicorn",
        "--hidden-import=fastapi",
        "--collect-all=app",
        "--add-data=app/templates:app/templates",
        "--add-data=.env.example:.",
        str(root / "launcher.py"),
    ]
    
    subprocess.run(cmd, cwd=root, check=True)
    print("✓ Linux executable created: dist/StudyMate")

if __name__ == "__main__":
    build()
    print("\n" + "=" * 50)
    print("✓ Build complete!")
    print("=" * 50)
