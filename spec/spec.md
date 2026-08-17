# Git 實作考試系統規格書

文件版本：1.3
文件狀態：Current Implementation
更新日期：2026-08-17

## 1. 文件目的

本文件描述 Git 實作考試系統目前的產品範圍、使用流程、題目規則、資料保存、程式架構、測試及 CI/CD。

若文件與程式不一致，以下列檔案為實際來源：

- 題目文字與判定：`questions/questions.json`
- 題目初始 Git 狀態：`app/template_builder.py`
- 自動檢查邏輯：`app/check_engine.py`
- Session 與 workspace：`app/services.py`
- 頁面與 API：`app/routes.py`
- CI/CD：`.github/workflows/ci-cd.yml`

## 2. 產品定位

這是一套在 Windows 本機執行的 Git 實作測驗。受測者使用 Terminal、PowerShell 或 VS Code 操作真實 Git repository，再回到瀏覽器按「檢查結果」。

系統依 repository 的狀態判定結果，不記錄受測者逐條輸入的 Git 指令。

### 2.1 主要目標

- 以真實 repository 測驗常見 Git 操作。
- 六題彼此獨立，互不影響。
- 每題可立即檢查、重設及續考。
- 每位考生保留最近兩份有效測驗。
- 題目與檢查條件可由設定檔維護。
- 題目操作不需要連線至公司 Git、GitHub 或 Gerrit。

### 2.2 非目標

目前不包含：

- 網頁內嵌 Terminal。
- 分數、排名、及格門檻或考試限時。
- 帳號、密碼、考官權限或防作弊機制。
- 多人共用的中央伺服器。
- Linux 或 macOS 正式支援。
- 雲端部署或正式遠端 repository 整合。

## 3. 執行環境與啟動

### 3.1 環境需求

- Windows 10 或 Windows 11。
- Python 3.11 或更新版本。
- Git for Windows。
- Microsoft Edge 或 Google Chrome。

### 3.2 啟動與停止

一般使用者雙擊：

```text
Start Git Assessment.vbs
```

第一次啟動會：

1. 建立專案專用 `.venv`。
2. 安裝 `requirements/requirements.txt` 中的套件。
3. 建立六題離線 Git templates。
4. 啟動本機 Web Server。
5. 開啟瀏覽器。

需要查看即時錯誤時可改用 `scripts/start.bat`。正常停止請使用網頁右上角的「安全關閉」；網頁無法操作時可執行 `scripts/Stop Git Assessment.bat`。

預設網址：

```text
http://127.0.0.1:8765
```

可用環境變數：

| 變數 | 用途 |
|---|---|
| `GIT_ASSESSMENT_PORT` | 修改服務 port |
| `GIT_ASSESSMENT_NO_BROWSER=1` | 啟動後不自動開啟瀏覽器 |

Server 只綁定 `127.0.0.1`。程式會檢查 port、使用 single-instance lock 防止重複啟動，並將執行紀錄寫入 `runtime/logs/`。

## 4. 使用者流程

### 4.1 首頁與建立測驗

首頁顯示 Git、題目 templates、runtime 健康狀態，以及最近的本機測驗紀錄。

建立測驗流程：

1. 輸入姓名或識別代碼。
2. 系統建立安全且穩定的考生 ID。
3. 在 staging 產生六個獨立 repositories。
4. 完整驗證後安裝為新的 `current` workspace。
5. 建立結果 JSON 並進入任務總覽。

同一名稱會沿用相同考生身份；中文姓名不會互相碰撞，英文大小寫視為同一身份。

### 4.2 任務總覽與題目頁

任務狀態：

| 狀態 | 說明 |
|---|---|
| `not_started` | 尚未開啟或檢查 |
| `in_progress` | 已開啟或檢查，但未全部通過 |
| `completed` | 所有必要 checks 已通過 |

題目頁提供：

- 情境、步驟、限制與完成條件。
- Repository 絕對路徑。
- 「複製路徑」及「開啟資料夾」。
- 「檢查結果」及「重設本題」。
- 上一題、下一題及返回總覽。

「如何開始」會說明如何用 `cd`、檔案總管、CMD 或 VS Code 進入題目 repository。

### 4.3 檢查結果

按下「檢查結果」後：

1. 後端讀取 repository 狀態。
2. 執行題目設定的全部 checks。
3. 顯示每項通過或未通過。
4. 所有必要 checks 通過後將題目標記為完成。
5. 將最新狀態寫入結果 JSON。

若已完成的 repository 後來不再符合條件，再次檢查會將題目恢復為 `in_progress`。

### 4.4 重設與修復

重設只影響目前題目。系統先建立並驗證替代 repository，再交換正式資料；失敗時保留原 repository。

損壞的未完成題目可先移到 `runtime/quarantine` 再從 template 重建。已完成題目需要額外確認，避免直接清除考生答案。

Windows 若因 Terminal、VS Code 或檔案總管占用資料夾而無法交換，頁面會提示使用者先關閉占用程式。

### 4.5 續考與結果

- 關閉瀏覽器或程式不會刪除進度。
- 首頁可繼續最近未完成的測驗。
- 題目檔案、Git history、branch、stash 與 working tree 都會保留。
- 結果摘要顯示姓名、完成題數、每題狀態及檢查次數。
- 結果摘要可由瀏覽器保存成 PNG。

## 5. Workspace 與結果資料

### 5.1 考生與兩份紀錄

每位考生固定使用：

```text
runtime/workspaces/<candidate-id>/current/
runtime/workspaces/<candidate-id>/previous/
```

- `current`：最新測驗。
- `previous`：上一份測驗。
- 更舊的資料移到 `runtime/archive`，不顯示於首頁。

考生 ID 由正規化名稱、可讀 slug 與八碼 SHA-256 組成，例如：

```text
example-user-<8-char-hash>
candidate-<8-char-hash>
```

### 5.2 Session 與 repository 路徑

Session ID：

```text
YYYYMMDD-HHMMSS-<6-char-random-id>
```

新題目資料夾本身就是 Git repository：

```text
runtime/workspaces/<candidate-id>/current/task02
```

舊版的 `task02/repo` 路徑仍可讀取，以保留續考相容性。

### 5.3 建立與輪替安全

建立新測驗時：

1. 在 `.session-stage-*` 建立六題。
2. 驗證所有 repositories 與必要 refs。
3. 準備 transaction manifest。
4. 將原 `current` 移到 `previous`。
5. 將新 staging 安裝為 `current`。
6. 任一步驟失敗時回復原結果與 workspace。

同一考生、Session、Task 與重複 request 由程序內 `RLock` 保護；本系統不支援多個 Python 程序共用同一份 runtime。

### 5.4 結果 JSON

結果保存在：

```text
runtime/results/<session-id>.json
```

目前 schema version 為 3，主要欄位為：

```json
{
  "schema_version": 3,
  "session_id": "20260817-090000-a1b2c3",
  "candidate_id": "example-user-12345678",
  "candidate_key": "<sha256>",
  "candidate_name": "Example User",
  "slot": "current",
  "workspace": "workspaces/example-user-12345678/current",
  "started_at": "2026-08-17T09:00:00+08:00",
  "completed_at": null,
  "tasks": [],
  "events": []
}
```

Workspace 使用相對路徑，因此完整程式資料夾可搬到其他 Windows 電腦。Schema v2 或更早的絕對路徑會依目前 runtime 位置遷移，不會回連舊電腦或舊資料夾。

無效資料會移到 `runtime/quarantine`；被輪替的舊資料會移到 `runtime/archive`。

### 5.5 本機 remote

第四、五題以 workspace 內的 bare repository 模擬遠端，不連線至外部服務：

```text
runtime/workspaces/<candidate-id>/<slot>/.origins/task04.git
runtime/workspaces/<candidate-id>/<slot>/.origins/task05.git
```

舊版放在題目目錄內的 `origin.git` 仍受到相容支援。

## 6. 六道實作題目

### 6.1 Task 01：選擇性提交

初始狀態同時包含應提交的 `src/config.py`、不可提交的 `README.md`，以及 untracked 的 `debug.log`。

完成條件：

- 只新增一筆 commit。
- Commit message 為 `Fix configuration loading`。
- 最新 commit 包含 `src/config.py`，不包含 `debug.log`。
- `README.md` 保留為未提交修改。
- `debug.log` 保持 untracked。

主要能力：status、diff、staging、commit。

### 6.2 Task 02：Amend 最新 Commit

最新 commit 已包含程式修改，但缺少完成的 `tests/test_config.py`。

完成條件：

- 將測試檔加入原本 commit，不增加 commit 數量。
- Commit message 保持 `Fix configuration loading`。
- `HEAD` 中的測試內容包含指定 assertion。
- Working tree 乾淨。

主要能力：修改檔案、staging、`commit --amend`。

### 6.3 Task 03：建立工作分支

從 `main` 建立 `feature/login-timeout`，將 `LOGIN_TIMEOUT` 從 30 改為 60 並提交。

完成條件：

- 目前位於 `feature/login-timeout`。
- 修改已存在於 `HEAD`。
- `main` 不包含該修改。
- `main..HEAD` 只有一筆 commit。
- Working tree 乾淨。

主要能力：branch、switch／checkout、commit。

### 6.4 Task 04：Fetch、Rebase 與 Conflict

工作分支與假遠端 `main` 會修改同一段程式。受測者先用頁面按鈕建立遠端更新，再 fetch、rebase 並解決 conflict。

完成條件：

- 目前位於 `feature/login-timeout`。
- `origin/main` 是 `HEAD` 的祖先。
- 最終保留 `LOGIN_TIMEOUT = 60` 與 `LOGIN_RETRY = 5`。
- 沒有 merge commit。
- Working tree 乾淨且沒有未完成的 Git operation。

主要能力：fetch、rebase、conflict resolution。

### 6.5 Task 05：Stash 與遠端分支

受測者需要暫存 `notes/development.md` 草稿，取得遠端限定的 hotfix，查看後回到原分支並恢復草稿。

完成條件：

- 回到 `feature/login-timeout`。
- 草稿恢復為未提交修改且內容完整。
- 本機存在 `hotfix/check-status`，內容包含遠端修正。
- Stash 清空。
- Reflog 包含由 hotfix 切回工作分支的紀錄。

主要能力：stash、fetch、remote-tracking branch、switch／checkout。

### 6.6 Task 06：Cherry-pick 指定 Commit

從 `fix/validation` 找出修正 commit，並只將該 commit 套用到 `feature/login-timeout`。

完成條件：

- 目前位於 `feature/login-timeout`。
- `src/validator.py` 包含指定修正。
- 最新 commit message 為 `Reject empty validation values`。
- 只增加一筆 commit，且沒有合併整個來源分支。
- Working tree 乾淨且沒有未完成的 Git operation。

主要能力：log、cherry-pick。

## 7. 題目設定與自動檢查

### 7.1 題目設定

題目位於 `questions/questions.json`。每題包含：

- `id`、`order`、`title`、`description`。
- `instructions` 與 `constraints`。
- `repository_template`。
- 選用的 `copy_blocks`。
- 一組必要或選用的 `checks`。

簡化範例：

```json
{
  "id": "task02",
  "order": 2,
  "repository_template": "task02",
  "checks": [
    {
      "id": "message",
      "type": "commit_message",
      "expected": "Fix configuration loading",
      "label": "Commit message 保持不變"
    }
  ]
}
```

啟動時會驗證題目 ID、順序、必要 checks、check type 及檔案路徑。

### 7.2 檢查原則

- Git 指令以 argument array 執行，不使用 shell 字串拼接。
- 每個 Git 操作都有 timeout。
- 檢查只讀取狀態，不修改考生答案。
- 所有 `required` checks 通過才算完成。
- Git return code 只有在語意有效時才可判定通過。
- 檔案路徑不得跳脫題目 repository。

目前支援 18 種 check types：

| 類別 | Check types |
|---|---|
| 分支與 Commit | `current_branch`、`branch_exists`、`commit_message`、`commit_count` |
| 檔案內容 | `file_contains`、`file_at_revision_contains`、`file_at_revision_not_contains` |
| Commit 檔案 | `file_in_commit`、`file_not_in_commit` |
| Working tree | `working_tree_modified`、`working_tree_clean`、`untracked_file` |
| Git 狀態 | `stash_count`、`no_operation_in_progress`、`reflog_contains` |
| 歷史關係 | `is_ancestor`、`not_is_ancestor`、`no_merge_commit` |

## 8. Template 建立與版本

Templates 由 `app/template_builder.py` 建立於：

```text
data/templates/task01/
...
data/templates/task06/
```

目前 Template 版本為 7，完成標記為：

```text
data/templates/.ready-v7.json
```

Template v7 的每個一般與 bare repository 都設定：

```text
core.longpaths=true
```

這可避免 GitHub Windows runner 或較深安裝路徑因傳統 260 字元限制而將 Git objects 誤判為損壞。

一般啟動使用快速檢查；重建 template、新建 workspace 與完整測試會驗證 HEAD、tag、必要 refs、remote 及 `git fsck`。新 templates 在 staging 完整建立並驗證後才交換到正式位置。

修改初始 Git 狀態時必須：

1. 修改 `app/template_builder.py`。
2. 提升 `TemplateBuilder.VERSION`。
3. 重新啟動讓 templates 重建。
4. 執行完整測試。

Template 更新不會覆寫既有作答；考生需建立新測驗或重設該題。

## 9. 程式架構

| 模組 | 責任 |
|---|---|
| `run.py` | Single-instance、port、logger、server 生命週期 |
| `app/routes.py` | 頁面與 API |
| `app/services.py` | Session、workspace、結果、輪替、修復與遷移 |
| `app/git_tools.py` | 執行 Git 指令與 timeout |
| `app/check_engine.py` | 執行題目 checks |
| `app/template_builder.py` | 建立六題初始 repositories |
| `app/security.py` | 本機 Host、Origin 與 API token 防護 |
| `questions/questions.json` | 題目文字、限制與 checks |
| `app/static/app.js` | 複製、檢查、重設與資料夾操作 |

主要資料夾：

```text
app/                 Flask 程式與網頁
questions/           題目設定
data/templates/      產生的題目 templates
runtime/workspaces/  考生 repositories
runtime/results/     結果 JSON
runtime/archive/     輪替出的舊資料
runtime/quarantine/  異常資料與修復備份
runtime/logs/        執行紀錄
scripts/             本機啟動與輔助腳本
tests/               自動化測試
```

## 10. 頁面與 API

| Method | Endpoint | 用途 |
|---|---|---|
| `GET` | `/` | 首頁、環境狀態與續考 |
| `POST` | `/api/sessions` | 建立新測驗 |
| `POST` | `/api/sessions/<id>/delete` | 刪除測驗與 workspace |
| `GET` | `/assessment/<id>` | 任務總覽 |
| `GET` | `/assessment/<id>/tasks/<task>` | 題目頁 |
| `GET` | `/assessment/<id>/result` | 結果摘要與 PNG 保存 |
| `POST` | `/api/sessions/<id>/tasks/<task>/check` | 執行檢查 |
| `POST` | `/api/sessions/<id>/tasks/<task>/reset` | 重設題目 |
| `POST` | `/api/sessions/<id>/tasks/<task>/repair` | 備份並修復題目 |
| `POST` | `/api/sessions/<id>/tasks/<task>/open` | 開啟 repository 資料夾 |
| `POST` | `/api/sessions/<id>/tasks/<task>/remote-update` | 模擬第四題遠端更新 |
| `GET` | `/api/sessions/<id>/result` | 取得結果 JSON |
| `GET` | `/api/health` | 取得 runtime 健康狀態 |
| `POST` | `/api/shutdown` | 安全停止 server |

所有有副作用的請求都驗證本機 Host、Origin 與每次啟動產生的 token。瀏覽器操作使用 request ID 避免相同請求被重複執行。

錯誤回應依 `Accept` header 決定格式：一般表單顯示 HTML 錯誤頁，API 客戶端取得 JSON。

## 11. 安全、健康與錯誤處理

### 11.1 資料安全

- Session ID 與 workspace 路徑皆會驗證。
- Workspace 必須位於 `runtime/workspaces`。
- 不允許清理 workspace root 或 repository 外路徑。
- Git 指令不經 shell 字串執行。
- Template、重設與新 Session 都先 staging，再交換正式資料。
- 異常資料優先 quarantine，而不是直接永久刪除。
- 專案不讀取或保存 Git credential。
- `.env`、金鑰、個人工具設定、runtime 與產生的 templates 都由 `.gitignore` 排除。

### 11.2 健康檢查層級

- 啟動與首頁：快速檢查結果 schema、workspace 與 `.git` 結構。
- 任務總覽：以 `git rev-parse` 確認 repository 可辨識。
- Template 重建、新 workspace 與正式測試：執行必要 refs 驗證及 `git fsck`。

快速啟動不會對每一份既有 workspace 執行完整 `git fsck`，避免啟動時間隨歷史資料增加。

### 11.3 常見錯誤

| 情況 | 系統行為 |
|---|---|
| Git 未安裝 | 首頁顯示錯誤並禁止建立測驗 |
| Template 無法建立 | 保留舊 template，首頁顯示未就緒 |
| Repository 損壞 | 顯示健康問題，可備份後修復 |
| Git operation 未完成 | 檢查不通過並提示完成或取消操作 |
| Git 指令逾時 | 終止指令並回傳錯誤 |
| Workspace 被占用 | 保留原資料並提示關閉占用程式 |
| 結果格式錯誤 | 隔離到 quarantine，不載入首頁 |

## 12. 自動化測試

執行方式：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

目前共有 24 個測試，主要涵蓋：

- 首頁、總覽、題目頁與結果摘要。
- 六題初始狀態與標準解答。
- 題目判定繞過與 Git revision 錯誤。
- Reset、repair、workspace staging 與失敗回復。
- 考生 ID、兩份紀錄輪替與舊 schema 遷移。
- 本機 remote、fetch、remote-only branch 與長路徑。
- API token、request idempotency、安全關閉。
- HTML 表單錯誤與 JSON API 錯誤的內容協商。
- 整包 runtime 搬移後的相對路徑與 remote 修正。

完整測試會建立並操作真實 Git repositories，因此比一般單元測試耗時。

## 13. CI/CD

Workflow 位於 `.github/workflows/ci-cd.yml`，在 `windows-latest` 與 Python 3.11 執行。

### 13.1 CI 觸發方式

- 對 `main` 建立或更新 Pull Request。
- Push 或 merge 到 `main`。
- 手動執行 `workflow_dispatch`。
- Push `v*` tag。

單純 push feature branch 不會執行 CI；建立 Pull Request 後才會執行。

CI 步驟：

1. Checkout repository。
2. 安裝 `requirements/requirements-dev.txt`。
3. 執行 `python -m pytest -q`。

### 13.2 CD／Release

推送 `v*` tag 後，release job 會等待 test job 通過，再：

1. 使用 `git archive` 建立 ZIP。
2. 建立對應的 GitHub Release。
3. 附加 ZIP 與自動產生的 release notes。

目前 CD 是「發布可下載 ZIP」，不是部署線上網站。Release 不包含測試、規格、GitHub workflow、runtime 或產生的 templates。

建議以 Pull Request 合併功能，確認 `main` 通過後再手動建立版本 tag。

## 14. 維護規則

| 修改內容 | 主要檔案 | 額外動作 |
|---|---|---|
| 題目文字 | `questions/questions.json` | 重新啟動即可 |
| 完成條件 | `questions/questions.json` | 執行對應測試 |
| 新 check type | `check_engine.py`、`services.py` | 新增測試 |
| 題目初始狀態 | `template_builder.py` | 提升 Template 版本並重建 |
| 頁面 | `app/templates/` | 檢查相關頁面 |
| 前端互動 | `app/static/app.js` | 執行相關流程 |
| Session／資料 | `app/services.py` | 執行完整測試與搬移測試 |

正式發布前至少應：

1. 執行完整 pytest。
2. 建立一份新測驗。
3. 確認檢查、重設、續考與輪替。
4. 確認 `git status` 沒有 runtime、credential 或個人設定。
5. 透過 Pull Request 合併並等待 CI 通過。
6. 建立 `v*` tag 觸發 Release。

## 15. 目前限制

- 只支援單機 Windows。
- 第一次安裝需要可取得 Python 套件，或預先準備 `.venv`。
- 沒有考官密碼、限時、集中成績或權限管理。
- 操作鎖只保護單一 Python 程序。
- 首頁最多顯示最近 8 筆紀錄。
- `archive` 與 `quarantine` 由管理者自行決定保留期限。
- 系統依最終 Git 狀態判定，不保證能證明受測者輸入過指定指令。
- 完整測試因使用真實 repositories，執行時間較長。

## 16. 版本摘要

### 1.2

- 完成可攜式 workspace、schema v3、兩份紀錄交易與異常資料隔離。
- 加入考生 ID 防碰撞、操作鎖、API token、Host／Origin 驗證。
- 加入 template 完整性、runtime 健康檢查、安全修復與安全關閉。
- 補強第二、四、五、六題判定與測試。

### 1.3

- Template 升級為 v7，所有 Git repositories 啟用 Windows long paths。
- 新增 GitHub Actions CI 與以 `v*` tag 發布 GitHub Release 的流程。
- HTML 表單與 JSON API 依 `Accept` header 回傳合適的錯誤格式。
- 自動化測試增加為 24 個。
- 移除已修復問題的重複稽核全文，使本文件只描述目前行為。
