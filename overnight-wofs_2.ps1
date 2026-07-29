$ErrorActionPreference = "Continue"

$cases = @(
  "gilbert_river_qld",
  "fitzroy_river_wa",
  "moonie_river_qld_nsw",
  "lachlan_river_nsw",
  "daly_river_nt"
)

$resolutions = @(30, 60, 90, 300)

$runDir = "output\overnight-wofs_dea_mask"
$csvDir = "output\water_extent_csv_dea_mask"
New-Item -ItemType Directory -Force $runDir | Out-Null
New-Item -ItemType Directory -Force $csvDir | Out-Null

Start-Transcript -Path "$runDir\run.log"

foreach ($resolution in $resolutions) {
  foreach ($case in $cases) {
    $log = "$runDir\${case}_${resolution}m.log"
    $outCsv = "$csvDir\${case}_${resolution}m_water_extent.csv"

    Write-Host "START $case @ ${resolution}m"

    python scripts/extract_water_extent_csv.py `
      --only $case `
      --resolution $resolution `
      --wet-mask dea_stats `
      --output-csv $outCsv `
      --mask-cache-dir output\wofs_cache `
      --compute-batch-size 16 `
      --read-workers 0 `
      --year-workers 1 *> $log

    if ($LASTEXITCODE -eq 0) {
      Write-Host "DONE  $case @ ${resolution}m"
    } else {
      Write-Warning "FAILED $case @ ${resolution}m; see $log"
    }
  }
}

Stop-Transcript
