# ⚠️ WINDOWS DEPENDENCY INSTALLATION FAILED?

## START HERE - Choose One Option

### 🟢 **Option 1: Easy Fix (Recommended)**
```
Double-click → install_dependencies.bat
```
- Simplest method
- Shows all steps
- Auto-fixes most issues
- **Try this first!**

---

### 🔵 **Option 2: See What's Wrong**
```
Double-click → diagnose.bat
```
- Shows detailed diagnostics
- Helps troubleshoot
- Use if Option 1 doesn't work

---

### 🟣 **Option 3: PowerShell Method**
1. Right-click **PowerShell**
2. Select "Run as Administrator"
3. Copy-paste this entire block:
```powershell
cd "c:\Users\ahame\studymate-dp1"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

---

### 🟡 **Option 4: Full Troubleshooting**
Read: **`WINDOWS_QUICK_FIX.md`** (2 min read)

Still stuck? Read: **`WINDOWS_DEPENDENCY_FIX.md`** (Complete guide with 7 solutions)

---

## 📋 Files Available

| File | Purpose | Use When |
|------|---------|----------|
| `install_dependencies.bat` | Auto-installer | Dependencies fail |
| `diagnose.bat` | Shows errors | Need to debug |
| `WINDOWS_QUICK_FIX.md` | Quick guide | Want quick fix |
| `WINDOWS_DEPENDENCY_FIX.md` | Full guide | Need detailed help |
| `WINDOWS_DEPENDENCY_FIX_SUMMARY.md` | Overview | Want summary |

---

## ✅ Common Causes & Fixes

| Issue | Fix |
|-------|-----|
| "Python not recognized" | Reinstall Python, add to PATH, restart |
| "Permission denied" | Run as Administrator |
| "Module not found" | Run `install_dependencies.bat` |
| "Can't find pip" | Reinstall Python with pip enabled |

---

## 🚀 After Fixing Dependencies

1. Double-click **`StudyMate.bat`**
2. Server starts
3. Browser opens to http://127.0.0.1:8000
4. You're ready to go!

---

## 💬 Quick Reference

```
Problem:        Dependencies won't install
Solution 1:     Double-click install_dependencies.bat
Solution 2:     Run diagnose.bat (see what's wrong)
Solution 3:     PowerShell method (copy-paste commands)
Solution 4:     Read WINDOWS_DEPENDENCY_FIX.md (full guide)
```

---

**Bottom line**: Try `install_dependencies.bat` first. If that doesn't work, use the other options.

Good luck! 🎓
