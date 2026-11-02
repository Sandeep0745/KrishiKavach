# Python skips hidden .pth files. Copied environments must retain their startup hooks.
$projectRoot = Split-Path -Parent $PSScriptRoot
foreach ($environmentName in @('.venv', '.venv-voice', '.venv-browser', '.venv-gpu')) {
    $packagesPath = Join-Path $projectRoot "$environmentName/Lib/site-packages"
    if (Test-Path -LiteralPath $packagesPath) {
        Get-ChildItem -LiteralPath $packagesPath -Filter '*.pth' -File -Force | ForEach-Object {
            if ($_.Attributes -band [System.IO.FileAttributes]::Hidden) {
                $_.Attributes = $_.Attributes -band (-bnot [System.IO.FileAttributes]::Hidden)
            }
        }
    }
}
