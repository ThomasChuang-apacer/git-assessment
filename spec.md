# Git 實作考試系統規格書

文件版本：1.2  
文件狀態：Current Implementation + Improvements Implemented  
更新日期：2026-08-04  
適用程式：`C:\path\to\git-assessment`

## 1. 文件目的

本文件描述 Git 實作考試系統目前已完成並實際運作的功能、畫面、資料保存方式、六道題目、自動檢查規則、技術架構及測試範圍。

本文件以桌面版本的現況為準，不再描述已淘汰的長 Session workspace 命名方式。若文件與程式不一致，應同步檢查下列實際來源：

- 題目文字及判定：`questions/questions.json`
- Git 初始環境：`app/template_builder.py`
- 自動檢查器：`app/check_engine.py`
- Session 與 workspace 管理：`app/services.py`
- 頁面及 API：`app/routes.py`

## 2. 產品定位

這是一套在 Windows 本機執行的 Git 實作測驗系統。

受測者會在真實的 Git repository 中，使用 Terminal、PowerShell 或 VS Code 操作 Git，再回到瀏覽器按下「檢查結果」。系統依照 repository 的最終狀態判定是否完成，不要求受測者在網頁輸入指令或文字答案。

### 2.1 主要目標

- 使用真實 Git repository 進行實作測驗。
- 涵蓋日常常見的 Git 操作。
- 每題完成後可立即檢查並打勾。
- 每題使用獨立 repository，避免前一題影響下一題。
- 支援中途關閉及下次續考。
- 每位考生最多保存兩份測驗。
- 題目、初始 Git history 與檢查條件可維護及擴充。
- 所有題目可在沒有公司 Git、Gerrit 或網際網路的情況下執行。

### 2.2 非目標

目前版本不包含：

- 網頁內嵌 Terminal。
- 自動計分、排名或及格門檻。
- 逐條記錄受測者執行過的 Git 指令。
- 帳號、密碼或權限管理。
- 多台電腦共用的中央伺服器。
- 雲端部署。
- 與正式 Gerrit、GitHub 或公司 repository 連線。
- 防作弊或螢幕錄影。
- Linux 或 macOS 正式支援。

## 3. 執行環境

### 3.1 支援環境

- Windows 10 或 Windows 11。
- Python 3.11 或更新版本。
- Git for Windows。
- Microsoft Edge 或 Google Chrome。

### 3.2 啟動方式

受測者或考官雙擊（預設，不顯示 CMD）：

```text
Start Git Assessment.vbs
```

需要查看即時錯誤時可改用 `start.bat`。正常使用時可在任一網頁右上角按「安全關閉 Git Assessment」；確認後伺服器會結束受控服務迴圈、清理 PID 與 lock，並顯示精簡完成畫面。「Stop Git Assessment.bat」保留為網頁無法操作時的備用停止方式。程式會寫入 rotating log、檢查 port，並以 lock 防止重複啟動。

第一次啟動時：

1. 建立專案專用 `.venv`。
2. 安裝 `requirements.txt` 中的 Flask。
3. 建立六題離線 Git templates。
4. 啟動本機 Web Server。
5. 自動開啟瀏覽器。

若 `.venv` 不存在，`Start Git Assessment.vbs` 會顯示第一次啟動進度視窗，以持續跑動的進度條及階段文字呈現「建立 Python 環境」、「安裝 Flask」與「啟動 Git Assessment」。安裝完成且本機 port 已就緒後，視窗會自動關閉；後續啟動不顯示此視窗。

預設網址：

```text
http://127.0.0.1:8765
```

環境變數：

| 變數 | 用途 |
|---|---|
| `GIT_ASSESSMENT_PORT` | 修改本機服務 port |
| `GIT_ASSESSMENT_NO_BROWSER=1` | 啟動後不自動開啟瀏覽器 |

Server 只綁定 `127.0.0.1`，不對區域網路公開。

## 4. 使用者流程

### 4.1 首頁

首頁顯示：

- Git 安裝狀態及版本。
- 六題 template 是否已就緒。
- 姓名或識別代碼輸入欄位。
- 「建立新測驗」按鈕。
- 最近一份未完成測驗的「繼續上次測驗」入口。
- 最近的本機測驗清單。
- 每份測驗的完成題數及是否完成。

首頁最多顯示最近 8 筆本機紀錄。若結果 JSON 存在但對應 workspace 不存在，該筆紀錄不允許續考。

### 4.2 建立新測驗

1. 受測者輸入姓名或識別代碼。
2. 系統將名稱轉成安全的資料夾名稱，例如 `Example User` 轉成 `Example-User`。
3. 系統執行該考生的兩份紀錄輪替。
4. 系統由 templates 建立六個獨立 repositories。
5. 系統建立新的結果 JSON。
6. 瀏覽器進入任務總覽。

任務總覽標題區及每一題標題旁均提供「如何開始」按鈕。點擊後以共用 modal 說明三種進入題目 repository 的方式：複製地址後使用 `cd`、開啟資料夾後在檔案總管網址列輸入 `cmd`、以及透過 VS Code「開啟資料夾」或 `code .` 操作。此功能不修改各題既有的地址、複製及開啟資料夾區塊。

### 4.3 任務總覽

任務總覽顯示：

- 受測者名稱。
- 開始時間。
- 已完成題數，例如 `2 / 6`。
- 每題的狀態。
- 進入各題的入口。
- 結果 JSON 查看入口。

題目狀態：

| 狀態 | 說明 |
|---|---|
| `not_started` | 尚未開啟或檢查 |
| `in_progress` | 已開啟或檢查，但尚未全部通過 |
| `completed` | 所有必要條件均已通過 |

### 4.4 題目頁

每個題目頁顯示：

- 題號及題目名稱。
- 情境說明。
- 任務要求。
- 操作限制。
- Repository 絕對路徑。
- 「複製路徑」按鈕。
- 「開啟資料夾」按鈕。
- 完成條件清單。
- 「檢查結果」按鈕。
- 「重設本題」按鈕。
- 上一題、下一題及返回總覽導覽。

題目可以使用 `copy_blocks` 顯示可直接複製的程式碼。第二題目前會顯示完整 Python 預期內容及「複製程式碼」按鈕。

### 4.5 檢查結果

受測者按下「檢查結果」後：

1. 後端讀取目前 repository 狀態。
2. 執行題目設定中的全部 checks。
3. 每項顯示 `✓` 或 `✗`。
4. 顯示不洩漏標準 Git 指令的狀態訊息。
5. 所有必要 checks 通過後，題目標示為完成。
6. 結果寫入 JSON。

若已完成的 repository 後來被修改而不再符合條件，再次檢查時題目會回到 `in_progress`。

### 4.6 重設本題

受測者按下「重設本題」後會看到確認訊息。確認後，系統採用安全交換流程：

1. 先在同一個 workspace 建立完整的替代 repository。
2. 確認替代 repository 包含有效 `.git`。
3. 將原題目以同磁碟原子 rename 移到暫時備份。
4. 將完整替代 repository 放到正式位置。
5. 確認成功後才清除備份。

完成後：

- 只刪除目前題目的 repository。
- 由 template 重新建立該題。
- 清除該題的完成狀態、檢查次數及檢查結果。
- 不影響其他題目。
- 保留 `task_reset` 事件紀錄。

Windows 的 Git object 可能具有唯讀屬性，系統已支援唯讀檔案的安全清理。

若題目資料夾正被 Terminal、VS Code 或其他程式占用，Windows 可能拒絕 rename。此時重設會停止並保留原 repository，不會再出現先刪除 `.git`、後續重建失敗的半完成狀態；頁面會提示受測者先離開該資料夾並關閉占用程式後重試。

### 4.7 中途關閉及續考

- 關閉瀏覽器或程式不會刪除 workspace。
- 任一頁右上角提供「安全關閉 Git Assessment」；確認後顯示「關閉 Git Assessment」與「測驗進度已保存，現在可以關閉此頁。」
- 安全關閉會停止受控 Web Server，並由啟動流程正常清理 PID 與 single-instance lock。
- 下次啟動時，首頁會讀取 `runtime/results`。
- 可從「繼續上次測驗」或「最近的測驗」返回原 Session。
- 題目檔案、Git history、branch、stash 及 working tree 狀態會保留。
- 完整程式資料夾停止後可壓縮並搬到其他 Windows 電腦；解壓縮後會以新位置續考。

## 5. Workspace 與紀錄保存規則

### 5.1 每位考生最多兩份

每位考生固定使用兩個槽位：

```text
runtime/workspaces/<candidate>/current/
runtime/workspaces/<candidate>/previous/
```

定義：

- `current`：最新建立的測驗，也是首頁優先續考的紀錄。
- `previous`：建立新測驗前的上一份紀錄。

建立新測驗時：

1. 在 `.session-stage-*` 建立完整的六題 workspace。
2. 驗證各題 repository 及 `git fsck`。
3. 寫入 transaction manifest。
4. 將更舊的 `previous` 移到 `runtime/archive`。
5. 將原本的 `current` 原子移到 `previous`。
6. 將 staging 原子安裝成新的 `current` 並寫入結果。
7. 任一步驟失敗時回復原本結果與 workspace。

因此每位考生最多只有兩份有效測驗紀錄。

### 5.2 Session ID

新 Session ID 格式：

```text
YYYYMMDD-HHMMSS-<6-char-random-id>
```

考生名稱不再放入 Session ID，因此不會在 workspace 路徑重複出現。

### 5.3 新版 repository 路徑

新建立題目的路徑：

```text
runtime/workspaces/Example-User/current/task02
```

`task01` 至 `task06` 資料夾本身就是 Git repository，不再額外加入 `repo` 子資料夾。

為了讓舊測驗仍能續考，系統也相容舊路徑：

```text
runtime/workspaces/Example-User/current/task02/repo
```

### 5.4 啟動時正規化

系統啟動時會：

- 將現有紀錄整理成 `current` 與 `previous`。
- 每位考生只保留最新兩筆有效紀錄。
- 將結果 JSON 的 workspace 更新為相對於 `runtime` 的可攜式路徑。
- 修正本機模擬 remote 的絕對路徑。
- 清理無法對應有效 workspace 的結果索引。

Windows 上的 workspace 搬移採用「完整複製後清理來源」方式，避免唯讀 Git objects 造成失敗。

結果 schema version 3 不再保存舊電腦的 `C:\...` workspace。若讀到 schema version 2 或更早的絕對路徑，系統會根據 `candidate_id` 與 `slot` 重新定位目前程式包內的 `runtime/workspaces/<candidate>/<slot>`。即使原始資料夾仍存在，複製後的程式也不會回連原位置。

整包搬移前必須先停止程式，並保留 `runtime/results` 與 `runtime/workspaces`。目的端必須先完整解壓縮，不能直接從 ZIP 預覽執行。

### 5.5 本機 remote

第四題需要 `origin/main`。系統使用受測者 Session 內的本機 bare repository 模擬 origin，不會連線到外部網路。

新版位置：

```text
runtime/workspaces/<candidate>/<slot>/.origins/task04.git
```

舊版 Session 的 `task04/origin.git` 仍受到相容支援。

## 6. 結果資料

結果保存在：

```text
runtime/results/<session-id>.json
```

主要欄位：

```json
{
  "schema_version": 3,
  "session_id": "20260804-090000-a1b2c3",
  "candidate_id": "Example-User",
  "candidate_name": "Example User",
  "slot": "current",
  "workspace": "workspaces/Example-User/current",
  "started_at": "2026-08-04T09:00:00+08:00",
  "completed_at": null,
  "tasks": [],
  "events": []
}
```

每題保存：

- `task_id`
- `status`
- `completed_at`
- `check_attempts`
- `last_checks`

事件包含：

- `session_started`
- `task_opened`
- `task_checked`
- `task_reset`

系統不保存受測者逐條輸入過的 Git 指令。

## 7. 六道實作題目

### 7.1 任務一：提交指定的修改

初始狀態：

- `src/config.py` 已修改，應提交。
- `README.md` 已修改，但不能提交。
- `debug.log` 是 untracked 檔案，不能提交或刪除。
- 目前 branch 為 `main`。

要求：

- 只提交 `src/config.py`。
- Commit message：`Fix configuration loading`。
- `README.md` 保留為未提交修改。
- `debug.log` 保持 untracked。
- 只新增一筆 commit。

自動檢查：

- 最新 commit message 正確。
- 最新 commit 包含 `src/config.py`。
- `README.md` 仍在 working tree。
- `debug.log` 仍為 untracked。
- `debug.log` 未包含於最新 commit。
- `assessment-start..HEAD` 的 commit 數量為 1。

主要能力：`status`、`diff`、選擇性 staging、commit。

### 7.2 任務二：補充最新的 Commit

初始狀態：

- `src/config.py` 已在最新 commit 中改成 production path。
- `tests/test_config.py` 仍是未完成的舊版本。
- `assessment-start..HEAD` 已有一筆 commit。

頁面提供可直接複製的預期內容：

```python
from src.config import CONFIG_PATH


def test_config_path():
    assert CONFIG_PATH == "config/production.json"
```

要求：

- 將測試檔加入原本最新 commit。
- Commit message 保持 `Fix configuration loading`。
- 不可增加額外 commit。

自動檢查：

- Commit message 保持不變。
- 最新 commit 包含 `src/config.py`。
- 最新 commit 包含 `tests/test_config.py`。
- 測試檔包含指定 assertion。
- `assessment-start..HEAD` 的 commit 數量仍為 1。

主要能力：修改檔案、staging、amend。

`tests/__pycache__` 已從 template 及既有題目副本清除，不應作為初始 untracked 檔案出現。

### 7.3 任務三：建立工作分支

初始狀態：

- 目前 branch 為 `main`。
- `LOGIN_TIMEOUT = 30`。
- `assessment-start` 位於初始 commit。

要求：

- 建立並切換到 `feature/login-timeout`。
- 將 `LOGIN_TIMEOUT` 改成 60。
- Commit message：`Update login timeout`。
- `main` 不可包含此修改。
- Working tree 必須乾淨。

自動檢查：

- 目前位於指定工作分支。
- `HEAD:src/login.py` 確實包含 `LOGIN_TIMEOUT = 60`。
- 最新 commit message 正確。
- `main:src/login.py` 不包含 timeout 60 修改。
- `main..HEAD` 只有一筆 commit。
- Working tree 乾淨。

此題已補強，不能只建立空 commit 後在 working tree 修改 timeout 來通過。

主要能力：branch、switch／checkout、commit。

### 7.4 任務四：更新分支並處理 Conflict

初始狀態：

- 目前位於 `feature/login-timeout`。
- 工作分支將 timeout 改成 60、retry 保持 3。
- 初始的本機 `origin/main` 與假遠端 `main` 都仍指向舊版。
- 假遠端另保存一筆待發布更新，內容將 timeout 改成 45、retry 改成 5。
- 兩個 branch 修改同一段檔案，rebase 時會產生 conflict。

要求：

- 確認目前位於 `feature/login-timeout`。
- 按下題目頁的「模擬遠端 main 更新」，將待發布 commit 寫入假遠端的 `main`。
- 題目只提示「遠端資料更新後，要先 fetch 最新資訊」，不直接提供完整指令；取得資訊後 `origin/main` 才會由舊 commit 前進到新 commit。
- 將目前工作分支 rebase 到最新 `origin/main`。
- 最終保留 `LOGIN_TIMEOUT = 60`。
- 保留 `origin/main` 的最新修改，最終 `LOGIN_RETRY` 必須等於 `5`。
- 不可使用 merge commit。
- Rebase 必須完整結束。

自動檢查：

- 目前位於 `feature/login-timeout`。
- `origin/main` 是 `HEAD` 的祖先。
- 最終檔案包含 timeout 60。
- 最終檔案包含 retry 5。
- `origin/main..HEAD` 沒有 merge commit。
- Working tree 乾淨。
- 沒有進行中的 rebase、merge 或 cherry-pick。

主要能力：fetch、rebase、conflict resolution。

Template v3 起採用真正的 stale remote-tracking 情境。既有 v2 workspace 不會自動覆寫；題目頁會保留原作答並提示考生使用「重設本題」後套用新版。

### 7.5 任務五：暫時保存未完成的修改

初始狀態：

- 目前位於 `feature/login-timeout`。
- `notes/development.md` 有未提交草稿。
- 假遠端有 `hotfix/check-status`，內容包含 `STATUS = "healthy"` 最新修正。
- 本機沒有 `hotfix/check-status`，也尚未取得 `origin/hotfix/check-status`。

要求：

- 不建立 commit，暫時保存目前修改。
- 取得假遠端 `origin` 的最新分支資訊。
- 從 `origin/hotfix/check-status` 建立並切換本機追蹤分支，可使用 `switch` 或 `checkout`。
- 確認 hotfix 最新修正，不需自行修改該分支檔案。
- 切回 `feature/login-timeout`。
- 恢復原本草稿。
- 執行 `git stash list`，確認完全沒有顯示任何 stash 紀錄。

自動檢查：

- 已回到 `feature/login-timeout`。
- `notes/development.md` 保留為未提交修改。
- 草稿內容完整存在。
- 本機 `hotfix/check-status` 已建立。
- `hotfix/check-status` 包含假遠端的 `STATUS = "healthy"` 修正。
- Stash 數量為 0。
- Reflog 包含由 hotfix 分支切回工作分支的紀錄。

主要能力：stash、fetch、從 remote-tracking branch 建立本機追蹤分支、switch／checkout、stash pop／apply 與清理。

Template v5 起將 task05 的 hotfix 設為遠端限定分支。既有 v4 或更早 workspace 不會自動覆寫；題目頁會保留原作答並提示使用「重設本題」套用新版。

### 7.6 任務六：套用指定的修正

初始狀態：

- 目前位於 `feature/login-timeout`。
- `fix/validation` 比 `assessment-start` 多一筆驗證修正。
- 目前工作分支尚未包含該修正。

要求：

- 找出 `fix/validation` 最新 commit。
- 只將該筆 commit 套用到目前工作分支。
- 不可合併整個來源分支。
- 完成後 working tree 必須乾淨。

自動檢查：

- 目前位於 `feature/login-timeout`。
- `src/validator.py` 包含空字串驗證修正。
- 最新 commit message 為 `Reject empty validation values`。
- `assessment-start..HEAD` 只增加一筆 commit。
- `fix/validation` 本身不是 `HEAD` 的祖先，排除整分支 merge。
- Working tree 乾淨。
- 沒有未完成的 cherry-pick、merge 或 rebase。

主要能力：log、cherry-pick。

## 8. 題目設定格式

題目設定檔：

```text
questions/questions.json
```

目前 schema：

```json
{
  "id": "task02",
  "order": 2,
  "title": "補充最新的 Commit",
  "description": "題目情境",
  "instructions": ["任務要求"],
  "copy_blocks": [
    {
      "title": "可複製內容標題",
      "language": "python",
      "content": "完整程式碼"
    }
  ],
  "constraints": ["限制"],
  "repository_template": "task02",
  "checks": [
    {
      "id": "message",
      "type": "commit_message",
      "expected": "Fix configuration loading",
      "label": "Commit message 保持不變",
      "required": true
    }
  ]
}
```

`copy_blocks` 為選填。未提供時題目頁不顯示程式碼複製區塊。

### 8.1 啟動驗證

啟動時會檢查：

- 題目 `id` 不重複。
- 題目 `order` 不重複。
- 每題至少有一個必要 check。
- Check type 必須受到支援。
- 題目檔案路徑不得為絕對路徑或包含 `..`。

## 9. 自動檢查器

### 9.1 執行原則

- 使用 argument array 呼叫 Git，不使用 `shell=True`。
- 檢查具有 timeout。
- 檢查只讀取狀態，不自動修正考生答案。
- 題目是否完成取決於全部 `required` checks。
- 錯誤訊息描述狀態，不直接顯示正確 Git 指令。
- 保留 `git status --porcelain` 的前置空白，以正確解析 X/Y status 欄位。

### 9.2 目前支援的 Check Types

| Check type | 用途 |
|---|---|
| `current_branch` | 檢查目前 branch |
| `branch_exists` | 檢查本地 branch 是否存在 |
| `commit_message` | 檢查最新或指定 revision 的 commit message |
| `commit_count` | 檢查 revision range 的 commit 數量 |
| `file_contains` | 檢查 working tree 檔案內容 |
| `file_at_revision_contains` | 檢查指定 revision 中的檔案內容 |
| `file_at_revision_not_contains` | 確認指定 revision 不包含某內容 |
| `file_in_commit` | 檢查指定檔案存在於 commit diff |
| `file_not_in_commit` | 確認指定檔案不在 commit diff |
| `working_tree_modified` | 檢查 tracked 檔案保留為未提交修改 |
| `working_tree_clean` | 檢查 working tree 無修改及 untracked 檔案 |
| `untracked_file` | 檢查指定 untracked 檔案 |
| `stash_count` | 檢查 stash 筆數 |
| `no_operation_in_progress` | 檢查沒有 rebase、merge 或 cherry-pick 進行中 |
| `is_ancestor` | 檢查 Git ancestor 關係 |
| `not_is_ancestor` | 確認 Git ancestor 關係不存在 |
| `no_merge_commit` | 檢查指定 range 沒有 merge commit |
| `reflog_contains` | 檢查 reflog 操作紀錄 |

### 9.3 檔案路徑安全

檔案內容檢查會解析絕對路徑，並確認檔案仍位於該題 repository 中。題目設定不能藉由路徑跳脫讀取 repository 外的檔案。

## 10. Template 建立與維護

Templates 由以下程式建立：

```text
app/template_builder.py
```

產生位置：

```text
data/templates/task01/
...
data/templates/task06/
```

建立完成後寫入 manifest：

```text
data/templates/.ready-v6.json
```

一般啟動採快速檢查，確認 manifest、六題 `.git` 與第四、五題本機 origin 結構；template 重建時仍會驗證 HEAD、`assessment-start`、必要 branch／remote 及 `git fsck`，成功後才交換正式 templates。完整 `git fsck` 也保留於新測驗 workspace 建立及正式測試流程。

修改 template builder 後，維護者必須：

1. 關閉考試程式。
2. 提升 `TemplateBuilder.VERSION`。
3. 重新啟動，讓 templates 交易式重建。
4. 執行完整測試。

注意：修改 templates 不會自動修改既有 `current` 或 `previous` workspace。若要套用新版題目初始狀態，應建立新測驗或重設該題。

## 11. API 與頁面路由

| Method | Endpoint | 用途 |
|---|---|---|
| `GET` | `/` | 首頁、環境狀態、續考與最近測驗 |
| `POST` | `/api/sessions` | 建立新測驗及執行兩份紀錄輪替 |
| `POST` | `/api/sessions/<session_id>/delete` | 永久刪除指定結果與對應 workspace，並整理剩餘 slot |
| `GET` | `/assessment/<session_id>` | 任務總覽 |
| `GET` | `/assessment/<session_id>/result` | 可閱讀的結果摘要與 PNG 保存頁 |
| `GET` | `/assessment/<session_id>/tasks/<task_id>` | 題目頁 |
| `POST` | `/api/sessions/<session_id>/tasks/<task_id>/check` | 執行自動檢查 |
| `POST` | `/api/sessions/<session_id>/tasks/<task_id>/reset` | 重設單題 |
| `POST` | `/api/sessions/<session_id>/tasks/<task_id>/open` | Windows 開啟 repository 資料夾 |
| `POST` | `/api/sessions/<session_id>/tasks/<task_id>/remote-update` | 第四題模擬另一位開發者更新假遠端 main |
| `POST` | `/api/sessions/<session_id>/tasks/<task_id>/repair` | 備份並修復損壞題目 |
| `POST` | `/api/shutdown` | 安全停止本機 Web Server；進度保留於 runtime |
| `GET` | `/api/sessions/<session_id>/result` | 取得結果 JSON |
| `GET` | `/api/health` | 取得 runtime 健康狀態 |

所有 POST 都驗證本機 Host、Origin 與每次啟動隨機產生的 API token；瀏覽器操作另帶 request ID 避免重複執行。

## 12. 程式架構

```text
git-assessment/
├── app/
│   ├── __init__.py
│   ├── routes.py
│   ├── services.py
│   ├── git_tools.py
│   ├── check_engine.py
│   ├── security.py
│   ├── template_builder.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── home.html
│   │   ├── overview.html
│   │   ├── result.html
│   │   ├── task.html
│   │   └── error.html
│   └── static/
│       ├── app.js
│       └── styles.css
├── questions/
│   └── questions.json
├── data/
│   └── templates/
├── runtime/
│   ├── workspaces/
│   ├── results/
│   ├── archive/
│   ├── quarantine/
│   └── logs/
├── tests/
│   └── test_exam_flow.py
├── run.py
├── start.bat
├── Start Git Assessment.vbs
├── Stop Git Assessment.bat
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── README.md
└── spec.md
```

主要責任：

| 模組 | 責任 |
|---|---|
| `routes.py` | 頁面與 API |
| `services.py` | Session、workspace、結果、續考、輪替及重設 |
| `git_tools.py` | 安全執行 Git 指令及 timeout |
| `check_engine.py` | 解析及執行 checks |
| `template_builder.py` | 建立六題初始 repositories |
| `questions.json` | 題目文字、限制、可複製內容及 checks |
| `app.js` | 複製、檢查、重設及開啟資料夾互動 |

## 13. 安全與資料保護

- 僅接受系統建立的 Session ID。
- Session ID 只允許英數、點、底線及連字號。
- Workspace 必須位於 `runtime/workspaces` 內。
- 重設及清理前會解析並驗證實際路徑。
- 不允許刪除 workspace root。
- Git 指令不使用 shell 字串拼接。
- 題目檔案路徑不可跳脫 repository。
- 重設具有前端確認訊息。
- 每位考生第三份測驗會依規則移除最舊紀錄。
- 不保存 Git credential。
- 不連線至正式遠端服務。
- HTML 內容由 Jinja escaping，程式碼 block 也不直接插入未轉義 HTML。

## 14. 錯誤處理

### Git 未安裝

首頁顯示找不到 Git，且不可建立測驗。

### Template 建立失敗

首頁顯示題目環境未就緒，且不可建立測驗。

### Repository 不存在或損壞

題目頁或 API 顯示 repository 無法讀取，不執行自動修復。

### Git 操作尚未完成

若 rebase、merge 或 cherry-pick 尚未完成，檢查顯示目前 Git 操作未結束。

### Git 檢查逾時

終止 Git process、回傳逾時訊息，且題目不標示完成。

### 結果與 Workspace 不一致

啟動整理時會移除無法對應有效 workspace 的結果索引。首頁只允許可用 workspace 續考。

## 15. 自動化測試

執行方式：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

目前共有 21 組測試，除原有流程外新增：

1. 首頁、任務總覽及題目頁可正常載入。
2. 首頁會列出可續考紀錄。
3. 第二題顯示可複製的預期 Python 程式碼。
4. 六題初始狀態都不會誤判為完成。
5. 第一題新增超過一筆 commit 時不得通過。
6. 第三題只在 working tree 修改 timeout、未提交時不得通過。
7. 六題參考解全部可以通過。
8. 重設單題不影響其他題目。
9. 同一考生建立三次測驗後，只保留 `current` 與 `previous`。
10. Repository 被占用而無法交換時，重設不得破壞原 repository。

- 中文姓名碰撞與英文大小寫身份。
- 本機 API token 與相同 request ID 去重。
- 第二題 working tree 繞過。
- 第六題來源 branch 不存在時的 Git 錯誤。
- 新 Session 複製失敗時保留 current。
- 未完成損壞題目先隔離再修復。
- 整包 runtime 搬到不同根目錄後，舊絕對路徑會遷移為相對路徑，且本機 origin 會改指向新位置。
- 第四題假遠端更新後，本機 `origin/main` 必須等到 fetch 才前進。
- 第五題必須先取得遠端限定 hotfix，再以 switch 或 checkout 建立本機追蹤分支，並將 stash 清空。
- 結果摘要頁可顯示姓名、各題狀態及 PNG 保存按鈕。
- 安全關閉 API 會拒絕未帶 token 的請求，合法請求則呼叫註冊的伺服器關閉程序。

## 16. 驗收條件

- [x] Windows 本機可以啟動 Web Application。
- [x] 系統可偵測 Git 是否可用。
- [x] 可輸入姓名建立新測驗。
- [x] 每次測驗建立六個獨立 repositories。
- [x] 首頁顯示最近測驗與續考入口。
- [x] 首頁可經明確確認後永久刪除指定測驗紀錄與 workspace。
- [x] 中途關閉後可恢復 Git workspace 狀態。
- [x] 任一網頁可按「安全關閉 Git Assessment」正常停止伺服器並保留進度。
- [x] 每位考生最多保留兩份紀錄。
- [x] 考生姓名在 workspace 路徑只出現一次。
- [x] 新題目資料夾本身就是 Git repository。
- [x] 題目頁可複製路徑及開啟資料夾。
- [x] 第二題可直接複製預期 Python 內容。
- [x] 每項完成條件顯示通過或未通過。
- [x] 全部必要條件通過後自動打勾。
- [x] 已完成題目變得不符合條件時會撤回完成狀態。
- [x] 可獨立重設單題。
- [x] 第四題使用本機 origin 模擬 rebase conflict。
- [x] 系統不記錄逐條 Git 指令。
- [x] 六題可以離線操作。
- [x] 21 組自動化測試全部通過。
- [x] 完整程式包搬到不同路徑後可讀取既有紀錄並續考。

## 17. 已完成的重要調整

相較最初版本，目前已完成：

1. 新增首頁「繼續上次測驗」。
2. 新增最近測驗清單及完成進度。
3. 將 workspace 從長 Session 路徑改為 `<candidate>/current` 與 `<candidate>/previous`。
4. 每位考生最多保留兩份測驗。
5. Session ID 不再包含考生名稱。
6. 新建立的 task 資料夾直接作為 Git repository。
7. 保留舊版 `taskXX/repo` 路徑相容性。
8. 支援 Windows 唯讀 Git object 的 workspace 搬移及重設。
9. 修正搬移後本機 origin URL。
10. 第二題加入完整預期 Python 程式碼及複製按鈕。
11. 清除第二題 `tests/__pycache__` 暫存資料。
12. 第一題增加只允許一筆新 commit 的判定。
13. 第三題改為檢查修改是否真正存在於 `HEAD`。
14. 第三題增加 working tree 必須乾淨的判定。
15. 第四題文字明確要求 rebase。
16. 第五題文字明確說明 hotfix 分支不需修改檔案。
17. 自動化測試增加到 9 組。
18. 重設改為先建立完整替代 repository，再進行安全交換。
19. Repository 被占用時保留原內容並顯示可操作的錯誤訊息。
20. 自動化測試增加到 10 組。

## 18. 維護規則

### 只修改題目文字

修改：

```text
questions/questions.json
```

重新啟動程式即可，不需重建 templates。

### 修改完成條件

修改 `questions/questions.json` 的 `checks`。若需要新的 check type，還必須同步修改：

- `app/check_engine.py`
- `app/services.py` 的支援清單
- `tests/test_exam_flow.py`

### 修改題目初始 Git 狀態

修改：

```text
app/template_builder.py
```

然後重建 `data/templates` 並執行完整測試。

### 修改畫面文字或版面

- 首頁：`app/templates/home.html`
- 任務總覽：`app/templates/overview.html`
- 題目頁：`app/templates/task.html`
- 樣式：`app/static/styles.css`
- 前端互動：`app/static/app.js`

### 正式使用前

每次修改後至少應：

1. 重新啟動程式。
2. 確認首頁環境狀態正常。
3. 執行完整 pytest。
4. 建立一份新測驗。
5. 確認續考、檢查、重設及兩份紀錄輪替正常。

## 19. 目前限制與後續選項

目前限制：

- 僅適用單機 Windows。
- 第一次安裝 Flask 需要套件來源或預先準備好的 `.venv`。
- 沒有考官密碼，受測者可自行重設本題。
- 沒有考試限時。
- 沒有集中式成績或紀錄管理。
- 最近測驗首頁最多顯示 8 筆。
- 第六題以最終內容、commit message、commit 數量及祖先關係判定，沒有記錄受測者實際輸入的 cherry-pick 指令。

可選的後續功能：

- 考官模式及受測者模式。
- 考試限時。
- 題庫及隨機抽題。
- HTML／PDF 結果摘要。
- 題目版本管理。
- Gerrit 實作題型。
- 將 Flask 與相依套件包裝成單一 Windows executable。

## 20. 完整程式檢驗與改善清單

檢驗日期：2026-08-04  
檢驗範圍：桌面版完整程式、題目設定、六題 templates、結果 JSON、現有 workspaces、自動化測試、資料安全、判定邏輯、啟動流程及 API。

本章保留 1.1 版檢驗當時的問題基準；其中描述的「目前行為」是修復前狀態。實際完成狀態與新版行為請以第 21 章為準。

### 20.1 檢驗基準

本次檢驗結果：

- 現有自動化測試：`10 passed`。
- 完整測試時間：約 98 秒。
- 六個題目 templates：`git fsck` 全部正常。
- `runtime/results` 中的 JSON：全部可正常解析。
- 沒有殘留 `.reset-*` 或 `.migrate-*` 暫存目錄。
- 大部分目前 workspaces repositories：Git 結構正常。

自動化測試通過只代表測試建立的隔離環境符合預期，不代表現有使用中 workspace 一定完整。因此仍需要獨立的 runtime 健康檢查。

### 20.2 目前發現的 Workspace 問題

本次檢驗發現兩個既有 workspace 已損壞，目前尚未修復：

#### Current Task 04

路徑：

```text
runtime/workspaces/Example-User/current/task04
```

狀態：

- 題目資料夾存在。
- `.git` 不存在。
- 結果 JSON 將 task04 記錄為 `in_progress`。
- 目前無法作為正常 Git repository 使用。

#### Previous Task 01

路徑：

```text
runtime/workspaces/Example-User/previous/task01/repo
```

狀態：

- `.git` 資料夾存在。
- `.git` 只剩部分 `objects` 與 `refs`。
- 缺少 `HEAD`、`config` 等必要 metadata。
- `git fsck`／`git status` 無法將它辨識為正常 repository。

### 20.3 P1：考生 ID 可能碰撞

目前位置：`app/services.py` 的 `_slug()`。

目前行為：

```python
slug = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(".-_")
return (slug or "candidate")[:40]
```

風險：

- 不同中文姓名都可能變成 `candidate`。
- `王小明` 和 `李小華` 可能共用同一個 workspace。
- Windows 路徑不區分大小寫，但程式 candidate ID 比較區分大小寫。
- `Example-User` 與 `example-user` 可能指向同一個實體資料夾，卻被結果邏輯視為不同考生。
- 同名考生也會共用 `current`／`previous`，造成紀錄輪替或刪除。

建議：

- 使用正規化顯示名稱加穩定 hash。
- Candidate identity 採 case-insensitive 比較。
- 若用於正式測驗，要求輸入唯一員工編號或考生代碼。

建議格式：

```text
王小明-a83f21
Example-User-482c1a
```

必要測試：

- 兩個不同中文姓名不可碰撞。
- 英文大小寫差異不可建立兩組衝突身份。
- 同名但不同唯一代碼的考生不可互相輪替。

### 20.4 P1：建立新測驗與兩份紀錄輪替不是完整交易

目前位置：

- `app/services.py:create_session()`
- `app/services.py:_rotate_for_new_session()`

目前流程：

1. 先刪除舊 `previous` 結果。
2. 先刪除舊 `previous` workspace。
3. 將 `current` 搬到 `previous`。
4. 再建立新的 `current`。
5. 逐題複製六個 repositories。
6. 最後才寫入新結果 JSON。

風險：

- 任一 template 複製失敗時，舊紀錄已經被輪替。
- 磁碟空間不足可能留下不完整 `current`。
- 寫入結果 JSON 失敗時，可能存在沒有結果索引的 workspace。
- 刪除舊 previous 成功、建立新 current 失敗時，可能只剩一份紀錄。
- 程式或電腦中途關閉時，無法保證回復原狀。

建議交易流程：

1. 在 staging 目錄建立完整新 Session。
2. 驗證六題 `.git`、HEAD、branches、tags 及 remote。
3. 預先產生並驗證結果 JSON。
4. 寫入 transaction manifest。
5. 一次交換 `current`／`previous`。
6. 確認成功後再清理最舊紀錄。
7. 任一步驟失敗都依 manifest 回復。

必要測試：

- 模擬第三題複製失敗。
- 模擬結果 JSON 寫入失敗。
- 模擬 previous 被占用。
- 模擬磁碟空間不足。
- 模擬流程中途終止後重新啟動。

### 20.5 P1：啟動時會直接刪除異常或過多紀錄

目前位置：`app/services.py:_normalize_storage()`。

目前行為：

- Workspace 不存在時直接刪除對應結果 JSON。
- 每位考生超過兩份時直接刪除第三份 workspace 與結果 JSON。
- `.migrate-*` 目錄會在啟動時直接清除。

風險：

- 暫時性檔案存取問題可能被視為永久遺失。
- 被防毒軟體、同步程式或其他程序暫時占用時，可能造成錯誤清理。
- 結果 JSON 被手動修改後，可能指向 `runtime/workspaces` 中其他考生的資料夾。
- 啟動整理沒有 migration backup 或操作報告。
- 單筆異常可能阻止整個應用程式啟動。

建議：

- 異常結果移到 `runtime/quarantine`，不要立即永久刪除。
- 最舊紀錄先移到 `runtime/archive`。
- 保留清理及 migration log。
- 驗證 workspace candidate ownership。
- Migration 採版本化並可回復。
- 單筆失敗應隔離，不應讓整個網站無法啟動。

### 20.6 P1：第六題可能將 Git 錯誤誤判為通過

目前位置：`app/check_engine.py` 的 `is_ancestor`／`not_is_ancestor`。

`git merge-base --is-ancestor` 回傳值：

| Return code | 意義 |
|---|---|
| `0` | 是 ancestor |
| `1` | 不是 ancestor |
| 其他 | Revision 不存在或 Git 發生錯誤 |

目前程式將所有非 `0` 結果都視為「不是 ancestor」。

可能的繞過方式：

1. 刪除 `fix/validation` branch。
2. 手動建立相同修改及 commit message。
3. `merge-base` 因 branch 不存在回傳錯誤。
4. `not_is_ancestor` 將錯誤視為通過。

建議：

- Return code `0`：ancestor。
- Return code `1`：not ancestor。
- 其他 return code：check failed，並顯示 revision 不存在或 Git 錯誤。

必要測試：

- 刪除 `fix/validation` 後不得通過。
- 使用不存在的 revision 時不得通過。
- Git repository 損壞時不得將錯誤當成正確結果。

### 20.7 P1：第二題仍可從 Working Tree 繞過判定

目前位置：`questions/questions.json` 中 task02 的 `test-content`。

目前使用：

```json
{
  "type": "file_contains",
  "file": "tests/test_config.py",
  "expected": "CONFIG_PATH == \"config/production.json\""
}
```

`file_contains` 檢查的是 working tree，不是 `HEAD`。

可能的繞過方式：

1. Amend 一個不正確的測試檔。
2. Commit 完成後再於 working tree 加入指定 assertion。
3. 最新 commit 確實包含該檔案，因此 `file_in_commit` 通過。
4. Working tree 出現指定文字，因此 `file_contains` 通過。
5. 題目沒有 `working_tree_clean`，最終可能被判定完成。

建議：

- 將 `test-content` 改成 `file_at_revision_contains`，revision 使用 `HEAD`。
- 加入 `working_tree_clean`。
- 更完整的方式是實際執行限制範圍內的 pytest。
- 若執行考生程式碼，必須加入 timeout、隔離及資源限制。

必要測試：

- Commit 後才修改 working tree 不得通過。
- Assertion 只出現在 comment 中不得通過。
- Python syntax error 不得被視為有效測試。

### 20.8 P1：缺少並行操作鎖定

目前相關位置：

- `app/services.py:_save_result()`
- `app/services.py:check_task()`
- `app/services.py:reset_task()`
- `app/services.py:create_session()`

目前結果 JSON 雖使用 temporary file 再 replace，可避免寫到一半的 JSON，但沒有阻止兩個 request 同時進行「讀取、修改、寫回」。

風險：

- 快速點擊兩次「檢查結果」可能遺失事件或計數。
- 兩個分頁同時 check／reset 可能互相覆蓋狀態。
- 同一考生同時建立兩份新測驗可能同時輪替 workspace。
- Reset 與 check 同時執行時，Git 檢查可能讀到交換中的 repository。

建議：

- Candidate 級 lock：保護新 Session 建立及 current／previous 輪替。
- Session 級 lock：保護結果 JSON。
- Task 級 lock：保護 check／reset。
- 前端加入 request ID 或 idempotency key。
- 重複 request 應回傳相同結果，不重複執行破壞性操作。

### 20.9 P2：有副作用的 API 缺少請求驗證

目前位置：`app/routes.py` 的 POST endpoints。

受影響 API：

- 建立新 Session。
- Check task。
- Reset task。
- Open task folder。

目前沒有：

- CSRF token。
- Origin 驗證。
- Host 驗證。
- 每次啟動產生的本機 API token。

即使 Server 只綁定 localhost，外部網站仍可能嘗試讓瀏覽器對本機服務送出 request。

建議：

- 驗證 `Origin` 與 `Host`。
- 加入每次啟動隨機產生的本機 token。
- Token 放入頁面及 AJAX header。
- 若未來使用 cookie，設定 SameSite。
- Reset 及 create 應增加 server-side confirmation token。

### 20.10 P2：Template Ready Marker 無法證明完整性

目前位置：`app/template_builder.py:ensure()`。

目前只要下列檔案存在，就完全跳過重建及完整性檢查：

```text
data/templates/.ready-v1
```

首頁的 template 檢查也只確認 `.git` 資料夾存在。

未被檢查的項目：

- Git repository 是否通過 `git fsck`。
- `HEAD` 是否存在。
- `assessment-start` tag 是否存在。
- 必要 branches 是否存在。
- 第四題 `origin/main` 是否存在。
- Working tree 初始修改是否正確。
- Commit message 及 commit count 是否正確。

建議：

- 為每題建立 template manifest。
- 啟動時執行快速完整性檢查。
- Templates 損壞時先建立 staging templates。
- Staging 全部驗證成功後才交換正式 templates。
- 不要因 marker 遺失就先刪除完整 template root。

### 20.11 P2：結果 JSON 缺少 Schema 驗證

目前 JSON 讀取主要依賴 `.get()`，未驗證完整 schema。

風險：

- `tasks` 不是 list 時首頁可能發生例外。
- 缺少 candidate ID 或 workspace 時可能觸發錯誤 migration。
- 不正確的 task status 仍可能進入 UI。
- 未來欄位調整沒有 schema version migration。

建議：

- 結果 JSON 增加 `schema_version`。
- 讀取時執行完整欄位及型別驗證。
- 不合法結果移到 quarantine。
- Migration 前建立備份。
- 保留 migration version 及時間。

### 20.12 P2：啟動、關閉及錯誤回報可改善

目前 `start.bat` 直接在 CMD 中執行 Flask，CMD 同時是 Server process 的生命週期。

目前限制：

- 關閉 CMD 就停止網站。
- 沒有 log 檔。
- 沒有重複啟動偵測。
- 沒有 port 占用檢查。
- `.venv` 存在但套件損壞時不會自動修復。
- Flask 啟動失敗後，瀏覽器 timer 仍可能打開無法連線的頁面。
- 沒有明確的「停止程式」入口。

建議：

- 寫入 rotating log file。
- 啟動前檢查 port。
- 建立 single-instance lock。
- 提供隱藏 CMD 的 launcher。
- 提供系統列圖示或停止程式入口。
- 隱藏啟動時仍保留可查看 log 的方式。
- 最終可包裝成 Windows executable。

### 20.13 P2：測試覆蓋與速度可改善

目前測試會為多個 test 重複複製六題 repositories，完整執行約需 98 秒。

建議新增測試：

- 不同中文姓名。
- 英文姓名大小寫差異。
- 同名考生加唯一代碼。
- 第六題不存在 branch。
- 第二題 working tree 繞過。
- Template 缺少 HEAD、tag、branch 或 remote。
- Result JSON schema 錯誤。
- Workspace 暫時無法存取。
- 建立 Session 中途失敗。
- Check 與 reset 同時執行。
- 同一考生同時建立兩個 Session。
- Server port 已占用。

測試速度改善：

- 共用只讀 template fixture。
- 只在真正需要時建立六題完整 Session。
- Check engine 單元測試使用最小 repository。
- 將慢速完整流程標示為 integration tests。
- 快速單元測試與完整驗收測試分開執行。

### 20.14 建議改善順序

建議依下列順序處理：

1. 增加啟動時 workspace 健康檢查，標示並安全修復目前損壞題目。
2. 修正考生 ID 的中文、大小寫及同名碰撞。
3. 將建立新 Session 及 current／previous 輪替改成完整交易。
4. 將異常資料改為 quarantine／archive，不直接永久刪除。
5. 修正第六題 invalid revision 誤判。
6. 修正第二題 working tree 判定漏洞。
7. 加入 candidate／session／task 操作鎖。
8. 加入 API Origin、Host 及本機 token 保護。
9. 加入 template manifest 與完整性檢查。
10. 加入結果 schema version 與 migration backup。
11. 加入 log、single-instance、port 檢查及無 CMD launcher。
12. 擴充測試覆蓋並縮短測試時間。

### 20.15 Runtime 健康檢查建議

未來首頁應增加「系統健康狀態」，至少檢查：

- 每個結果 JSON 是否符合 schema。
- 每個結果是否有對應 workspace。
- 每個 task 是否有可辨識的 `.git`。
- `git rev-parse --is-inside-work-tree` 是否成功。
- `git fsck` 是否成功。
- 題目必要 branch、tag 及 remote 是否存在。
- 是否有殘留 reset／migration staging 或 backup。
- Result task status 是否與 repository 可用性一致。

發現異常時：

- 不自動永久刪除。
- 顯示「需要修復」。
- 提供備份後從 template 重建的選項。
- 將修復動作寫入事件及 log。
- 已完成題目在修復前應要求考官確認，避免直接清除考生答案。

## 21. 1.2 版修復與改善實作結果

實作日期：2026-08-04

### 21.1 已完成項目

- Workspace 健康檢查：啟動與首頁先檢查結果 schema、workspace 及 `.git` 結構；題目總覽仍以 `rev-parse` 確認 Git repository，新 workspace 建立及正式測試使用 `git fsck`。首頁顯示問題數，另提供 `/api/health`。
- 安全修復：未完成的損壞題目會先移入 `runtime/quarantine` 再重建；已完成題目不會自動重設，必須在總覽進行額外確認。
- 考生身份：新 ID 使用正規化名稱加八碼 SHA-256，中文姓名不再全部變成 `candidate`，英文大小寫共用相同 identity。既有合法 ID 為了續考相容性會保留。
- Session 交易：新 workspace 在 staging 完整建立並驗證後才輪替；交換途中失敗會回復 current、previous 與結果 JSON。
- 安全保存：異常結果及 workspace 移到 quarantine；第三份舊紀錄移到 archive，不再直接永久刪除。
- 判定修正：`merge-base --is-ancestor` 只有 return code 0／1 代表有效判定，其他錯誤一律不通過。
- 第二題修正：預期內容改查 `HEAD`，並要求 working tree clean。
- 操作鎖：candidate、session、task 與 request 級 `RLock` 保護同一程序內的並行操作；單一執行個體鎖防止同一份程式重複啟動。
- API 防護：所有 POST 驗證 localhost Host、Origin、隨機 token；reset／repair 另驗證 confirmation header；request ID 提供重試去重。
- Template 完整性：`.ready-v6.json`、必要 ref、remote 與 `git fsck` 驗證，重建採 staging 交換。第四題驗證 pending main；第五題驗證 hotfix 只存在假遠端、本機與 remote-tracking refs 均不存在。
- 結果 schema：升級為 `schema_version: 3`，workspace 改存相對路徑；舊絕對路徑會依目前 runtime 自動 migration，並保留欄位、型別驗證及異常隔離。
- Windows 啟動：新增隱藏 CMD launcher、停止入口、rotating log、port 檢查、套件檢查與啟動完成後才開瀏覽器。
- 網頁安全關閉：所有頁面右上角提供確認按鈕，透過受 token 保護的 `/api/shutdown` 正常停止 Werkzeug server；完成後顯示精簡提示，PID、lock 與進度資料依既有生命週期正確處理。
- 瀏覽器啟動：改用 TCP port 就緒檢查，避免首頁健康檢查超過短 HTTP timeout 而無法開啟；再次雙擊會開啟既有網站，真正失敗時由 VBS 顯示 log 位置。
- 快速啟動：既有虛擬環境直接確認 Flask 套件檔案，不再為套件檢查額外啟動 Python 或每次執行完整 `pip check`；template 與既有 workspace 採快速結構檢查，完整 Git 驗證保留在資料建立及正式測試流程。
- Windows 腳本相容性：`start.bat`、`Stop Git Assessment.bat` 與 `Start Git Assessment.vbs` 固定保存為 CRLF，避免 CMD 將 LF-only 批次檔錯誤解析。
- 結果輸出：新增 HTML 摘要頁，列出考生姓名、完成題數、六題狀態及檢查次數；前端 Canvas 可下載 PNG，不需額外套件。
- 測試：由 10 組擴充為 21 組，涵蓋身份、API、判定繞過、假遠端 fetch、remote-only branch checkout、結果頁、安全關閉、建立／交換失敗回復、健康修復及整包搬移。

### 21.2 本次既有資料修復結果

- `Example-User/current/task04`：原資料已備份到 `runtime/quarantine`，題目已重建並回到 `not_started`。
- `Example-User/previous/task01`：原資料已備份到 `runtime/quarantine`，題目已重建並回到 `not_started`。
- 兩份結果已升級為 schema version 3 與相對 workspace 路徑。
- 最新 current 仍保留原本三題完成狀態。
- 修復後兩份 session 共十二個 repository 全部可用，runtime 健康問題數為 0。

### 21.3 保留限制

- 操作鎖是單一 Python 程序內鎖；應搭配 single-instance lock 使用，不支援多台主機共用同一 runtime。
- `runtime/archive` 與 `runtime/quarantine` 是復原用途，不計入首頁顯示的兩份有效測驗；目前由考官自行決定保留期限。
- 完整驗收測試使用真實 Git repositories，因此比一般單元測試慢；快速語法檢查可先用 `python -m py_compile`，正式發佈前仍應執行完整 pytest。
