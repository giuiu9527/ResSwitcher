@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 安装 PyInstaller...
python -m pip install --quiet pyinstaller
echo [2/2] 打包...
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "分辨率切换器" ^
  --paths src ^
  --add-data "driver;driver" ^
  --uac-admin ^
  src\app.py
if errorlevel 1 (echo 打包失败 & pause & exit /b 1)
echo.
echo 完成: dist\分辨率切换器.exe
pause
