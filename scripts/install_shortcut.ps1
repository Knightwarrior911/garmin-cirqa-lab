$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) { throw 'Install the repository virtual environment first.' }
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop 'CIRQA Dashboard.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($path)
$link.TargetPath = $python
$link.Arguments = '"' + (Join-Path $repo 'launcher.pyw') + '"'
$link.WorkingDirectory = $repo
$link.Description = 'Open Garmin metrics and refresh from Garmin Connect'
$link.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
$link.Save()
Write-Output "Desktop shortcut installed: $path"
