# StudyMate - One-Click Launch Guide

## 🚀 Quick Start (Choose Your OS)

### Windows
```
📁 StudyMate/
   📄 StudyMate.bat  ← Double-click this!
   └─ (rest of files)
```
✅ App opens automatically in browser

---

### Mac
```
📁 StudyMate/
   📄 StudyMate.sh  ← Double-click this!
   └─ (rest of files)
```
✅ App opens automatically in browser

---

## 📍 From Google Drive

**Setup:**
1. Drag StudyMate folder to Google Drive
2. Keep Google Drive Desktop app running
3. Done!

**Use:**
- Windows: Double-click `StudyMate.bat`
- Mac: Double-click `StudyMate.sh`

Everything syncs automatically - your data is portable!

---

## 📦 Share Without Python

```bash
python build_executable.py
```

Creates:
- **Windows**: `dist/StudyMate.exe` ← Share this file
- **Mac**: `dist/StudyMate.app` ← Share this folder

Recipients just double-click - no Python needed!

---

## 📋 What Happens When You Click

```
StudyMate.bat/sh
    ↓
Check Python installed
    ↓
Install dependencies (first time only)
    ↓
Create .env file (if missing)
    ↓
Initialize database (first time only)
    ↓
Start server on http://127.0.0.1:8000
    ↓
🌐 Browser opens automatically
    ↓
✅ Ready to use!
```

---

## ⚙️ Configuration

**First run**: Edit `.env` to add your Anthropic API key
```
ANTHROPIC_API_KEY=sk-ant-...
```

**Port busy?**: Edit `launcher.py`, change `8000` → `8001`

---

## ❌ Troubleshooting

| Error | Fix |
|-------|-----|
| Python not found | Install Python 3.10+ from python.org |
| Port 8000 in use | Edit launcher.py, change port |
| Dependencies fail | Run: `pip install -r requirements.txt` |
| Database error | Delete `studymate.db`, restart |

---

## 📁 Folder Structure

```
StudyMate/
├─ StudyMate.bat          ← Click me (Windows)
├─ StudyMate.sh           ← Click me (Mac)
├─ launcher.py            ← Core launcher logic
├─ build_executable.py    ← Build standalone app
├─ requirements.txt       ← Dependencies
├─ .env.example           ← Config template
├─ app/                   ← FastAPI app
│  ├─ main.py
│  ├─ models.py
│  └─ templates/
├─ studymate.db           ← Database (created on first run)
└─ uploads/               ← Your files (created on first upload)
```

---

## 💾 Your Data

**Where it's stored:**
- Database: `studymate.db` (stays in folder)
- Uploads: `uploads/` (stays in folder)
- Settings: `.env` (stays in folder)

**Backup**: Just copy the entire StudyMate folder

**Move anywhere**: Folder works on any computer with Python

---

## 🔧 Advanced: Build Standalone

No Python on target computer? Build an executable:

```bash
# On your machine
pip install pyinstaller  # (included in requirements.txt)
python build_executable.py

# Creates:
# - Windows: dist/StudyMate.exe
# - Mac: dist/StudyMate.app

# Share these files - they work anywhere!
```

---

## 📖 Full Documentation

- `QUICK_START.md` - Quick reference
- `LAUNCHER_SETUP.md` - Detailed setup guide
- `SINGLE_CLICK_APP.md` - Technical details
- `README.md` - Original project info

---

## ✅ You're All Set!

1. Double-click `StudyMate.bat` (Windows) or `StudyMate.sh` (Mac)
2. App opens in browser
3. Add Anthropic API key to `.env` (optional)
4. Start studying!

**Questions?** Check the documentation files above.
