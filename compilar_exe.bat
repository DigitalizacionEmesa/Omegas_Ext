@echo off
echo ============================================
echo Compilando appOMEGAS.exe
echo ============================================
echo.

:: Mapear unidad de red temporalmente
net use Z: "\\emebidwh\DIgitalizacion\Desarrollo_Omegas" /persistent:no 2>nul

cd /d Z:\api

echo Directorio actual: %CD%
echo.

echo Limpiando carpetas anteriores...
if exist "build" rmdir /s /q "build"
if exist "..\dist\appOMEGAS" rmdir /s /q "..\dist\appOMEGAS"

echo.
echo Ejecutando PyInstaller...
python -m PyInstaller appOMEGAS.spec --noconfirm --distpath "..\dist" --workpath "build"

echo.
if exist "..\dist\appOMEGAS\appOMEGAS.exe" (
    echo ============================================
    echo COMPILACION EXITOSA!
    echo Ejecutable en: Z:\dist\appOMEGAS\appOMEGAS.exe
    echo ============================================
) else (
    echo ============================================
    echo ERROR: No se pudo crear el ejecutable
    echo ============================================
)

:: Desmontar unidad
net use Z: /delete /yes 2>nul

echo.
pause
