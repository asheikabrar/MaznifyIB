# StudyMate Single-Click Launcher Setup

## Overview
This guide explains how to run StudyMate as a single-click app on Windows and Mac, either locally or from Google Drive.

## Quick Start

### Windows
1. **Simple method** (Recommended):
   - Double-click `StudyMate.bat`
   - Server starts, browser opens automatically
   - Done! You can now use StudyMate

2. **Advanced method** (Build standalone exe):
   ```powershell
   python build_executable.py
   ```
   - Creates `dist/StudyMate.exe` - a self-contained executable
   - Works without Python installed
   - Can be moved anywhere or shared

### Mac / Linux
1. **Simple method**:
   ```bash
   chmod +x StudyMate.sh
   ./StudyMate.sh
   ```

2. **Advanced method** (Build standalone app):
   ```bash
   python3 build_executable.py
   ```
   - Creates `dist/StudyMate.app` (Mac) or `dist/StudyMate` (Linux)
   - Works without Python installed

---

## Setup Requirements (One-time)

### Windows
1. **Install Python 3.10+** from https://www.python.org
   - ✅ Check "Add Python to PATH" during install
2. **Extract StudyMate** to any folder
3. Double-click `StudyMate.bat` - dependencies install automatically

### Mac
1. **Install Python 3.10+** via Homebrew or https://www.python.org
2. Extract StudyMate to any folder
3. Run `chmod +x StudyMate.sh` in terminal
4. Double-click `StudyMate.sh` or run `./StudyMate.sh` in terminal

---

## Running from Google Drive

### Windows
1. **Don't build the .exe yet** - just use `StudyMate.bat`
2. Place your entire StudyMate folder in Google Drive
3. Right-click `StudyMate.bat` → Open with → Select Python
4. Or double-click after syncing (Google Drive Sync needed)

### Mac
1. Make sure `StudyMate.sh` is executable:
   ```bash
   chmod +x StudyMate.sh
   ```
2. Place folder in Google Drive (with Google Drive desktop app syncing)
3. Open Finder → Navigate to Google Drive → StudyMate folder
4. Double-click `StudyMate.sh`

**Important**: Google Drive syncing must be active for this to work smoothly.

---

## Configuration

### First Run
- The app creates `.env` automatically from `.env.example`
- **To enable AI features**: Edit `.env` and add your Anthropic API key:
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  ```

### Database
- SQLite database (`studymate.db`) is auto-created on first run
- Data persists across sessions
- Safe to move the entire folder - all data comes with it

---

## Troubleshooting

### "Python not found"
**Windows**: Reinstall Python, check "Add Python to PATH"
**Mac**: Run `which python3` in terminal to verify installation

### "Port 8000 already in use"
- Another app is using port 8000
- Edit `launcher.py`, change `"8000"` to `"8001"` in two places
- Browser will then open to `http://127.0.0.1:8001`

### Browser doesn't open
- Check the terminal/console for `http://127.0.0.1:8000`
- Copy-paste that URL into your browser manually

### "Missing dependencies"
- Scripts auto-install them, but if it fails:
  ```bash
  pip install -r requirements.txt
  ```

### Database errors on first run
- Delete `studymate.db` if corrupted
- Re-run the launcher - it will auto-initialize

---

## Building Standalone Executables (Advanced)

If you want to share StudyMate without requiring Python installation:

### Install PyInstaller
```bash
pip install pyinstaller
```

### Build
```bash
python build_executable.py
```

### Output
- **Windows**: `dist/StudyMate.exe` - Double-click to run
- **Mac**: `dist/StudyMate.app` - Double-click or run from Finder
- **Linux**: `dist/StudyMate` - Run from terminal

### Share the executable
- Windows: Share just `StudyMate.exe`
- Mac: Share the entire `StudyMate.app` folder
- Create a zip for easy distribution

---

## File Structure
```
StudyMate/
├── StudyMate.bat          ← Windows launcher (double-click this)
├── StudyMate.sh           ← Mac/Linux launcher
├── launcher.py            ← Core launcher logic
├── build_executable.py    ← Build standalone exe
├── requirements.txt       ← Dependencies
├── .env.example           ← Configuration template
├── app/                   ← FastAPI application
│   ├── main.py
│   ├── models.py
│   └── templates/
├── studymate.db           ← SQLite database (created on first run)
└── uploads/               ← User uploads directory
```

---

## Tips

1. **Add to Desktop**: Create shortcut to `StudyMate.bat` (Windows) or `StudyMate.sh` (Mac)
2. **Port conflicts**: If 8000 is busy, edit `launcher.py` line 50 to use a different port
3. **Always running**: Leave the terminal/console window open while using the app
4. **Backup data**: Your data is in `studymate.db` - keep this safe
5. **Move anywhere**: You can move the entire folder and it will still work

---

## Next Steps

1. Run `StudyMate.bat` (Windows) or `StudyMate.sh` (Mac)
2. Browser opens to http://127.0.0.1:8000
3. Add your Anthropic API key to `.env` (optional but recommended)
4. Start studying!

Need help? Check the console output for error messages.
