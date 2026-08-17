[CmdletBinding()]
param(
    [int]$ExitCode = 1,
    [switch]$NoUi,
    [ValidateRange(1, 60)]
    [int]$PopupSeconds = 15
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $projectRoot "runtime\logs\git-assessment.log"
$port = if ($env:GIT_ASSESSMENT_PORT) { $env:GIT_ASSESSMENT_PORT } else { "8765" }

$message = switch ($ExitCode) {
    3 {
        "Git Assessment 無法啟動，因為連接埠 $port 已被其他程式使用。`r`n`r`n請關閉占用該連接埠的程式後再試；詳細資訊請查看：`r`n$logPath"
    }
    default {
        "Git Assessment 無法啟動。請確認 Python 3.11+ 與 Git 可正常使用。`r`n`r`n詳細資訊請查看：`r`n$logPath"
    }
}

if ($NoUi) {
    Write-Output $message
    exit 0
}

$createdNew = $false
$mutex = [System.Threading.Mutex]::new($true, "Local\GitAssessmentErrorDialog", [ref]$createdNew)
if (-not $createdNew) {
    $mutex.Dispose()
    exit 0
}

try {
    $shell = New-Object -ComObject WScript.Shell
    $null = $shell.Popup($message, $PopupSeconds, "Git Assessment 啟動失敗", 16)
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
