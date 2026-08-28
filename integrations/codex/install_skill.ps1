[CmdletBinding()]
param(
    [string]$DestinationRoot,
    [switch]$Force
)

$changeLensSkillSource = Join-Path $PSScriptRoot 'aeh-change-lens'
if (-not $DestinationRoot) {
    $changeLensCodexRoot = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
    if (-not $changeLensCodexRoot) {
        $changeLensCodexRoot = Join-Path $env:USERPROFILE '.codex'
    }
    $DestinationRoot = Join-Path $changeLensCodexRoot 'skills'
}

$changeLensSkillTarget = Join-Path $DestinationRoot 'aeh-change-lens'
if ((Test-Path -LiteralPath $changeLensSkillTarget) -and -not $Force) {
    throw "Skill already exists: $changeLensSkillTarget. Re-run with -Force to update it."
}

New-Item -ItemType Directory -Path $changeLensSkillTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $changeLensSkillSource 'SKILL.md') -Destination $changeLensSkillTarget -Force
Copy-Item -LiteralPath (Join-Path $changeLensSkillSource 'agents') -Destination $changeLensSkillTarget -Recurse -Force
Copy-Item -LiteralPath (Join-Path $changeLensSkillSource 'references') -Destination $changeLensSkillTarget -Recurse -Force

Write-Output $changeLensSkillTarget
