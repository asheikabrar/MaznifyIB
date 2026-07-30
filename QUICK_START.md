# Single-Click App Guide

## TL;DR - Run StudyMate with One Click

### Windows
👉 **Double-click `StudyMate.bat`**
- Opens http://127.0.0.1:8000 in your browser
- Server runs in background
- Press Ctrl+C in the console to stop

### Mac
👉 **Make executable then run:**
```bash
chmod +x StudyMate.sh
./StudyMate.sh
```
Or just double-click `StudyMate.sh` in Finder.

---

## From Google Drive

1. **Place entire StudyMate folder in Google Drive**
2. **Keep Google Drive Desktop app syncing**
3. **Windows**: Double-click `StudyMate.bat`
4. **Mac**: Double-click `StudyMate.sh`

That's it! Works exactly the same whether running locally or from Google Drive.

---

## Standalone Executable (No Python Required)

If you want to share StudyMate without requiring Python:

```bash
python build_executable.py
```

This creates:
- **Windows**: `dist/StudyMate.exe` (double-click to run)
- **Mac**: `dist/StudyMate.app` (double-click to run)

These work anywhere with no Python installation needed.

---

## First Time Setup

1. **Install Python 3.10+** from https://www.python.org
2. Dependencies install automatically on first run
3. Database creates automatically
4. Edit `.env` to add your Anthropic API key (optional)

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Python not found" | Install Python, add to PATH |
| "Port 8000 in use" | Edit `launcher.py`, change port 8000 to 8001 |
| "Browser won't open" | Copy URL from console manually |
| Database errors | Delete `studymate.db`, restart |

See `LAUNCHER_SETUP.md` for full details.
