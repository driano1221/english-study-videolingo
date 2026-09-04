$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$legacyLayout = Test-Path -LiteralPath (Join-Path $workspaceRoot 'videos')
$artifactRoot = if ($legacyLayout) { $workspaceRoot } else { $repoRoot }

Push-Location $repoRoot
try {
    pyinstaller --noconfirm `
        --workpath (Join-Path $artifactRoot 'build') `
        --distpath (Join-Path $artifactRoot 'dist') `
        (Join-Path $repoRoot 'packaging\windows\VideoLingo Simples.spec')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

$exe = Join-Path $artifactRoot 'dist\VideoLingo Simples.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "PyInstaller terminou sem criar $exe"
}
Write-Output "Executável criado: $exe"
