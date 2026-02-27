# =================================================
# Script de compilación para appOMEGAS.exe
# =================================================

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Compilando appOMEGAS.exe" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$rutaProyecto = "\\emebidwh\DIgitalizacion\Desarrollo_Omegas"
$rutaApi = "$rutaProyecto\api"
$rutaDist = "$rutaProyecto\dist"

# Crear directorio temporal local
$tempDir = "$env:TEMP\appOMEGAS_build"
if (Test-Path $tempDir) {
    Remove-Item -Path $tempDir -Recurse -Force
}
New-Item -Path $tempDir -ItemType Directory -Force | Out-Null

Write-Host "Copiando archivos al directorio temporal..." -ForegroundColor Yellow
# Copiar solo los archivos necesarios para la compilación
Copy-Item -Path "$rutaApi\appOMEGAS.py" -Destination $tempDir -Force
Copy-Item -Path "$rutaApi\appOMEGAS.spec" -Destination $tempDir -Force
Copy-Item -Path "$rutaProyecto\translations" -Destination $tempDir -Recurse -Force
Copy-Item -Path "$rutaProyecto\assets" -Destination $tempDir -Recurse -Force
Copy-Item -Path "$rutaProyecto\IMAGENES" -Destination $tempDir -Recurse -Force
Copy-Item -Path "$rutaProyecto\Pantallas" -Destination $tempDir -Recurse -Force

Write-Host "Directorio temporal: $tempDir" -ForegroundColor Gray

# Cambiar al directorio temporal
Set-Location -Path $tempDir

# Actualizar las rutas en el archivo .spec para el directorio local
$specContent = Get-Content -Path "appOMEGAS.spec" -Raw
$specContent = $specContent -replace "\.\./translations", "translations"
$specContent = $specContent -replace "\.\./assets", "assets"
$specContent = $specContent -replace "\.\./IMAGENES", "IMAGENES"
$specContent = $specContent -replace "\.\./Pantallas", "Pantallas"
Set-Content -Path "appOMEGAS.spec" -Value $specContent

Write-Host ""
Write-Host "Ejecutando PyInstaller..." -ForegroundColor Yellow
Write-Host ""

# Ejecutar PyInstaller
python -m PyInstaller appOMEGAS.spec --noconfirm

# Verificar si se creó el ejecutable
$exePath = "$tempDir\dist\appOMEGAS\appOMEGAS.exe"
if (Test-Path $exePath) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "COMPILACION EXITOSA!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    
    # Copiar el resultado al destino final
    Write-Host ""
    Write-Host "Copiando ejecutable al servidor..." -ForegroundColor Yellow
    
    if (Test-Path "$rutaDist\appOMEGAS") {
        Remove-Item -Path "$rutaDist\appOMEGAS" -Recurse -Force
    }
    Copy-Item -Path "$tempDir\dist\appOMEGAS" -Destination $rutaDist -Recurse -Force
    
    Write-Host ""
    Write-Host "Ejecutable disponible en:" -ForegroundColor Cyan
    Write-Host "$rutaDist\appOMEGAS\appOMEGAS.exe" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Red
    Write-Host "ERROR: No se pudo crear el ejecutable" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Red
}

# Limpiar directorio temporal
Write-Host ""
Write-Host "Limpiando archivos temporales..." -ForegroundColor Gray
Set-Location -Path $env:USERPROFILE
Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Proceso completado." -ForegroundColor Cyan
