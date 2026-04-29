$ErrorActionPreference = 'Continue'
$browser = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if (-not (Test-Path $browser)) { $browser = 'C:\Program Files\Google\Chrome\Application\chrome.exe' }

$htmlOrig = 'C:\Users\alexandre bandarra\Desktop\global\strategy_report.html'
$pdfOrig  = 'C:\Users\alexandre bandarra\Desktop\global\strategy_report.pdf'

# Work in a space-free directory to avoid Chrome/Edge arg-parsing quirks
$work = 'C:\tmp_pdf'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$htmlW = Join-Path $work 'report.html'
$pdfW  = Join-Path $work 'report.pdf'
Copy-Item $htmlOrig $htmlW -Force
if (Test-Path $pdfW) { Remove-Item $pdfW -Force }

$tmpProfile = 'C:\tmp_pdf\profile'
New-Item -ItemType Directory -Path $tmpProfile -Force | Out-Null

$uri = ([System.Uri]$htmlW).AbsoluteUri
Write-Output "URI: $uri"

$proc = Start-Process -FilePath $browser -ArgumentList @(
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',
    '--disable-extensions',
    '--no-pdf-header-footer',
    "--user-data-dir=$tmpProfile",
    "--print-to-pdf=$pdfW",
    $uri
) -Wait -PassThru -NoNewWindow

Write-Output "Exit: $($proc.ExitCode)"
if (Test-Path $pdfW) {
    Copy-Item $pdfW $pdfOrig -Force
    $s = (Get-Item $pdfOrig).Length
    Write-Output "PDF: $pdfOrig ($s bytes)"
} else {
    Write-Output "MISSING"
}
Remove-Item -Recurse -Force $tmpProfile -ErrorAction SilentlyContinue
Remove-Item -Force $htmlW -ErrorAction SilentlyContinue
Remove-Item -Force $pdfW -ErrorAction SilentlyContinue
