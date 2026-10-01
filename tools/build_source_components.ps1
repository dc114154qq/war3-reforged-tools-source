param(
    [ValidateSet('trainer', 'hotkeys', 'selection', 'all')]
    [string]$Component = 'all',
    [string]$OutputDirectory = "$PSScriptRoot\..\build-source"
)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$out = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $out -Force | Out-Null

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

Set-Location $root
Require-Command 'python'

if ($Component -in @('hotkeys', 'all')) {
    Require-Command 'clang'
    python tools\build_war3_hotkey_bridge.py --output (Join-Path $out 'war3_hotkey_bridge.dll')
}

if ($Component -in @('selection', 'all')) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_war3_selection_plugin.ps1 -OutputDirectory (Join-Path $out 'selection-native')
}

if ($Component -in @('trainer', 'all')) {
    Write-Host 'Trainer native bridge inputs are selected by the trainer spec and corresponding tools/build_*.ps1 scripts.'
    Write-Host 'Build those inputs for the target game profile before invoking PyInstaller.'
}

Write-Host "Source build preparation completed: $out"

