# Git 實作考試系統

這是一套在 Windows 本機執行的 Git 實作測驗 MVP。受測者在 Terminal 或 VS Code 操作真實 Git repository，再回到瀏覽器按「檢查結果」。系統只記錄任務完成狀態，不記錄逐條 Git 指令，也不計算分數。

## 快速開始

環境需求：

- Windows 10 或 Windows 11
- Python 3.11 或更新版本
- Git for Windows

操作方式：

1. 雙擊 `Start Git Assessment.vbs`（不顯示 CMD 視窗）。如需查看即時錯誤，可改用 `start.bat`。
2. 第一次啟動會顯示進度視窗，建立專用 Python 環境並安裝 Flask；請保持網路連線。完成後進度視窗會自動關閉。
3. 瀏覽器會自動開啟 `http://127.0.0.1:8765`。
4. 輸入姓名或識別代碼，開始測驗。
5. 在題目顯示的 repository 中完成 Git 操作。
6. 回到瀏覽器按「檢查結果」。

任務總覽及每一題標題旁提供「如何開始」按鈕，說明如何複製地址後使用 `cd`、從檔案總管網址列輸入 `cmd`，或使用 VS Code 開啟題目的 repository。

中途關閉程式不會清除進度。下次啟動後，可在首頁按「繼續上次測驗」，或從「最近的測驗」選擇要恢復的紀錄。續考功能需要對應的 `runtime/results` 與 `runtime/workspaces` 同時存在。

每位考生最多保留兩份測驗，工作目錄固定使用：

```text
runtime/workspaces/<candidate>/current/
runtime/workspaces/<candidate>/previous/
```

建立新測驗時，系統會先在 staging 完整建立並驗證六題，成功後才將原本的 `current` 輪替成 `previous`。更舊的資料會移入 `runtime/archive`，不會在輪替途中直接永久刪除。每個 `task01` 至 `task06` 資料夾本身就是 Git repository，不再額外包含 `repo` 子資料夾。

整包程式可以壓縮後搬到其他 Windows 電腦。搬移前請先停止 Git Assessment，再壓縮完整的 `git-assessment` 資料夾；到新電腦後必須先完整解壓縮，不能直接在 ZIP 預覽中執行。結果 JSON 使用相對 workspace 路徑，啟動後會依新的程式位置找到 `runtime/workspaces`，並自動修正第四、五題的本機 `origin` 路徑。新電腦仍需具備 Python 3.11+ 與 Git for Windows。

若要停止程式，可在任一網頁右上角按「安全關閉 Git Assessment」。確認後伺服器會正常停止，畫面會顯示「關閉 Git Assessment」與「測驗進度已保存，現在可以關閉此頁。」；`Stop Git Assessment.bat` 保留為網頁無法操作時的備用停止方式。執行紀錄位於 `runtime/logs/git-assessment.log`；程式會檢查重複啟動及 port 占用。
若程式已在背景執行，再次雙擊 `Start Git Assessment.vbs` 會直接開啟現有網站；若啟動失敗則會顯示 log 位置。
Windows 啟動檔必須保留 CRLF 換行；若用編輯器修改 `.bat`／`.vbs`，請勿轉成 LF-only。

如不想自動開啟瀏覽器，可在啟動前設定 `GIT_ASSESSMENT_NO_BROWSER=1`。如需更換 port，可設定 `GIT_ASSESSMENT_PORT`。

## 題目內容

目前包含六個互相獨立的任務：

1. 選擇性提交指定檔案。
2. 補充最新 commit，且不增加 commit 數量。
3. 建立工作分支並提交修改。
4. Rebase 最新主分支並處理 conflict。
5. 暫存未完成修改、切換分支後恢復。
6. 將指定 commit 套用到目前分支。

題目 repository 會在第一次啟動時離線建立，不會連線到公司 repository 或 Gerrit。

## 執行測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Git 與 CI/CD

專案使用 `main` 作為可發布分支。每次 push 到 `main` 或對 `main` 建立 Pull Request 時，GitHub Actions 會在 Windows、Python 3.11 執行完整測試；推送 `v*` tag 時，測試通過後會建立 Windows ZIP 並發布到 GitHub Releases。

### 第一次設定 GitHub

1. 在 GitHub 建立名為 `git-assessment` 的空 repository；不要勾選新增 README、`.gitignore` 或 License。
2. 在本機專案執行：

```powershell
git remote add origin https://github.com/<account>/git-assessment.git
git push -u origin main
```

3. 到 GitHub 的 **Actions** 頁面，確認 `CI/CD` workflow 的 `test` job 通過。
4. 到 **Settings → Rules → Rulesets** 為 `main` 建立 branch ruleset，至少啟用 Require a pull request、Require status checks（選擇 `test`）、Block force pushes 與 Restrict deletions。`test` 通常要在第一次 workflow 執行後才會出現在選單。
5. Workflow 不需要自建 secret；發布使用 repository 內建的 `GITHUB_TOKEN`。若組織政策禁止 `contents: write`，需請 GitHub 組織管理員允許 workflow 建立 Release。

### 日常開發

```powershell
git switch -c feature/<change-name>
# 修改並在本機完成測試
git add .
git commit -m "Describe the change"
git push -u origin feature/<change-name>
```

接著在 GitHub 建立 Pull Request；CI 通過後才合併到 `main`。建議在 repository 的 Branch protection rule 要求 Pull Request 與 `test` status check。

### 建立版本

```powershell
git switch main
git pull --ff-only
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

Release ZIP 不含測試、規格、GitHub workflow、`runtime` 或產生出的 `data/templates`；使用者第一次啟動時仍會依既有流程建立 templates 與安裝 Flask。

測試會建立臨時題目環境，驗證：

- 所有題目的初始狀態都不會誤判為完成。
- 六題的標準操作結果都能通過。
- 重設單題不會影響其他題目。
- 首頁、總覽與題目頁可以正常載入。
- 中文姓名不碰撞、英文大小寫使用同一身份。
- 建立新測驗失敗時保留原本 current。
- 損壞的未完成題目會先備份再修復。
- API token、重複請求與 Git revision 錯誤不會被繞過。
- 安全關閉 API 必須通過 token 驗證，並會呼叫受控伺服器的正常關閉程序。
- 整包 runtime 搬到不同位置後，舊版絕對 workspace 紀錄會轉成可攜式路徑，且本機 origin 會指向新位置。

## 重要資料夾

```text
app/                 Flask 程式與畫面
questions/           題目文字及自動檢查設定
data/templates/      第一次啟動時產生的題目 templates
runtime/workspaces/  受測者實際操作的 repositories
runtime/results/     每次考試的 JSON 結果
runtime/archive/     輪替出的舊資料（不顯示於考試首頁）
runtime/quarantine/  損壞或格式異常資料的安全備份
runtime/logs/        啟動及錯誤 log
tests/               自動化驗收測試
```

首頁「最近的測驗」每筆紀錄都有「刪除」按鈕。確認後會永久刪除該次結果與對應的 Git workspace，無法復原；若 workspace 正被 Terminal 或編輯器占用，請先關閉後再試。若刪除最新紀錄而仍有上一份紀錄，系統會自動整理剩餘紀錄供後續續考。

## 題目維護

題目文字與檢查條件位於 `questions/questions.json`。初始 Git history 由 `app/template_builder.py` 建立。

Template 由 `.ready-v6.json` manifest 管理。一般啟動會快速確認 manifest、六題 `.git` 與必要本機 origin；template 重建、新測驗 workspace 建立及正式測試仍會驗證 HEAD、必要 refs 與 `git fsck`。若快速檢查發現結構損壞，程式會先在 staging 建好並完整驗證新版本，再交換正式 templates。第四題使用本機 bare repository 模擬 fetch；第五題的 hotfix 只存在另一個本機 bare remote，考生取得遠端資訊後可使用 `switch` 或 `checkout` 建立本機追蹤分支。正式使用前務必執行完整測試。

任務總覽的「查看／保存結果」會開啟可閱讀的結果摘要，包含考生姓名、完成題數及每題完成／未完成狀態；按「保存成 PNG」即可下載圖片，不需要額外安裝截圖套件。

所有有副作用的本機 API 都要求每次啟動產生的 token，並驗證 Host 與 Origin。結果 JSON 使用 schema version 3，workspace 保存為相對路徑；schema version 2 與更早的絕對路徑紀錄會在啟動時自動遷移。無效資料會移入 quarantine。首頁會顯示 runtime 健康狀態，損壞題目可在任務總覽備份後重建；已完成題目需要額外確認。
