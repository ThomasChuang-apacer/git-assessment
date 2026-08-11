document.addEventListener("DOMContentLoaded", () => {
  const apiToken = document.querySelector('meta[name="git-assessment-token"]')?.content || "";
  const shell = document.querySelector("[data-session-id][data-task-id]");

  const shutdownButton = document.getElementById("shutdown-app");
  shutdownButton?.addEventListener("click", async () => {
    const confirmed = window.confirm(
      "確定要安全關閉 Git Assessment 嗎？\n\n請先確認目前沒有正在建立、重設或檢查題目。已保存的測驗進度不會被刪除。"
    );
    if (!confirmed) return;

    shutdownButton.disabled = true;
    const fullLabel = shutdownButton.querySelector(".shutdown-label-full");
    const shortLabel = shutdownButton.querySelector(".shutdown-label-short");
    if (fullLabel) fullLabel.textContent = "正在安全關閉…";
    if (shortLabel) shortLabel.textContent = "關閉中…";

    try {
      const response = await fetch("/api/shutdown", {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-Git-Assessment-Token": apiToken,
          "X-Git-Assessment-Request-ID": window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
        },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "無法關閉 Git Assessment");
      document.getElementById("shutdown-screen").hidden = false;
      document.body.classList.add("is-shutting-down");
    } catch (error) {
      window.alert(error.message || "無法關閉 Git Assessment");
      shutdownButton.disabled = false;
      if (fullLabel) fullLabel.textContent = "安全關閉 Git Assessment";
      if (shortLabel) shortLabel.textContent = "安全關閉";
    }
  });

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        const original = button.textContent;
        button.textContent = "已複製";
        window.setTimeout(() => { button.textContent = original; }, 1400);
      } catch {
        window.prompt("請複製以下路徑：", target.textContent.trim());
      }
    });
  });

  const startForm = document.querySelector(".start-form");
  startForm?.addEventListener("submit", () => {
    const button = startForm.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.textContent = "正在建立測驗…";
    }
  });

  const repositoryGuide = document.getElementById("repository-guide");
  document.getElementById("open-repository-guide")?.addEventListener("click", () => {
    if (typeof repositoryGuide?.showModal === "function") repositoryGuide.showModal();
  });
  repositoryGuide?.querySelectorAll("[data-guide-close]").forEach((button) => {
    button.addEventListener("click", () => repositoryGuide.close());
  });
  repositoryGuide?.addEventListener("click", (event) => {
    if (event.target === repositoryGuide) repositoryGuide.close();
  });

  document.querySelectorAll("[data-delete-session]").forEach((button) => {
    button.addEventListener("click", async () => {
      const candidate = button.dataset.deleteCandidate || "這位考生";
      const started = button.dataset.deleteStarted || "所選時間";
      const confirmed = window.confirm(
        `確定要永久刪除「${candidate}」於 ${started} 的測驗紀錄嗎？\n\n該次測驗的結果與 Git workspace 都會刪除，無法復原。`
      );
      if (!confirmed) return;

      button.disabled = true;
      button.textContent = "刪除中…";
      try {
        const sessionId = encodeURIComponent(button.dataset.deleteSession);
        const response = await fetch(`/api/sessions/${sessionId}/delete`, {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "X-Git-Assessment-Token": apiToken,
            "X-Git-Assessment-Request-ID": window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
            "X-Git-Assessment-Confirm": "delete-session",
          },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || "無法刪除測驗紀錄");
        window.location.reload();
      } catch (error) {
        window.alert(error.message || "無法刪除測驗紀錄");
        button.disabled = false;
        button.textContent = "刪除";
      }
    });
  });

  document.querySelectorAll("[data-repair-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      const completed = button.dataset.repairCompleted === "yes";
      const warning = completed
        ? "此題已完成。修復會先備份資料，但會清除完成狀態並重建題目。考官確認要繼續嗎？"
        : "系統會先備份損壞資料，再重建本題。確定要繼續嗎？";
      if (!window.confirm(warning)) return;
      button.disabled = true;
      try {
        const response = await fetch(`/api/sessions/${encodeURIComponent(button.dataset.repairSession)}/tasks/${encodeURIComponent(button.dataset.repairTask)}/repair`, {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "X-Git-Assessment-Token": apiToken,
            "X-Git-Assessment-Request-ID": window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
            "X-Git-Assessment-Confirm": "repair",
            "X-Git-Assessment-Confirm-Completed": completed ? "yes" : "no",
          },
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "修復失敗");
        window.location.reload();
      } catch (error) {
        window.alert(error.message);
        button.disabled = false;
      }
    });
  });

  const resultButton = document.getElementById("download-result-png");
  resultButton?.addEventListener("click", () => {
    const dataElement = document.getElementById("result-summary-data");
    const message = document.getElementById("result-download-message");
    try {
      const summary = JSON.parse(dataElement.textContent);
      const width = 1200;
      const rowHeight = 112;
      const height = 390 + summary.tasks.length * rowHeight;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");

      ctx.fillStyle = "#f3f5f7";
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = "#20252b";
      ctx.fillRect(0, 0, width, 26);
      ctx.font = "700 24px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#075985";
      ctx.fillText("GIT PRACTICAL ASSESSMENT", 70, 85);
      ctx.font = "800 52px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#20252b";
      ctx.fillText("測驗結果摘要", 70, 150);

      ctx.font = "700 34px 'Microsoft JhengHei', sans-serif";
      ctx.fillText(summary.candidate_name, 70, 225);
      ctx.font = "500 20px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#5b6570";
      ctx.fillText(`開始時間：${summary.started_at}`, 70, 265);

      ctx.fillStyle = "#0f2f46";
      ctx.fillRect(895, 80, 235, 170);
      ctx.textAlign = "center";
      ctx.font = "800 58px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#9bd9f5";
      ctx.fillText(`${summary.completed_count}/${summary.total}`, 1012, 165);
      ctx.font = "600 20px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#ffffff";
      ctx.fillText("完成題數", 1012, 207);
      ctx.textAlign = "left";

      summary.tasks.forEach((task, index) => {
        const y = 320 + index * rowHeight;
        const completed = task.status === "completed";
        const inProgress = task.status === "in_progress";
        ctx.fillStyle = completed ? "#e9f6ee" : inProgress ? "#eef2f6" : "#ffffff";
        ctx.fillRect(70, y, 1060, 86);
        ctx.font = "800 24px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = "#5b6570";
        ctx.fillText(String(task.order).padStart(2, "0"), 98, y + 52);
        ctx.font = "700 25px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = "#20252b";
        ctx.fillText(task.title, 170, y + 39);
        ctx.font = "500 17px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = "#5b6570";
        ctx.fillText(`檢查次數：${task.check_attempts}`, 170, y + 67);
        ctx.textAlign = "right";
        ctx.font = "700 22px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = completed ? "#237a49" : inProgress ? "#475569" : "#5b6570";
        ctx.fillText(completed ? "✓ 已完成" : inProgress ? "進行中" : "尚未完成", 1090, y + 53);
        ctx.textAlign = "left";
      });

      ctx.font = "500 16px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#7b8782";
      ctx.fillText(`Session: ${summary.session_id}`, 70, height - 32);

      canvas.toBlob((blob) => {
        if (!blob) {
          message.textContent = "瀏覽器無法產生 PNG";
          message.className = "action-message error";
          return;
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        const safeName = summary.candidate_name.replace(/[\\/:*?"<>|]+/g, "-");
        link.href = url;
        link.download = `${safeName}-git-assessment-result.png`;
        link.click();
        URL.revokeObjectURL(url);
        message.textContent = "結果 PNG 已產生並下載。";
        message.className = "action-message success";
      }, "image/png");
    } catch (error) {
      message.textContent = error.message || "無法產生結果 PNG";
      message.className = "action-message error";
    }
  });

  if (!shell) return;
  const sessionId = shell.dataset.sessionId;
  const taskId = shell.dataset.taskId;
  const message = document.getElementById("action-message");

  const post = async (action) => {
    const requestId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const headers = {
      "Accept": "application/json",
      "X-Git-Assessment-Token": apiToken,
      "X-Git-Assessment-Request-ID": requestId,
    };
    if (action === "reset") headers["X-Git-Assessment-Confirm"] = "reset";
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}/${action}`, {
      method: "POST",
      headers,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "操作失敗");
    return payload;
  };

  const renderChecks = (checks) => {
    const list = document.getElementById("check-list");
    list.innerHTML = "";
    checks.forEach((check) => {
      const row = document.createElement("div");
      row.className = `check-item ${check.passed ? "passed" : "failed"}`;
      const symbol = document.createElement("span");
      symbol.className = "check-symbol";
      symbol.textContent = check.passed ? "✓" : "✗";
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = check.label;
      const detail = document.createElement("small");
      detail.textContent = check.message;
      copy.append(title, detail);
      row.append(symbol, copy);
      list.append(row);
    });
  };

  document.getElementById("check-task")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "檢查中…";
    message.textContent = "";
    try {
      const result = await post("check");
      renderChecks(result.checks);
      document.getElementById("completed-count").textContent = result.completed_count;
      document.getElementById("task-status-title").textContent = result.completed ? "任務已完成" : "還有項目未完成";
      document.getElementById("task-checkmark").classList.toggle("is-complete", result.completed);
      message.textContent = result.completed ? "完成狀態已保存。" : "請確認未通過的項目後再試一次。";
      message.className = `action-message ${result.completed ? "success" : "notice"}`;
      if (result.all_completed) message.textContent = "全部任務都完成了！返回總覽查看結果。";
    } catch (error) {
      message.textContent = error.message;
      message.className = "action-message error";
    } finally {
      button.disabled = false;
      button.textContent = "檢查結果";
    }
  });

  document.getElementById("reset-task")?.addEventListener("click", async (event) => {
    if (!window.confirm("重設會清除本題的所有 Git 操作與檔案修改。確定要繼續嗎？")) return;
    event.currentTarget.disabled = true;
    try {
      await post("reset");
      window.location.reload();
    } catch (error) {
      message.textContent = error.message;
      message.className = "action-message error";
      event.currentTarget.disabled = false;
    }
  });

  document.getElementById("simulate-remote-update")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    message.textContent = "正在更新假遠端…";
    try {
      const result = await post("remote-update");
      message.textContent = result.updated
        ? "遠端 main 已更新。提示：遠端資料更新後，要先 fetch 最新資訊，再觀察 origin/main 的變化。"
        : "遠端 main 已經是最新模擬狀態。請先取得最新遠端資訊，再處理分支整合。";
      message.className = "action-message success";
      button.textContent = "遠端更新已建立";
    } catch (error) {
      message.textContent = error.message;
      message.className = "action-message error";
      button.disabled = false;
    }
  });

  document.getElementById("open-folder")?.addEventListener("click", async () => {
    try {
      await post("open");
      message.textContent = "已送出開啟資料夾要求。";
      message.className = "action-message success";
    } catch (error) {
      message.textContent = error.message;
      message.className = "action-message error";
    }
  });
});
