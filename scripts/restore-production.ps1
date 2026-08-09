param(
    [Parameter(Mandatory = $true)][string]$BackupDirectory,
    [Parameter(Mandatory = $true)][string]$ConfirmRestore,
    [string]$ComposeFile = "docker-compose.production.yml"
)

$ErrorActionPreference = "Stop"
if ($ConfirmRestore -ne "RESTORE-ValuSee") { throw "Refusing restore: pass -ConfirmRestore RESTORE-ValuSee" }
$backup = Resolve-Path -LiteralPath $BackupDirectory
$manifestPath = Join-Path $backup "manifest.json"
if (!(Test-Path -LiteralPath $manifestPath)) { throw "Backup manifest is missing" }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
foreach ($item in $manifest) {
    $file = Join-Path $backup $item.file
    if (!(Test-Path -LiteralPath $file)) { throw "Backup file missing: $($item.file)" }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $item.sha256) { throw "Checksum mismatch: $($item.file)" }
}

& docker compose -f $ComposeFile stop api monitor-worker
Get-Content -LiteralPath (Join-Path $backup "postgres.sql") -Raw | & docker compose -f $ComposeFile exec -T postgres psql -v ON_ERROR_STOP=1 -U valuesee -d valuesee
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed" }
& docker run --rm -v "valuesee_minio-data:/target" -v "${backup}:/backup:ro" alpine:3.22 sh -c "rm -rf /target/* && tar xzf /backup/minio-data.tgz -C /target"
if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed" }
& docker run --rm -v "valuesee_attachment-cache:/target" -v "${backup}:/backup:ro" alpine:3.22 sh -c "rm -rf /target/* && tar xzf /backup/attachments.tgz -C /target"
if ($LASTEXITCODE -ne 0) { throw "Attachment restore failed" }
& docker compose -f $ComposeFile up -d api monitor-worker
Write-Host "Restore completed. Run scripts/verify-release.ps1 before opening traffic."
