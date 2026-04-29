$ErrorActionPreference = 'Stop'

$outDir = 'C:\Users\alexandre bandarra\Desktop\global'
$htmlPath = Join-Path $outDir 'strategy_report.html'
$pdfPath  = Join-Path $outDir 'strategy_report.pdf'

$readSafe = {
    param($p)
    if (Test-Path $p) { Get-Content -Raw -Path $p } else { "" }
}

$files = @(
    @{ title='Strategy 1: Volatility Breakout [Fixed Risk]'; path='C:\Users\alexandre bandarra\backtest_results.md' }
    @{ title='Strategy 2: Optimized BTC Mean Reversion (RSI 20/65)'; path='C:\Users\alexandre bandarra\mean_reversion_results.md' }
    @{ title='Strategy 3: Volume Breakout V3E [Score2of3]'; path='C:\Users\alexandre bandarra\v3e_results.md' }
    @{ title='Strategy 4: BTC V4C Range Kalman'; path='C:\Users\alexandre bandarra\v4c_results.md' }
)

# Minimal markdown-to-HTML (tables, headers, bold, lists)
function Md2Html([string]$md) {
    $lines = $md -split "`r?`n"
    $out = New-Object System.Collections.Generic.List[string]
    $inTable = $false
    $tableBuf = @()
    $inList = $false
    foreach ($l in $lines) {
        $t = $l.TrimEnd()
        if ($t -match '^\s*\|') {
            if (-not $inTable) { $inTable = $true; $tableBuf = @() }
            $tableBuf += $t
            continue
        } elseif ($inTable) {
            # Flush table
            $out.Add('<table>')
            $hdr = $tableBuf[0]
            $sep = if ($tableBuf.Count -gt 1) { $tableBuf[1] } else { '' }
            $hasHdr = ($sep -match '^[\s\|\-:]+$')
            $rowStart = if ($hasHdr) { 2 } else { 0 }
            if ($hasHdr) {
                $cells = ($hdr -replace '^\s*\|','' -replace '\|\s*$','') -split '\|'
                $out.Add('<thead><tr>')
                foreach ($c in $cells) { $out.Add("<th>$(InlineMd($c.Trim()))</th>") }
                $out.Add('</tr></thead><tbody>')
            } else { $out.Add('<tbody>') }
            for ($i=$rowStart; $i -lt $tableBuf.Count; $i++) {
                $cells = ($tableBuf[$i] -replace '^\s*\|','' -replace '\|\s*$','') -split '\|'
                $out.Add('<tr>')
                foreach ($c in $cells) { $out.Add("<td>$(InlineMd($c.Trim()))</td>") }
                $out.Add('</tr>')
            }
            $out.Add('</tbody></table>')
            $inTable = $false
            $tableBuf = @()
        }
        if ($t -match '^### (.*)') { $out.Add("<h3>$(InlineMd($Matches[1]))</h3>"); continue }
        if ($t -match '^## (.*)')  { $out.Add("<h2>$(InlineMd($Matches[1]))</h2>"); continue }
        if ($t -match '^# (.*)')   { $out.Add("<h1>$(InlineMd($Matches[1]))</h1>"); continue }
        if ($t -match '^---$')     { $out.Add("<hr/>"); continue }
        if ($t -match '^\s*-\s(.*)') {
            if (-not $inList) { $out.Add('<ul>'); $inList = $true }
            $out.Add("<li>$(InlineMd($Matches[1]))</li>")
            continue
        } elseif ($inList) {
            $out.Add('</ul>')
            $inList = $false
        }
        if ($t -match '^\s*\d+\.\s(.*)') {
            $out.Add("<p>$(InlineMd($t))</p>")
            continue
        }
        if ([string]::IsNullOrWhiteSpace($t)) { $out.Add(''); continue }
        $out.Add("<p>$(InlineMd($t))</p>")
    }
    if ($inList) { $out.Add('</ul>') }
    if ($inTable) {
        # end flush
        $out.Add('<table><tbody>')
        foreach ($tr in $tableBuf) {
            $cells = ($tr -replace '^\s*\|','' -replace '\|\s*$','') -split '\|'
            $out.Add('<tr>')
            foreach ($c in $cells) { $out.Add("<td>$(InlineMd($c.Trim()))</td>") }
            $out.Add('</tr>')
        }
        $out.Add('</tbody></table>')
    }
    return ($out -join "`n")
}

function InlineMd([string]$s) {
    $s = [System.Web.HttpUtility]::HtmlEncode($s)
    $s = [regex]::Replace($s, '\*\*([^*]+)\*\*', '<strong>$1</strong>')
    $s = [regex]::Replace($s, '(?<!\*)\*([^*]+)\*(?!\*)', '<em>$1</em>')
    $s = [regex]::Replace($s, '`([^`]+)`', '<code>$1</code>')
    return $s
}

Add-Type -AssemblyName System.Web

$css = @'
<style>
@page { size: A4; margin: 18mm 14mm; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #1c2e3a; margin: 0; line-height: 1.45; }
h1 { color: #0b1e28; border-bottom: 2px solid #2962ff; padding-bottom: 4px; margin-top: 28px; font-size: 22px; }
h2 { color: #0b1e28; background: linear-gradient(90deg, #e8f0fe, transparent); padding: 8px 10px; border-left: 4px solid #2962ff; margin-top: 22px; font-size: 17px; }
h3 { color: #263238; margin-top: 14px; font-size: 14px; }
p  { margin: 6px 0; font-size: 12px; }
code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 11px; }
ul { margin: 6px 0 10px 18px; font-size: 12px; }
li { margin: 2px 0; }
hr { border: none; border-top: 1px dashed #cfd8dc; margin: 16px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 14px 0; font-size: 11px; }
th, td { border: 1px solid #cfd8dc; padding: 5px 7px; text-align: left; vertical-align: top; }
thead th { background: #263238; color: #fff; font-weight: 600; }
tbody tr:nth-child(even) { background: #f7fafc; }
strong { color: #0b1e28; }
.cover { text-align: center; padding: 80px 20px; page-break-after: always; }
.cover h1 { border: none; font-size: 34px; color: #2962ff; }
.cover .sub { font-size: 16px; color: #546e7a; margin-top: 10px; }
.cover .meta { margin-top: 40px; font-size: 12px; color: #607d8b; }
.section { page-break-before: always; }
.footer { position: fixed; bottom: 6mm; left: 0; right: 0; text-align: center; font-size: 9px; color: #90a4ae; }
</style>
'@

$today = Get-Date -Format 'MMMM dd, yyyy'
$cover = @"
<div class="cover">
  <h1>BTC/USDT Strategy Backtest Report</h1>
  <div class="sub">BINANCE:BTCUSDT &middot; Timeframes: 15m / 1H / 4H</div>
  <div class="sub">4 Strategies tested &middot; Walk-forward &middot; Optimization</div>
  <div class="meta">Report generated $today &middot; TradingView Strategy Tester</div>
</div>
"@

$sections = New-Object System.Collections.Generic.List[string]
$sections.Add($cover)
foreach ($f in $files) {
    $md = & $readSafe $f.path
    $body = Md2Html $md
    $sections.Add("<div class='section'>$body</div>")
}

$html = @"
<!doctype html>
<html><head><meta charset="utf-8"><title>BTC Strategy Backtest Report</title>$css</head>
<body>
$($sections -join "`n")
<div class="footer">Strategy Report &middot; BTCUSDT &middot; $today</div>
</body></html>
"@

Set-Content -Path $htmlPath -Value $html -Encoding UTF8
Write-Output "HTML written: $htmlPath"

# Convert to PDF via Chrome headless
$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw 'No Chrome or Edge found' }
Write-Output "Browser: $chrome"

$htmlUri = ([System.Uri]$htmlPath).AbsoluteUri
& $chrome --headless --disable-gpu --no-sandbox "--print-to-pdf=$pdfPath" --print-to-pdf-no-header $htmlUri 2>&1 | Out-Null

if (Test-Path $pdfPath) {
    $size = (Get-Item $pdfPath).Length
    Write-Output "PDF written: $pdfPath ($size bytes)"
} else {
    throw 'PDF not produced'
}
