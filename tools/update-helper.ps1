$ErrorActionPreference = 'Stop'
$work = [IO.Path]::GetFullPath($PSScriptRoot)
$spec = Get-Content -LiteralPath (Join-Path $work 'update.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$install = [IO.Path]::GetFullPath($spec.install).TrimEnd('\')
$parent = Split-Path -Parent $install
if ($spec.runId -notmatch '^[a-f0-9]{32}$' -or -not $parent -or $install -eq [IO.Path]::GetPathRoot($install)) { throw 'Invalid install path' }
$appName = $spec.executable
if ([IO.Path]::GetFileName($appName) -ne $appName -or -not $appName.EndsWith('.exe')) { throw 'Invalid executable' }
$exe = Join-Path $install $appName
if (-not (Test-Path -LiteralPath $exe -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $install '_internal/build-info.json')) -or (Test-Path -LiteralPath (Join-Path $install '.git'))) { throw 'Not a packaged installation' }
if ((Get-Item -LiteralPath $install).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked install folders are not supported' }
$stage = [IO.Path]::GetFullPath((Join-Path $parent ('.hexu-stage-' + $spec.runId)))
$old = [IO.Path]::GetFullPath((Join-Path $parent ('.hexu-old-' + $spec.runId)))
foreach ($target in @($stage,$old)) {
  if ((Split-Path -Parent $target) -ne $parent -or $target -eq $install -or (Test-Path -LiteralPath $target)) { throw 'Invalid temporary target' }
}
$resultFile = Join-Path $work 'result.json'
$movedOld = $false
$movedModel = $false
$installedNew = $false
$restarted = $null
function Start-Library {
  $launch = @{FilePath=$exe;WorkingDirectory=$install;WindowStyle='Hidden';PassThru=$true}
  if ($spec.restartArgs.Count -gt 0) { $launch.ArgumentList = @($spec.restartArgs) }
  Start-Process @launch
}
try {
  # Unpack and validate before changing the running installation.
  Expand-Archive -LiteralPath (Join-Path $work $spec.programZip) -DestinationPath $stage -Force
  if (-not (Test-Path -LiteralPath (Join-Path $stage $appName) -PathType Leaf)) { throw 'Archive has no executable' }
  $newInfo = Get-Content -LiteralPath (Join-Path $stage '_internal/build-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($newInfo.version -ne $spec.expectedVersion) { throw 'Archive version does not match release' }
  if ($spec.modelZip) {
    Expand-Archive -LiteralPath (Join-Path $work $spec.modelZip) -DestinationPath $stage -Force
    foreach ($name in @('model.int8.onnx','tokens.txt')) {
      $modelFile = Join-Path $stage ('_internal/models/sense-voice/' + $name)
      if (-not (Test-Path -LiteralPath $modelFile) -or (Get-Item -LiteralPath $modelFile).Length -eq 0) { throw 'Incomplete model archive' }
    }
  }
  $program = Get-Process -Id $spec.pid -ErrorAction SilentlyContinue
  if ($program) {
    if ([IO.Path]::GetFullPath($program.Path) -ne $exe) { throw 'Process does not belong to this install' }
    $null = $program.CloseMainWindow()
    if (-not $program.WaitForExit(10000)) { Stop-Process -Id $spec.pid -Force }
  }
  # Both renames stay in the install's parent directory and on the same volume.
  Move-Item -LiteralPath $install -Destination $old
  $movedOld = $true
  $models = Join-Path $old '_internal/models'
  if (-not $spec.modelZip -and (Test-Path -LiteralPath $models)) {
    Move-Item -LiteralPath $models -Destination (Join-Path $stage '_internal/models')
    $movedModel = $true
  }
  Move-Item -LiteralPath $stage -Destination $install
  $installedNew = $true
  $restarted = Start-Library
  $healthy = $false
  for ($attempt=0;$attempt -lt 40;$attempt++) {
    try {
      $info = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $spec.restartPort + '/build-info.json') -TimeoutSec 1
      if ($info.version -eq $newInfo.version -and $info.commit -eq $newInfo.commit) { $healthy = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
  }
  if (-not $healthy) { throw 'Restarted service did not become ready' }
  @{state='completed';version=$newInfo.version;pid=$restarted.Id} | ConvertTo-Json | Set-Content -LiteralPath $resultFile -Encoding UTF8
  # A successful update leaves one installed version, with no old-program backup.
  Remove-Item -LiteralPath $old -Recurse -Force
  $movedOld = $false
  foreach ($name in @($spec.programZip,$spec.modelZip)) {
    if ($name -and [IO.Path]::GetFileName($name) -eq $name) { Remove-Item -LiteralPath (Join-Path $work $name) -Force -ErrorAction SilentlyContinue }
  }
} catch {
  $failure = $_.Exception.Message
  # Restore the previous working installation only when installation/restart failed.
  if ($movedOld) {
    if ($restarted) { Stop-Process -Id $restarted.Id -Force -ErrorAction SilentlyContinue }
    $modelSource = if ($installedNew) { Join-Path $install '_internal/models' } else { Join-Path $stage '_internal/models' }
    if ($movedModel -and (Test-Path -LiteralPath $modelSource)) { Move-Item -LiteralPath $modelSource -Destination (Join-Path $old '_internal/models') -Force }
    if ($installedNew -and (Test-Path -LiteralPath $install)) { Remove-Item -LiteralPath $install -Recurse -Force }
    Move-Item -LiteralPath $old -Destination $install
    $null = Start-Library
  } elseif (-not (Get-Process -Id $spec.pid -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $exe)) {
    $null = Start-Library
  }
  @{state='failed';message=$failure} | ConvertTo-Json | Set-Content -LiteralPath $resultFile -Encoding UTF8
  exit 1
} finally {
  if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
