param(
    [string]$OutputRoot = "backups",
    [string]$ComposeFile = "docker-compose.production.yml"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$destination = Join-Path (Resolve-Path ".") (Join-Path $OutputRoot $stamp)
New-Item -ItemType Directory -Force -Path $destination | Out-Null

& docker compose -f $ComposeFile ps --status running | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Production compose stack is not available" }

& docker compose -f $ComposeFile exec -T postgres pg_dump -U valuesee -d valuesee --clean --if-exists --no-owner | Set-Content -LiteralPath (Join-Path $destination "postgres.sql") -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed" }

& docker run --rm -v "valuesee_minio-data:/source:ro" -v "${destination}:/backup" alpine:3.22 tar czf /backup/minio-data.tgz -C /source .
if ($LASTEXITCODE -ne 0) { throw "MinIO backup failed" }
& docker run --rm -v "valuesee_attachment-cache:/source:ro" -v "${destination}:/backup" alpine:3.22 tar czf /backup/attachments.tgz -C /source .
if ($LASTEXITCODE -ne 0) { throw "Attachment backup failed" }

$manifest = Get-ChildItem -LiteralPath $destination -File | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    [pscustomobject]@{ file = $_.Name; bytes = $_.Length; sha256 = $hash.Hash.ToLowerInvariant() }
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination "manifest.json") -Encoding utf8
Write-Host "Backup completed: $destination"
