# Git 實作考試系統

一套在 Windows 本機執行的 Git 操作測驗。受測者在真實 Git repository 完成任務，再回到瀏覽器檢查結果。

系統包含六個主題：選擇性提交、amend、branch、rebase conflict、stash、cherry-pick。測驗資料只保存在本機，不會連線到公司 repository。

## 環境需求

- Windows 10 或 Windows 11
- Python 3.11 或更新版本
- Git for Windows

## 快速開始

1. 雙擊 `Start Git Assessment.vbs`。
2. 第一次啟動會自動建立 Python 環境並安裝套件（若專案內附 `wheels/` 會優先離線安裝）。
3. 瀏覽器會開啟 `http://127.0.0.1:8765`。
4. 輸入姓名並選擇「練習模式」或「考試模式」，依題目提供的路徑進入 repository 操作。
5. 完成後回到瀏覽器按「檢查結果」，全數通過後可保存 PNG 成績單或複製文字摘要。

需要查看啟動錯誤時，改用 `scripts/start.bat`。停止程式請使用網頁右上角的「安全關閉」；網頁無法操作時可執行 `scripts/Stop Git Assessment.bat`。

測驗進度保存在 `runtime/`，關閉後可以繼續作答。

## 進階環境變數與離線打包

- `GIT_ASSESSMENT_PORT`：修改服務連接埠（預設 `8765`）。
- `GIT_ASSESSMENT_NO_BROWSER=1`：啟動後不自動開啟瀏覽器。
- `GIT_ASSESSMENT_EXAMINER_PIN`：設定考官 PIN 碼（啟用共用考場隱私鎖定，歷史清單、刪除、修復與原始 JSON 僅在 `/examiner` 解鎖後顯示）。
- 離線環境打包：先在有網路的電腦執行 `scripts\Prepare Offline Wheels.bat` 下載 `.whl` 至 `wheels/`，再整包複製給新人使用即可完全離線安裝。

## 輔助腳本說明

`scripts/` 目錄包含以下內部與輔助腳本：

- `start.bat`：終端機啟動腳本，需查看完整啟動輸出或排查錯誤時使用。
- `Stop Git Assessment.bat`：停止背景伺服器處理程序。網頁無法操作時使用。
- `Prepare Offline Wheels.bat`：預先下載離線安裝所需 Python wheel 檔至 `wheels/`。
- `First Start Git Assessment.ps1`：啟動時顯示 GUI 進度視窗（由 VBS 自動呼叫）。
- `Show Git Assessment Error.ps1`：啟動失敗時顯示錯誤訊息彈窗（由 `start.bat` 自動呼叫）。

## 執行測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 開發流程

```powershell
git switch -c feature/<change-name>
# 修改並執行測試
git add .
git commit -m "Describe the change"
git push -u origin feature/<change-name>
```

Push 後在 GitHub 建立 Pull Request。PR 的 CI 通過後再合併到 `main`；合併後 `main` 會再次執行 CI。

## 發布版本

```powershell
git switch main
git pull --ff-only
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

推送 `v*` tag 後，GitHub Actions 會先執行測試，再建立 ZIP 並發布到 GitHub Releases。

## 主要目錄

```text
app/                 Flask 程式與網頁
questions/           題目與自動檢查規則
data/templates/      自動產生的題目範本
runtime/             本機測驗進度與紀錄
scripts/             本機啟動與輔助腳本
wheels/              選用的離線 Python 套件包
tests/               自動化測試
```

完整架構、題目規則與資料格式請參考 [spec.md](spec/spec.md)。
