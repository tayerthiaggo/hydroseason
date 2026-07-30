$ErrorActionPreference = "Continue"

$pending = @(
  @{ case = "daly_river_nt";          res = 90 },
  @{ case = "daly_river_nt";          res = 300 },
  @{ case = "lachlan_river_nsw";      res = 90 },
  @{ case = "lachlan_river_nsw";      res = 300 },
  @{ case = "fitzroy_river_wa";       res = 90 },
  @{ case = "fitzroy_river_wa";       res = 300 },
  @{ case = "moonie_river_qld_nsw";   res = 300 }
)

$runDir = "output\overnight-wofs"
New-Item -ItemType Directory -Force $runDir | Out-Null

Start-Transcript -Path "$runDir\run_resume.log" -Append

foreach ($item in $pending) {
  $case = $item.case
  $resolution = $item.res
  $log = "$runDir\${case}_${resolution}m.log"

  Write-Host "START $case @ ${resolution}m"

  python scripts/extract_water_extent_csv.py `
    --only $case `
    --resolution $resolution `
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

Stop-Transcript
