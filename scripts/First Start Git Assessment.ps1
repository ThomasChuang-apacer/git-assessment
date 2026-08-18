param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$startBat = Join-Path $ProjectRoot "scripts\start.bat"
$runtimeRoot = Join-Path $ProjectRoot "runtime"
$statusPath = Join-Path $runtimeRoot "setup-status.txt"
[System.IO.Directory]::CreateDirectory($runtimeRoot) | Out-Null
Remove-Item -LiteralPath $statusPath -Force -ErrorAction SilentlyContinue

$form = New-Object System.Windows.Forms.Form
$form.Text = "Git Assessment 第一次啟動"
$form.ClientSize = New-Object System.Drawing.Size(500, 190)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.ControlBox = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(248, 246, 241)

$title = New-Object System.Windows.Forms.Label
$title.AutoSize = $false
$title.Location = New-Object System.Drawing.Point(30, 24)
$title.Size = New-Object System.Drawing.Size(440, 32)
$title.Font = New-Object System.Drawing.Font("Microsoft JhengHei UI", 14, [System.Drawing.FontStyle]::Bold)
$title.Text = "正在準備 Git Assessment"
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.AutoSize = $false
$status.Location = New-Object System.Drawing.Point(31, 66)
$status.Size = New-Object System.Drawing.Size(438, 24)
$status.Font = New-Object System.Drawing.Font("Microsoft JhengHei UI", 10)
$status.ForeColor = [System.Drawing.Color]::FromArgb(82, 113, 101)
$status.Text = "正在檢查第一次啟動環境…"
$form.Controls.Add($status)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(32, 103)
$progress.Size = New-Object System.Drawing.Size(436, 22)
$progress.Style = "Marquee"
$progress.MarqueeAnimationSpeed = 24
$form.Controls.Add($progress)

$hint = New-Object System.Windows.Forms.Label
$hint.AutoSize = $false
$hint.Location = New-Object System.Drawing.Point(31, 139)
$hint.Size = New-Object System.Drawing.Size(438, 22)
$hint.Font = New-Object System.Drawing.Font("Microsoft JhengHei UI", 9)
$hint.ForeColor = [System.Drawing.Color]::FromArgb(100, 116, 109)
$hint.Text = "第一次需要建立環境並下載 Flask，請保持網路連線。"
$form.Controls.Add($hint)

$process = New-Object System.Diagnostics.Process
$process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
$process.StartInfo.FileName = $env:ComSpec
$process.StartInfo.Arguments = ('/d /c ""{0}""' -f $startBat)
$process.StartInfo.WorkingDirectory = $ProjectRoot
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.CreateNoWindow = $true
$process.StartInfo.EnvironmentVariables["GIT_ASSESSMENT_HIDDEN"] = "1"
$process.StartInfo.EnvironmentVariables["GIT_ASSESSMENT_PROGRESS"] = "1"

try {
    if (-not $process.Start()) {
        throw "無法啟動安裝程序"
    }
} catch {
    [System.Windows.Forms.MessageBox]::Show(
        "Git Assessment 無法開始第一次啟動。請確認 Python 3.11+ 與 Git for Windows 已安裝。",
        "Git Assessment",
        "OK",
        "Error"
    ) | Out-Null
    exit 1
}

$port = 8765
$configuredPort = [Environment]::GetEnvironmentVariable("GIT_ASSESSMENT_PORT")
if ($configuredPort -and [int]::TryParse($configuredPort, [ref]$port) -eq $false) {
    $port = 8765
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 250
$timer.Add_Tick({
    $phase = ""
    if (Test-Path -LiteralPath $statusPath) {
        try {
            $phase = [System.IO.File]::ReadAllText($statusPath).Trim()
        } catch [System.IO.IOException] {
            $phase = ""
        }
        switch ($phase) {
            "create-venv" { $status.Text = "正在建立專用 Python 環境…" }
            "install-packages" { $status.Text = "正在下載並安裝 Flask…" }
            "start-server" { $status.Text = "環境已完成，正在啟動 Git Assessment…" }
        }
    }

    if ($process.HasExited) {
        $timer.Stop()
        Remove-Item -LiteralPath $statusPath -Force -ErrorAction SilentlyContinue
        [System.Windows.Forms.MessageBox]::Show(
            "Git Assessment 無法完成第一次啟動。請確認 Python 3.11+、Git for Windows 與網路連線後再試一次。",
            "Git Assessment",
            "OK",
            "Error"
        ) | Out-Null
        $form.Close()
        return
    }

    if ($phase -eq "start-server") {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $connection = $client.ConnectAsync("127.0.0.1", $port)
            if ($connection.Wait(100) -and $client.Connected) {
                $timer.Stop()
                $progress.Style = "Continuous"
                $progress.Value = 100
                $status.Text = "準備完成，正在開啟瀏覽器…"
                Remove-Item -LiteralPath $statusPath -Force -ErrorAction SilentlyContinue
                [System.Windows.Forms.Application]::DoEvents()
                Start-Sleep -Milliseconds 800
                $form.Close()
            }
        } catch {
        } finally {
            $client.Dispose()
        }
    }
})

$form.Add_Shown({ $timer.Start() })
[System.Windows.Forms.Application]::Run($form)
