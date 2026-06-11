# Build a standalone camera_capture.exe (no Python needed to run it).
#
# Run this from the repository root on Windows:
#   powershell -ExecutionPolicy Bypass -File camera_module\build_exe.ps1
#
# Output:
#   dist\camera_capture.exe   — the program
#   dist\config.yaml          — editable settings (read on every start)

$ErrorActionPreference = "Stop"

# 1. Make sure PyInstaller and runtime deps are installed
pip install pyinstaller -r camera_module/requirements.txt

# 2. Build a single-file exe.
#    --collect-all genicam/harvesters pulls in their binary/data files
#    that PyInstaller cannot discover by static analysis.
pyinstaller --onefile --name camera_capture `
    --paths . `
    --collect-all genicam `
    --collect-all harvesters `
    camera_module/examples/capture_example.py

# 3. Put an editable config next to the exe (the exe looks for
#    config.yaml in its own folder first).
Copy-Item camera_module/config.yaml dist/config.yaml -Force

Write-Host ""
Write-Host "Done. Your program is in: dist\camera_capture.exe"
Write-Host "Edit settings any time in:  dist\config.yaml"
