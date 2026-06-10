Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Compilando omegasext_v1.02.exe" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$projectRoot = $PSScriptRoot

$apiDir = Join-Path $projectRoot 'api'
$distDir = Join-Path $projectRoot 'dist'
$buildDir = Join-Path $projectRoot 'build\omegasext_v1.02'
$specPath = Join-Path $apiDir 'omegasext_v1.02.spec'
$outputExe = Join-Path $distDir 'omegasext_v1.02.exe'
$dbConfigPath = Join-Path $projectRoot 'db_connection_config.json'

if (-not (Test-Path $specPath)) {
    throw "No se encuentra el archivo spec: $specPath"
}

if (Test-Path $buildDir) {
    Remove-Item -Path $buildDir -Recurse -Force
}

if (Test-Path $outputExe) {
    Remove-Item -Path $outputExe -Force
}

Push-Location $apiDir
try {
    & "c:/Proyectos/Desarrollo_Omegas - copia/.venv-1/Scripts/python.exe" -m PyInstaller $specPath --noconfirm --clean --distpath $distDir --workpath $buildDir
}
finally {
    Pop-Location
}

if (Test-Path $outputExe) {
    if (Test-Path $dbConfigPath) {
        Copy-Item -Path $dbConfigPath -Destination $distDir -Force
    }

    Write-Host ""
    Write-Host "COMPILACION EXITOSA" -ForegroundColor Green
    Write-Host $outputExe -ForegroundColor White
} else {
    throw "No se pudo generar $outputExe"
}