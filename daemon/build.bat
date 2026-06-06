@echo off
echo ===================================
echo   PitWall AI — Build EXE
echo ===================================
echo.

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Building executable...
pyinstaller ^
  --onefile ^
  --noconsole ^
  --name PitWallAI ^
  --icon pitwall\icon.ico ^
  --add-data "pitwall;pitwall" ^
  pitwall_launcher.py

echo.
echo ===================================
echo   Done! EXE is in dist\PitWallAI.exe
echo ===================================
pause
