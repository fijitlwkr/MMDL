param(
    [string]$Python = 'C:\Users\brain\anaconda3\python.exe',
    [string]$ScoringRoot = ''
)
$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'HypB Judge - secure key entry'
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if (-not $ScoringRoot) {
    $ScoringRoot = Join-Path (Split-Path $RepoRoot -Parent) 'eval_B_20261101/scoring'
}
Set-Location -LiteralPath $RepoRoot
& $Python -X utf8 (Join-Path $PSScriptRoot 'judge_runner.py') --scoring-root $ScoringRoot
if ($LASTEXITCODE -eq 0) {
    $Host.UI.RawUI.WindowTitle = 'HypB Judge - COMPLETE'
    Write-Host 'COMPLETE. The key has been removed from the launcher environment.' -ForegroundColor Green
} else {
    $Host.UI.RawUI.WindowTitle = 'HypB Judge - FAILED / PENDING'
    Write-Host 'FAILED / PENDING. Inspect the local judge_launcher logs before resuming.' -ForegroundColor Red
}
