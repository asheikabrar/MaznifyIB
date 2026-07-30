# Single-Click App Implementation Summary

## What's New

You now have **three ways** to run StudyMate:

### 1. **Single-Click (Recommended)**
- **Windows**: Double-click `StudyMate.bat`
- **Mac**: Double-click `StudyMate.sh`
- Auto-installs dependencies, initializes database, opens browser
- Works locally or from Google Drive

### 2. **Standalone Executable (No Python Required)**
```bash
python build_executable.py
```
Creates:
- `dist/StudyMate.exe` (Windows)
- `dist/StudyMate.app` (Mac)

### 3. **Manual Setup (Original Method)**
```bash
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```

---

## Files Created

| File | Purpose |
|------|---------|
| `launcher.py` | Core launcher logic (Python) |
| `StudyMate.bat` | Windows one-click launcher |
| `StudyMate.sh` | Mac/Linux one-click launcher |
| `build_executable.py` | Build standalone executables |
| `QUICK_START.md` | Quick reference guide |
| `LAUNCHER_SETUP.md` | Detailed setup documentation |
| `requirements.txt` | Updated with PyInstaller |

---

## How It Works

### When you click `StudyMate.bat` / `StudyMate.sh`:

1. **Check Python** - Verify Python is installed
2. **Install dependencies** - Run `pip install -r requirements.txt` if needed
3. **Setup environment** - Create `.env` from `.env.example` if missing
4. **Initialize database** - Run `app.seed` on first use
5. **Start server** - Launch FastAPI on `http://127.0.0.1:8000`
6. **Open browser** - Automatically open app in default browser
7. **Keep running** - Terminal stays open; press Ctrl+C to stop

---

## Google Drive Integration

**No special setup needed!** The entire folder works from Google Drive:

1. Place the whole StudyMate folder in Google Drive
2. Keep Google Drive Desktop app syncing
3. Run `StudyMate.bat` (Windows) or `StudyMate.sh` (Mac)
4. Works exactly the same!

All data (database, uploads) stays in the folder and syncs automatically.

---

## Building Executables

For sharing without Python requirement:

```bash
# Install PyInstaller (included in requirements.txt)
pip install pyinstaller

# Build (choose your platform)
python build_executable.py
```

Output:
- Windows: `dist/StudyMate.exe` - Just double-click
- Mac: `dist/StudyMate.app` - Just double-click

Share these executables with others - no Python needed!

---

## Configuration

### First Run
- `.env` created automatically from `.env.example`
- Edit to add: `ANTHROPIC_API_KEY=sk-ant-...`
- Database initialized automatically

### Port Conflicts
If port 8000 is busy, edit `launcher.py`:
```python
# Line ~50: change "8000" to "8001"
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Python not found | Install from https://www.python.org, add to PATH |
| Dependencies fail | Run: `pip install -r requirements.txt` |
| Port 8000 busy | Change port in `launcher.py` |
| Browser won't open | Copy URL from console manually |
| Database corrupted | Delete `studymate.db`, restart |

---

## Next Steps

1. **Test it**: Double-click `StudyMate.bat` (Windows) or `StudyMate.sh` (Mac)
2. **Add API key**: Edit `.env`, add `ANTHROPIC_API_KEY`
3. **Share it**: 
   - For others with Python: Share entire folder
   - For others without Python: Build executable with `build_executable.py`
4. **Use from Google Drive**: Just place folder in Drive, keep syncing active

---

## Technical Details

### launcher.py
- Checks Python installation
- Manages dependencies
- Creates `.env` if missing
- Runs database init on first launch
- Starts uvicorn server
- Opens browser automatically
- Graceful shutdown on Ctrl+C

### StudyMate.bat / StudyMate.sh
- Simple wrapper around Python launcher
- Auto-installs missing dependencies
- Works in any directory (local or Google Drive)
- No configuration needed

### build_executable.py
- Uses PyInstaller to bundle everything
- Includes all dependencies
- Creates platform-specific executable
- Can be run on any machine

---

## Platform Support

| OS | Method | Status |
|----|--------|--------|
| Windows | .bat launcher | ✅ Tested |
| Windows | .exe executable | ✅ Ready |
| Mac | .sh launcher | ✅ Ready |
| Mac | .app executable | ✅ Ready |
| Linux | .sh launcher | ✅ Ready |
| Google Drive | All methods | ✅ Supported |

---

## Questions?

- **Quick questions**: See `QUICK_START.md`
- **Detailed setup**: See `LAUNCHER_SETUP.md`
- **Technical details**: Check `launcher.py` source code
