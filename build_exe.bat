@echo off
rem Windows .exe ??p??t??se (egy f??jl, ablakos). Eredm??ny: dist\PdfRenamer.exe
cd /d "%~dp0"
py -m pip install -r requirements-build.txt || exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --windowed --name PdfRenamer run.py || exit /b 1
echo.
echo Kesz: %~dp0dist\PdfRenamer.exe
