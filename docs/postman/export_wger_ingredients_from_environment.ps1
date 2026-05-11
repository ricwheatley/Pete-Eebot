param(
    [string]$EnvironmentPath = "docs/postman/out/wger.postman_environment.out.json",
    [string]$OutputPath = "docs/postman/out/wger_ingredientinfo_language_2.json"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvironmentPath)) {
    throw "Environment export not found: $EnvironmentPath"
}

$environment = Get-Content -LiteralPath $EnvironmentPath -Raw | ConvertFrom-Json
$entry = $environment.values | Where-Object { $_.key -eq "wger_ingredients_json" } | Select-Object -First 1

if ($null -eq $entry -or [string]::IsNullOrWhiteSpace($entry.value)) {
    throw "wger_ingredients_json was not found in $EnvironmentPath"
}

$ingredients = $entry.value | ConvertFrom-Json
$outputDirectory = Split-Path -Parent $OutputPath

if ($outputDirectory) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}

$ingredients | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "Wrote $($ingredients.Count) ingredients to $OutputPath"
