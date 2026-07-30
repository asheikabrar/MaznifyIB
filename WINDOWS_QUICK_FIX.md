# Windows Dependency Installation - Quick Fix

If `StudyMate.bat` fails to install dependencies, try these in order:

## Quick Fix #1 - Use Manual Installer (Easiest)
```
Double-click → install_dependencies.bat
```
Then double-click `StudyMate.bat` again.

---

## Quick Fix #2 - Run Diagnostics
```
Double-click → diagnose.bat
```
This shows you exactly what's wrong. Share the output if you need help.

---

## Quick Fix #3 - PowerShell (Recommended)
1. **Right-click PowerShell** → "Run as Administrator"
2. Copy-paste this entire block:
```powershell
cd "c:\Users\ahame\studymate-dp1"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```
3. Wait for it to finish
4. Double-click `StudyMate.bat`

---

## Quick Fix #4 - If Python Isn't Recognized
1. Uninstall Python
2. Download Python 3.11 from https://www.python.org
3. **Important**: Check ✅ "Add Python to PATH"
4. Click "Install Now"
5. Restart your computer
6. Try again

---

## Most Common Cause

**Python isn't in your PATH** = Python installed but computer can't find it

**Solution**:
- Reinstall Python
- ✅ Check "Add Python to PATH" during install
- Restart computer

---

## Files to Use

| File | When to use |
|------|-----------|
| `StudyMate.bat` | Normal - just double-click |
| `install_dependencies.bat` | If dependencies fail to install |
| `diagnose.bat` | To see what's wrong |
| `install_dependencies.ps1` | Advanced PowerShell method |

---

## Still Not Working?

Read the full guide: `WINDOWS_DEPENDENCY_FIX.md`

It has 7 different solutions and specific error codes.

---

**TL;DR**: Try `install_dependencies.bat` first!
