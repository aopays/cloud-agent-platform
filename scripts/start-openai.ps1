Write-Warning "start-openai.ps1 is deprecated; use scripts\start.ps1."
& (Join-Path $PSScriptRoot "start.ps1") @args
exit $LASTEXITCODE
