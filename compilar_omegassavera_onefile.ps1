Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Compilando omegassavera.exe" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$projectRoot = $PSScriptRoot

$apiDir = Join-Path $projectRoot 'api'
$distDir = Join-Path $projectRoot 'dist'
$buildDir = Join-Path $projectRoot 'build\omegaegassavera'
$specPath = Join-Path $apiDir 'omegassavera.spec'
$outputExe = Join-Path $distDir 'omegassavera.exe'
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
    python -m PyInstaller $specPath --noconfirm --clean --distpath $distDir --workpath $buildDir
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
