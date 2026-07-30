# StudyMate - Single-Click App Launch Guide

## 🚀 START HERE

Choose your platform:

### Windows
**👉 Double-click `StudyMate.bat`**

That's it! Your app will:
- Install dependencies automatically
- Initialize the database
- Start the server
- Open http://127.0.0.1:8000 in your browser

### Mac/Linux
**👉 Double-click `StudyMate.sh`** (or run `./StudyMate.sh` in terminal)

Same thing - fully automatic!

---

## 📚 Documentation (Read in This Order)

1. **`QUICK_START.md`** ← Start here! (2 min read)
   - Quick overview of all options
   - TL;DR for each platform

2. **`VISUAL_GUIDE.md`** ← Visual walkthrough
   - Folder structure
   - Step-by-step what happens
   - Troubleshooting table

3. **`LAUNCHER_SETUP.md`** ← Detailed guide
   - Full setup instructions
   - Configuration options
   - Advanced features

4. **`SINGLE_CLICK_APP.md`** ← Technical details
   - How it all works
   - File descriptions
   - Platform support matrix

5. **`DELIVERY_SUMMARY.md`** ← What you got
   - Complete list of deliverables
   - Feature comparison
   - Next steps checklist

6. **`README.md`** ← Original project info
   - About StudyMate
   - Features
   - Project structure

---

## ⚡ Three Ways to Launch

### Option 1: One-Click (Easiest)
```bash
Windows: Double-click StudyMate.bat
Mac:     Double-click StudyMate.sh
```
✅ Fully automatic
✅ No terminal needed
✅ Works first time

### Option 2: Terminal (If Option 1 doesn't work)
```bash
# Windows (PowerShell)
./StudyMate.bat

# Mac/Linux
./StudyMate.sh
```

### Option 3: Manual
```bash
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000 manually

---

## 🌐 From Google Drive

**Setup:**
1. Move entire StudyMate folder to Google Drive
2. Keep Google Drive Desktop app syncing

**Use:**
- Windows: Double-click `StudyMate.bat`
- Mac: Double-click `StudyMate.sh`

Everything works exactly the same! Your data syncs automatically.

---

## 📦 Share With Others (No Python Needed)

Want to send StudyMate to friends who don't have Python?

```bash
python build_executable.py
```

This creates:
- **Windows**: `dist/StudyMate.exe` (one file, ~300MB)
- **Mac**: `dist/StudyMate.app` (one app bundle)

They just double-click - no Python installation needed!

---

## ⚙️ Configuration

### First Run
- `.env` file created automatically
- Database initialized automatically
- Everything ready to go

### Add API Key (Optional)
Edit `.env` and add:
```
ANTHROPIC_API_KEY=sk-ant-...
```
Then restart the app.

### Port Busy?
If port 8000 is already in use, edit `launcher.py`:
1. Find line with `"8000"`
2. Change to `"8001"` (or any free port)
3. Restart

---

## ❓ Quick Troubleshooting

| Issue | Fix |
|-------|-----|
| "Python not found" | Install Python 3.10+ from https://www.python.org |
| Nothing happens | Check console for error messages |
| Port 8000 busy | Edit launcher.py, change port |
| Database error | Delete `studymate.db`, restart |

See `LAUNCHER_SETUP.md` for more troubleshooting.

---

## 📂 Project Structure

```
StudyMate/
├─ StudyMate.bat              ← Windows launcher (CLICK ME)
├─ StudyMate.sh               ← Mac launcher (CLICK ME)
├─ launcher.py                ← Core launcher logic
├─ build_executable.py        ← Build standalone app
├─ requirements.txt           ← Dependencies
├─ .env.example               ← Config template
├─ app/                       ← FastAPI application
│  ├─ main.py
│  ├─ models.py
│  └─ templates/
├─ studymate.db               ← Database (created on first run)
├─ uploads/                   ← Your files
└─ Documentation/
   ├─ QUICK_START.md
   ├─ VISUAL_GUIDE.md
   ├─ LAUNCHER_SETUP.md
   ├─ SINGLE_CLICK_APP.md
   ├─ DELIVERY_SUMMARY.md
   └─ README.md
```

---

## ✨ Key Features

✅ **One-click launch** - No setup needed
✅ **Cross-platform** - Windows, Mac, Linux
✅ **Google Drive ready** - Sync automatically
✅ **Auto-setup** - First run installs everything
✅ **Auto-launch** - Browser opens automatically
✅ **Shareable** - Build standalone executables
✅ **Data portable** - Move folder anywhere

---

## 🎯 Your Next Steps

1. **Try it now:**
   - Windows: Double-click `StudyMate.bat`
   - Mac: Double-click `StudyMate.sh`

2. **Verify it works:**
   - Browser opens to http://127.0.0.1:8000
   - You see StudyMate login page

3. **Configure (optional):**
   - Edit `.env`
   - Add: `ANTHROPIC_API_KEY=sk-ant-...`
   - Restart app

4. **Try from Google Drive:**
   - Move folder to Google Drive
   - Run launcher from there
   - Everything syncs!

5. **Share with friends (optional):**
   - Run: `python build_executable.py`
   - Send them `StudyMate.exe` or `StudyMate.app`
   - They can use without Python!

---

## 📞 Need Help?

1. **Quick questions** → Read `QUICK_START.md`
2. **Setup issues** → Check `LAUNCHER_SETUP.md`
3. **How it works** → See `SINGLE_CLICK_APP.md`
4. **Error in console** → Read the error message carefully
5. **Still stuck** → Check `LAUNCHER_SETUP.md` Troubleshooting section

---

## ✅ You're Ready!

StudyMate is now:
- ✅ One-click ready
- ✅ Cross-platform ready
- ✅ Google Drive ready
- ✅ Shareable ready

**Just double-click and start studying!**

---

**Last Updated**: 2024
**Version**: 1.0
**Status**: Ready to Use 🎓
