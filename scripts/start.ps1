param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $python)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($null -ne $launcher) {
            & $launcher.Source -3 -m venv .venv
        }
        else {
            $launcher = Get-Command python -ErrorAction Stop
            & $launcher.Source -m venv .venv
        }
    }

    & $python -c "import fastapi, httpx, pydantic, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing project dependencies..."
        & $python -m pip install -c requirements.lock -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    }

    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath $envExample -Destination $envFile
        Write-Host "Created $envFile"
        Write-Host "Fill OPENAI_API_KEY in .env, then run this command again."
        exit 2
    }

    & $python scripts\preflight.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Home:      http://127.0.0.1:$Port/"
    Write-Host "Discovery: http://127.0.0.1:$Port/discovery"
    Write-Host "API docs:  http://127.0.0.1:$Port/docs"
    & $python -m uvicorn src.main:app --host 127.0.0.1 --port $Port --app-dir $projectRoot
}
finally {
    Pop-Location
}
