param(
    [Parameter(Mandatory = $true)][string]$BackupDirectory,
    [string]$ConfirmRestore = "",
    [string]$ComposeFile = "docker-compose.production.yml",
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$backup = Resolve-Path -LiteralPath $BackupDirectory
& python scripts/verify_backup.py $backup
if ($LASTEXITCODE -ne 0) { throw "Backup verification failed" }
if ($VerifyOnly) { Write-Host "Backup verification completed without restore."; exit 0 }
if ($ConfirmRestore -ne "RESTORE-ValuSee") { throw "Refusing restore: pass -ConfirmRestore RESTORE-ValuSee" }

& docker compose -f $ComposeFile stop api monitor-worker
Get-Content -LiteralPath (Join-Path $backup "postgres.sql") -Raw | & docker compose -f $ComposeFile exec -T postgres psql -v ON_ERROR_STOP=1 -U valuesee -d valuesee
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed" }
& docker run --rm -v "valuesee_minio-data:/target" -v "${backup}:/backup:ro" alpine:3.22 sh -c "rm -rf /target/* && tar xzf /backup/minio-data.tgz -C /target"
if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed" }
& docker run --rm -v "valuesee_attachment-cache:/target" -v "${backup}:/backup:ro" alpine:3.22 sh -c "rm -rf /target/* && tar xzf /backup/attachments.tgz -C /target"
if ($LASTEXITCODE -ne 0) { throw "Attachment restore failed" }
& docker compose -f $ComposeFile up -d api monitor-worker
Write-Host "Restore completed. Run scripts/verify-release.ps1 before opening traffic."
