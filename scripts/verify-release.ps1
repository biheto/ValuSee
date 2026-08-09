param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$MetricsToken = ""
)

$ErrorActionPreference = "Stop"
$health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 10
if ($health.status -ne "ok") { throw "Health probe failed" }
$ready = Invoke-RestMethod -Uri "$BaseUrl/ready" -TimeoutSec 15
if ($ready.status -ne "ok") { throw "Readiness probe failed" }
$headers = @{}
if ($MetricsToken) { $headers["X-Metrics-Token"] = $MetricsToken }
$metrics = Invoke-WebRequest -Uri "$BaseUrl/metrics" -Headers $headers -TimeoutSec 10
if ($metrics.Content -notmatch "valuesee_http_requests_total") { throw "Metrics probe failed" }
$home = Invoke-WebRequest -Uri "$BaseUrl/" -TimeoutSec 10
if ($home.Content -notmatch "ValuSee") { throw "Web application probe failed" }
Write-Host "Release probes passed for $BaseUrl"
