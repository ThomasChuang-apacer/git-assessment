# Git 實作考試系統規格書

文件版本：1.4
文件狀態：Current Implementation
更新日期：2026-11-24

## 1. 文件目的

本文件描述 Git 實作考試系統目前的產品範圍、使用流程、題目規則、資料保存、安全防線、程式架構、測試及 CI/CD。

若文件與程式不一致，以下列檔案為實際來源：

- 題目文字與判定：`questions/questions.json`
- 題目初始 Git 狀態：`app/template_builder.py`
- 自動檢查邏輯：`app/check_engine.py`
- Session、基準 SHA、雜湊驗證與 workspace：`app/services.py`
- 頁面與 API：`app/routes.py`
- 本機安全防護：`app/security.py`
- CI/CD：`.github/workflows/ci-cd.yml`

## 2. 產品定位

這是一套在 Windows 本機執行的 Git 實作測驗。受測者使用 Terminal、PowerShell 或 VS Code 操作真實 Git repository，再回到瀏覽器按「檢查結果」。

### 2.1 主要目標

- 以真實 repository 測驗常見 Git 操作。
- 六題彼此獨立，互不影響。
- 支援「練習模式」（逐步步驟與操作線索）與「考試模式」（僅目標與限制，提示另計次數）。
- 判題基準（起始 SHA、原始分支 SHA、模擬遠端目標 SHA、patch-id）由伺服器端保存於結果 JSON，防止竄改 repository ref 繞過檢查。
- 結果摘要記錄完整時間軸、檢查累計次數、重設次數與 SHA-256 完整性雜湊。
- 支援選擇性的共用考場「考官模式」（`GIT_ASSESSMENT_EXAMINER_PIN`）保護受測者隱私與危險操作。
- 題目操作不需要連線至公司 Git、GitHub 或 Gerrit；支援預先打包離線 `wheels/` 安裝。

### 2.2 非目標

目前不包含：

- 網頁內嵌 Terminal。
- 跨機集中成績伺服器或多人帳號系統。
- 強制考試限時或及格分數鎖定。
- Linux 或 macOS 正式支援。

## 3. 執行環境與啟動

### 3.1 環境需求

- Windows 10 或 Windows 11。
- Python 3.11 或更新版本。
- Git for Windows。
- Microsoft Edge 或 Google Chrome。

### 3.2 啟動與停止

一般使用者雙擊 `Start Git Assessment.vbs`。

啟動行為：

1. 透過 `/api/health` 核對 `project_root`（`instance_id`）：若同一目錄已在執行，直接開啟瀏覽器；若端口被其他目錄的 Git Assessment 占用，則跳出警告避免誤連錯誤實例。
2. 建立或驗證 `.venv`（若專案包含 `wheels/*.whl`，使用 `--no-index --find-links=wheels` 離線安裝）。
3. 透過 `First Start Git Assessment.ps1`（支援 `FirstStart` 與 `Starting` 模式）顯示啟動進度視窗。
4. 建立或驗證六題離線 Git templates（目前版本 `TemplateBuilder.VERSION = 8`）。
5. 啟動綁定於 `127.0.0.1` 的本機 Web Server（支援 `RotatingFileHandler` 自動去除 ANSI 控制碼）。

可用環境變數：

| 變數 | 用途 |
|---|---|
| `GIT_ASSESSMENT_PORT` | 修改服務 port（預設 `8765`） |
| `GIT_ASSESSMENT_NO_BROWSER=1` | 啟動後不自動開啟瀏覽器 |
| `GIT_ASSESSMENT_EXAMINER_PIN` | 設定考官模式 PIN 碼；設定後啟用共用電腦隱私保護 |

## 4. 使用者與考官流程

### 4.1 首頁與建立測驗

- 前端與後端同步驗證姓名為非純空白且不超過 80 字元。
- 支援選擇 `practice`（練習模式）或 `exam`（考試模式）。
- 建立測驗時由伺服器擷取各題基準 SHA（`baseline`）並設定 HttpOnly `SameSite=Lax` cookie `git_assessment_active_session`。

### 4.2 任務總覽、題目頁與提示

- 任務狀態分為 `not_started`、`in_progress`（已開啟或已檢查未通過）、`completed`。
- 任務頁提供「複製路徑」、「開啟資料夾」、`? 如何開始`（含常見 Vim / `--no-edit` 卡關說明）、可展開的「操作提示（記錄檢視次數）」、「檢查結果」及「重設本題」。
- 檢查失敗項目顯示受測者目前的實際狀態（目前分支、commit 數、訊息或未清理檔案等）。

### 4.3 重設與審計紀錄

- `reset_task` 原子重建題目 repository 並重新擷取 `baseline`，同時**保留累計 `check_attempts`、`hints_used` 並遞增 `reset_count`**。
- `completed_at` 僅於首次通過時寫入，重複檢查不會覆寫首次完成時間。

### 4.4 結果摘要與考官模式（`/examiner`）

- 結果頁顯示姓名、測驗模式、開始／完成時間、總作答時間、每題檢查／重設／提示次數與耗時、SHA-256 完整性驗證碼、可展開操作時間軸，並支援「複製文字摘要」與「保存成 PNG」。
- 若設定 `GIT_ASSESSMENT_EXAMINER_PIN`，首頁只允許同瀏覽器 cookie 繼續自己的未完成測驗；歷史清單、刪除、修復、原始 JSON 與殘留檔清理僅可在 `/examiner` 解鎖後操作。

## 5. Workspace 與結果資料

- Schema version 維持為 `3`（向下相容遷移），新增選用欄位：`mode`、`integrity_hash`，以及每題 `first_opened_at`、`reset_count`、`hints_used`、`viewed_hints`、`baseline`。
- 每次 `_save_result` 會自動計算並寫入 `integrity_hash`（SHA-256），於結果頁與考官模式即時驗算資料完整性。

## 6. 六道實作題目與檢查類型

- **Task 01**：選擇性提交（只提交 `src/config.py`，驗證 `HEAD != baseline.assessment_start`、`README.md` 保持未暫存修改且未進入 commit、`debug.log` 保持 untracked 且未進入 commit）。
- **Task 02**：Amend 最新 commit（額外驗證 `reflog_contains_action: commit (amend)`）。
- **Task 03**：建立功能分支（使用 `ref_equals` 比對伺服器端 `baseline.main` SHA 防止 `branch -f` 竄改）。
- **Task 04**：Fetch、Rebase 與 Conflict（驗證 `origin/main == baseline.remote_pending_main`、`no_conflict_markers`、設定正規表示式比對與無殘留舊值、`reflog_contains_action: rebase (finish)`）。
- **Task 05**：Stash 與遠端分支（驗證 `branch_tracks_remote`、`Task05` 相容性版本比對 `>= TemplateBuilder.TASK05_MIN_VERSION`、放寬 reflog 來回切換檢查）。
- **Task 06**：Cherry-pick 指定 Commit（Template v8 的 `fix/validation` 含 2 筆 commit，額外驗證未帶入不相關檔案 `notes/validator_todo.md`、`reflog_contains_action: cherry-pick` 與 `patch_equivalent`）。

目前支援 27 種 check types（含 `branch_tracks_remote`、`no_conflict_markers`、`file_equals`、`file_matches`、`file_not_contains`、`file_not_exists`、`ref_equals`、`reflog_contains_action`、`patch_equivalent`）。

## 7. API 與安全設計

| Method | Endpoint | 用途 |
|---|---|---|
| `GET` | `/` | 首頁、環境狀態、模式選擇與續考 |
| `POST` | `/api/sessions` | 建立新測驗（表單 302 / JSON 201） |
| `POST` | `/api/sessions/<id>/delete` | 刪除測驗與 workspace（考官權限） |
| `GET` | `/assessment/<id>` | 任務總覽 |
| `GET` | `/assessment/<id>/tasks/<task>` | 題目頁 |
| `GET` | `/assessment/<id>/result` | 結果摘要、時間軸與 PNG 保存 |
| `POST` | `/api/sessions/<id>/tasks/<task>/check` | 執行檢查 |
| `POST` | `/api/sessions/<id>/tasks/<task>/hint` | 記錄檢視提示次數 |
| `POST` | `/api/sessions/<id>/tasks/<task>/reset` | 重設題目（保留累計檢查／重設紀錄） |
| `POST` | `/api/sessions/<id>/tasks/<task>/repair` | 備份並修復題目（考官權限） |
| `POST` | `/api/sessions/<id>/tasks/<task>/open` | 開啟 repository 資料夾 |
| `POST` | `/api/sessions/<id>/tasks/<task>/remote-update` | 模擬第四題遠端更新 |
| `GET` | `/api/sessions/<id>/result` | 取得結果 JSON（考官權限） |
| `GET` | `/examiner` | 考官模式控制台 |
| `POST` | `/api/examiner/unlock` / `lock` | 驗證／鎖定考官 PIN |
| `POST` | `/api/examiner/cleanup` | 清理 `quarantine/` 與舊版殘留檔 |
| `GET` | `/api/health` | 取得 runtime 健康狀態與 `instance_id` / `project_root` |
| `POST` | `/api/shutdown` | 安全停止 server |

安全機制：
- **所有 HTTP 方法（含 GET）** 皆驗證 `Host` 必須屬於本機 `LOCAL_HOSTS`（防止 DNS rebinding）。
- 所有寫入方法驗證同源 `Origin` 與 `X-Git-Assessment-Token` / `_api_token`。
- 查無資料（`KeyError`）回傳 `404`；無效輸入（`ValueError`）回傳 `400`；所有 HTML 與 JSON HTTP 錯誤皆回傳中文訊息。
