# Windows Dependency Installation Troubleshooting

## Problem: Dependencies Failed to Install

If you see an error like "Failed to install dependencies", follow these steps:

---

## Solution 1: Use the Manual Installer (Easy)

1. **Double-click** `install_dependencies.bat`
2. Wait for it to complete
3. If successful, double-click `StudyMate.bat`

If that doesn't work, continue to Solution 2.

---

## Solution 2: PowerShell Method (Recommended)

1. **Right-click PowerShell** → Select "Run as Administrator"
2. Copy and paste these commands one at a time:

```powershell
cd "c:\Users\ahame\studymate-dp1"
python --version
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

3. Wait for each command to complete
4. If all succeed, run: `python launcher.py`

---

## Solution 3: Check Python Installation

The most common issue is Python not being in your PATH.

**Test 1: Verify Python works**
- Open Command Prompt
- Type: `python --version`
- Should see: `Python 3.x.x` (version number)

If it says "python is not recognized":
- **REINSTALL PYTHON** from https://www.python.org
- ✅ Check "Add Python to PATH" during installation
- ✅ Choose "Install for all users"
- Restart your computer
- Try again

---

## Solution 4: Specific Error Fixes

### Error: "Microsoft Visual C++ is required"
```
Install: https://visualstudio.microsoft.com/downloads/
Choose: Desktop development with C++
```

### Error: "pip permission denied"
```powershell
# Run PowerShell as Administrator, then:
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Error: "psycopg2 failed to build"
```powershell
# Install with binary wheels:
python -m pip install psycopg2-binary
```

### Error: "httpx version conflict"
```powershell
# Clear and reinstall:
python -m pip install --upgrade --force-reinstall -r requirements.txt
```

---

## Solution 5: Clean Reinstall

If nothing works, try a complete clean install:

**Step 1: Remove old environment**
```powershell
# Run PowerShell as Administrator:
python -m pip uninstall -y -r requirements.txt
```

**Step 2: Upgrade tools**
```powershell
python -m pip install --upgrade pip setuptools wheel
```

**Step 3: Fresh install**
```powershell
python -m pip install -r requirements.txt
```

---

## Solution 6: Virtual Environment Method

Some systems work better with a virtual environment:

```powershell
# Run PowerShell as Administrator:
cd "c:\Users\ahame\studymate-dp1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python launcher.py
```

---

## Solution 7: One-Command Install

Copy and paste this entire block into PowerShell (as Administrator):

```powershell
$dir = "c:\Users\ahame\studymate-dp1"
cd $dir
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
Write-Host "Done! You can now run: python launcher.py"
```

---

## Verify Installation

After running any solution, verify it worked:

```powershell
python -c "import fastapi; import uvicorn; print('OK - All good!')"
```

Should print: `OK - All good!`

---

## Still Not Working?

If none of the above work, please try the manual command-by-command approach:

```powershell
# Run PowerShell as Administrator

python --version

python -m pip install --upgrade pip
python -m pip install setuptools wheel
python -m pip install fastapi
python -m pip install uvicorn
python -m pip install sqlalchemy
python -m pip install anthropic

# If any of these fail, note which one and the error message
```

---

## What Each Package Does

If you want to install manually:

```powershell
python -m pip install fastapi==0.115.0              # Web framework
python -m pip install uvicorn[standard]==0.30.6    # Server
python -m pip install sqlalchemy==2.0.35            # Database
python -m pip install pydantic==2.9.2               # Validation
python -m pip install jinja2==3.1.4                 # Templates
python -m pip install python-multipart==0.0.12     # File uploads
python -m pip install python-dotenv==1.0.1         # Configuration
python -m pip install fsrs==4.1.1                   # Spaced revision
python -m pip install anthropic==0.39.0             # AI (optional)
python -m pip install pyinstaller==6.5.0            # Build executables
```

---

## Quick Checklist

- [ ] Python 3.10+ installed
- [ ] Python in PATH (`python --version` works)
- [ ] PowerShell run as Administrator
- [ ] Run pip upgrade first: `python -m pip install --upgrade pip setuptools wheel`
- [ ] Run: `python -m pip install -r requirements.txt`
- [ ] Verify: `python -c "import fastapi"`

---

## Still Stuck?

The most reliable method is the **Virtual Environment**:

```powershell
# Run PowerShell as Administrator:
cd "c:\Users\ahame\studymate-dp1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python launcher.py
```

This creates an isolated environment and usually works when system-wide install fails.

---

## Notes

- Don't worry about warning messages during install (they're usually harmless)
- The install can take 2-5 minutes - be patient
- Some packages need compilation (will show progress bars)
- Your internet connection must be active during install

Need more help? Check if your antivirus is blocking pip (temporarily disable and try again).
