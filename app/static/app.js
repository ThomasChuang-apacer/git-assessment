document.addEventListener("DOMContentLoaded", () => {
  const apiToken = document.querySelector('meta[name="git-assessment-token"]')?.content || "";
  const shell = document.querySelector("[data-session-id][data-task-id]");
  const liveRegion = document.getElementById("live-region");
  const announce = (text) => {
    if (!liveRegion) return;
    liveRegion.textContent = "";
    window.setTimeout(() => { liveRegion.textContent = text; }, 50);
  };

  const formatDateTime = (iso) => {
    if (!iso) return "—";
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return iso;
    const pad = (value) => String(value).padStart(2, "0");
    return `${parsed.getFullYear()}/${pad(parsed.getMonth() + 1)}/${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
  };

  const confirmDialog = document.getElementById("confirm-dialog");
  // Resolves true only when the confirm button is pressed.
  // With cancelLabel: null it acts as a single-button notice (replaces window.alert).
  const askConfirm = ({ title, message, confirmLabel = "確定", cancelLabel = "取消", danger = false }) => {
    if (typeof confirmDialog?.showModal !== "function") {
      if (cancelLabel === null) { window.alert(`${title}\n\n${message}`); return Promise.resolve(true); }
      return Promise.resolve(window.confirm(`${title}\n\n${message}`));
    }
    document.getElementById("confirm-dialog-title").textContent = title;
    document.getElementById("confirm-dialog-message").textContent = message;
    const ok = document.getElementById("confirm-dialog-ok");
    const cancel = document.getElementById("confirm-dialog-cancel");
    ok.textContent = confirmLabel;
    ok.className = `button ${danger ? "button-danger-solid" : "button-primary"}`;
    cancel.hidden = cancelLabel === null;
    if (cancelLabel !== null) cancel.textContent = cancelLabel;
    confirmDialog.returnValue = "cancel";
    confirmDialog.showModal();
    (danger && cancelLabel !== null ? cancel : ok).focus();
    return new Promise((resolve) => {
      confirmDialog.addEventListener("close", () => resolve(confirmDialog.returnValue === "confirm"), { once: true });
    });
  };
  const showNotice = (title, message) => askConfirm({ title, message, confirmLabel: "我知道了", cancelLabel: null });

  const shutdownButton = document.getElementById("shutdown-app");
  shutdownButton?.addEventListener("click", async () => {
    const confirmed = await askConfirm({
      title: "安全關閉 Git Assessment？",
      message: "請先確認目前沒有正在建立、重設或檢查題目。已保存的測驗進度不會被刪除。",
      confirmLabel: "安全關閉",
    });
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
      showNotice("無法關閉", error.message || "無法關閉 Git Assessment");
      shutdownButton.disabled = false;
      if (fullLabel) fullLabel.textContent = "安全關閉 Git Assessment";
      if (shortLabel) shortLabel.textContent = "安全關閉";
    }
  });

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      const copyLabel = button.dataset.copyLabel || "內容";
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        const original = button.dataset.originalLabel || button.textContent;
        button.dataset.originalLabel = original;
        button.textContent = "已複製";
        announce(`已複製${copyLabel}到剪貼簿`);
        window.setTimeout(() => { button.textContent = original; }, 1400);
      } catch {
        window.prompt(`請複製以下${copyLabel}：`, target.textContent.trim());
      }
    });
  });

  const startForm = document.querySelector(".start-form[action$='/api/sessions']");
  const nameInput = document.getElementById("candidate_name");
  const nameError = document.getElementById("candidate-name-error");
  nameInput?.addEventListener("input", () => {
    if (nameError && !nameError.hidden && nameInput.value.trim()) {
      nameError.hidden = true;
      nameError.textContent = "";
      nameInput.removeAttribute("aria-invalid");
    }
  });
  startForm?.addEventListener("submit", (event) => {
    if (nameInput) {
      const trimmed = nameInput.value.trim();
      if (!trimmed) {
        event.preventDefault();
        if (nameError) {
          nameError.textContent = "請輸入姓名或識別代碼（不能只有空白字元）。";
          nameError.hidden = false;
        }
        nameInput.setAttribute("aria-invalid", "true");
        nameInput.focus();
        return;
      }
      if (trimmed.length > 80) {
        event.preventDefault();
        if (nameError) {
          nameError.textContent = "姓名或識別代碼不可超過 80 個字元。";
          nameError.hidden = false;
        }
        nameInput.setAttribute("aria-invalid", "true");
        nameInput.focus();
        return;
      }
      nameInput.removeAttribute("aria-invalid");
      nameInput.value = trimmed;
    }
    const button = startForm.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.textContent = "正在建立 6 題獨立 Git 環境，請稍候…";
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
      const confirmed = await askConfirm({
        title: `永久刪除「${candidate}」的測驗紀錄？`,
        message: `開始時間：${started}\n該次測驗的結果與 Git workspace 都會刪除，無法復原。`,
        confirmLabel: "永久刪除",
        danger: true,
      });
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
        showNotice("刪除失敗", error.message || "無法刪除測驗紀錄");
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
        : "系統會先將損壞資料安全備份，再重建本題。確定要繼續嗎？";
      const confirmed = await askConfirm({
        title: "備份並修復這一題？",
        message: warning,
        confirmLabel: "備份並修復",
        danger: completed,
      });
      if (!confirmed) return;
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
        showNotice("修復失敗", error.message);
        button.disabled = false;
      }
    });
  });

  const cleanupButton = document.getElementById("cleanup-quarantine");
  const cleanupMessage = document.getElementById("cleanup-message");
  cleanupButton?.addEventListener("click", async () => {
    const confirmed = await askConfirm({
      title: "清理隔離備份與舊版殘留檔？",
      message: "會移除 runtime/quarantine/ 內容及舊版殘留的 git-exam.lock / debug/ 目錄；不會刪除現有有效測驗紀錄。",
      confirmLabel: "確認清理",
      danger: true,
    });
    if (!confirmed) return;
    cleanupButton.disabled = true;
    try {
      const response = await fetch("/api/examiner/cleanup", {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          "X-Git-Assessment-Token": apiToken,
          "X-Git-Assessment-Request-ID": window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
        },
        body: JSON.stringify({ include_quarantine: true, include_archive: false }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "清理失敗");
      if (cleanupMessage) {
        cleanupMessage.textContent = `已完成清理，共移除 ${payload.removed_items} 項殘留或隔離項目。`;
        cleanupMessage.className = "inline-message success";
      }
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      if (cleanupMessage) {
        cleanupMessage.textContent = error.message || "清理失敗";
        cleanupMessage.className = "inline-message error";
      }
      cleanupButton.disabled = false;
    }
  });

  const copySummaryButton = document.getElementById("copy-result-text");
  copySummaryButton?.addEventListener("click", async () => {
    const dataElement = document.getElementById("result-summary-data");
    const message = document.getElementById("result-download-message");
    try {
      const summary = JSON.parse(dataElement.textContent);
      const lines = [
        `【Git 實作測驗結果摘要】`,
        `姓名：${summary.candidate_name}（${summary.mode_label}）`,
        `完成題數：${summary.completed_count}/${summary.total}`,
        `開始時間：${formatDateTime(summary.started_at)}`,
        `完成時間：${formatDateTime(summary.completed_at)}`,
        `總作答時間：${summary.duration_display}`,
        `校驗碼：${summary.integrity_short}（${summary.integrity_ok ? "檔案一致" : "檔案異動"}）`,
        "",
        ...summary.tasks.map((task) => {
          const st = task.status === "completed" ? "已完成" : task.status === "in_progress" ? "進行中" : "尚未完成";
          const parts = [`檢查 ${task.check_attempts} 次`, `重設 ${task.reset_count} 次`];
          if (task.repair_count) parts.push(`修復 ${task.repair_count} 次`);
          return `0${task.order} ${task.title}：${st}（${parts.join("、")}）`;
        }),
      ];
      await navigator.clipboard.writeText(lines.join("\n"));
      if (message) {
        message.textContent = "文字結果摘要已複製到剪貼簿。";
        message.className = "action-message success";
      }
    } catch (error) {
      if (message) {
        message.textContent = error.message || "無法複製文字摘要";
        message.className = "action-message error";
      }
    }
  });

  const resultButton = document.getElementById("download-result-png");
  resultButton?.addEventListener("click", () => {
    const dataElement = document.getElementById("result-summary-data");
    const message = document.getElementById("result-download-message");
    try {
      const summary = JSON.parse(dataElement.textContent);
      const width = 1200;
      const rowHeight = 112;
      const height = 430 + summary.tasks.length * rowHeight;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");

      ctx.fillStyle = "#f3f5f7";
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = "#20252b";
      ctx.fillRect(0, 0, width, 26);
      ctx.font = "700 22px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#075985";
      ctx.fillText(`GIT PRACTICAL ASSESSMENT · ${summary.mode_label}`, 70, 82);
      ctx.font = "800 50px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#20252b";
      ctx.fillText("測驗結果摘要", 70, 146);

      ctx.font = "700 32px 'Microsoft JhengHei', sans-serif";
      ctx.fillText(summary.candidate_name, 70, 218, 790);
      ctx.font = "500 18px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#5b6570";
      ctx.fillText(
        `開始時間：${formatDateTime(summary.started_at)}　完成時間：${formatDateTime(summary.completed_at)}`,
        70,
        256
      );
      const topSummaryParts = [
        `總作答時間：${summary.duration_display}`,
        `重設總計：${summary.total_resets || 0} 次`,
      ];
      if (summary.total_repairs) topSummaryParts.push(`修復總計：${summary.total_repairs} 次`);
      topSummaryParts.push(`提示使用：${summary.total_hints || 0} 次`);
      ctx.fillText(topSummaryParts.join("　"), 70, 286);

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
        const y = 340 + index * rowHeight;
        const completed = task.status === "completed";
        const inProgress = task.status === "in_progress";
        ctx.fillStyle = completed ? "#e9f6ee" : inProgress ? "#eef2f6" : "#ffffff";
        ctx.fillRect(70, y, 1060, 86);
        ctx.font = "800 24px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = "#5b6570";
        ctx.fillText(String(task.order).padStart(2, "0"), 98, y + 52);
        ctx.font = "700 24px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = "#20252b";
        ctx.fillText(task.title, 170, y + 38, 700);
        ctx.font = "500 17px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = "#5b6570";
        const metaParts = [`檢查次數：${task.check_attempts}`, `重設次數：${task.reset_count || 0}`];
        if (task.repair_count) metaParts.push(`修復：${task.repair_count} 次`);
        if (completed && task.duration_display && task.duration_display !== "—") {
          metaParts.push(`耗時：${task.duration_display}`);
        }
        ctx.fillText(metaParts.join(" · "), 170, y + 66);
        ctx.textAlign = "right";
        ctx.font = "700 22px 'Microsoft JhengHei', sans-serif";
        ctx.fillStyle = completed ? "#237a49" : inProgress ? "#475569" : "#5b6570";
        ctx.fillText(completed ? "✓ 已完成" : inProgress ? "進行中" : "尚未完成", 1090, y + 53);
        ctx.textAlign = "left";
      });

      ctx.font = "500 15px 'Microsoft JhengHei', sans-serif";
      ctx.fillStyle = "#5b6570";
      ctx.fillText(
        `Session: ${summary.session_id} · 校驗碼：${summary.integrity_short || "無"}（${summary.integrity_ok ? "檔案一致" : "檔案異動"}）`,
        70,
        height - 28
      );

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
  const isExamMode = shell.dataset.mode === "exam";
  const message = document.getElementById("action-message");

  const post = async (action, jsonBody = null) => {
    const requestId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const headers = {
      "Accept": "application/json",
      "X-Git-Assessment-Token": apiToken,
      "X-Git-Assessment-Request-ID": requestId,
    };
    if (action === "reset") headers["X-Git-Assessment-Confirm"] = "reset";
    const options = { method: "POST", headers };
    if (jsonBody !== null) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(jsonBody);
    }
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}/${action}`, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "操作失敗");
    return payload;
  };

  const checkDisplayState = (check) => check.display_state || (check.passed ? "passed" : "failed");

  const renderChecks = (checks) => {
    const list = document.getElementById("check-list");
    list.innerHTML = "";
    checks.forEach((check) => {
      const dstate = checkDisplayState(check);
      const row = document.createElement("div");
      row.className = `check-item ${dstate}`;
      const symbol = document.createElement("span");
      symbol.className = "check-symbol";
      symbol.setAttribute("aria-hidden", "true");
      symbol.textContent = dstate === "passed" ? "✓" : dstate === "waiting" ? "·" : "✗";
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

  const checkButtons = document.querySelectorAll("[data-check-trigger]");
  const mainCheckButton = document.getElementById("check-task");
  const nextStepLink = document.getElementById("next-step-link");
  const checkPanel = document.querySelector(".check-panel");

  const setInlineMessage = (element, text, tone) => {
    const target = element || message;
    target.textContent = text;
    target.className = `${target === message ? "action-message" : "inline-message"} ${tone}`;
  };

  const runCheck = async (trigger) => {
    const labels = new Map([...checkButtons].map((button) => [button, button.textContent]));
    checkButtons.forEach((button) => { button.disabled = true; button.textContent = "檢查中…"; });
    message.textContent = "";
    try {
      const result = await post("check");
      renderChecks(result.checks);
      const passed = result.checks.filter((check) => checkDisplayState(check) === "passed").length;
      const failedCount = result.checks.filter((check) => checkDisplayState(check) === "failed").length;
      const summary = `${passed} / ${result.checks.length} 通過`;
      const summaryEl = document.getElementById("check-summary");
      const dockSummaryEl = document.getElementById("check-dock-summary");
      const attemptEl = document.getElementById("attempt-count");
      if (summaryEl) summaryEl.textContent = summary;
      if (dockSummaryEl) dockSummaryEl.textContent = summary;
      if (attemptEl && typeof result.check_attempts === "number") {
        attemptEl.textContent = result.check_attempts;
      }
      document.getElementById("completed-count").textContent = result.completed_count;
      document.getElementById("task-status-title").textContent = result.completed ? "任務已完成" : "還有項目未完成";
      const checkmark = document.getElementById("task-checkmark");
      if (checkmark) {
        checkmark.classList.toggle("is-complete", result.completed);
        checkmark.classList.toggle("is-failed", !result.completed);
        checkmark.textContent = result.completed ? "✓" : "!";
      }
      if (nextStepLink) {
        nextStepLink.hidden = !result.completed;
        if (result.all_completed && nextStepLink.dataset.resultHref) {
          nextStepLink.href = nextStepLink.dataset.resultHref;
          nextStepLink.textContent = "查看／保存結果 →";
        } else if (nextStepLink.dataset.nextHref) {
          nextStepLink.href = nextStepLink.dataset.nextHref;
          nextStepLink.textContent = nextStepLink.dataset.nextLabel || "前往下一題 →";
        }
      }
      mainCheckButton?.classList.toggle("button-primary", !result.completed);
      mainCheckButton?.classList.toggle("button-secondary", result.completed);
      if (mainCheckButton) labels.set(mainCheckButton, result.completed ? "重新檢查" : "檢查結果");
      const remaining = failedCount || (result.checks.length - passed);
      let text = result.completed
        ? "完成狀態已保存。"
        : `還有 ${remaining} 項未通過，請依紅色項目的說明修正後再試。`;
      if (result.all_completed) text = "全部任務都完成了！可點擊「查看／保存結果」下載成績單。";
      setInlineMessage(message, text, result.completed ? "success" : "notice");

      const firstFailed = document.querySelector("#check-list .check-item.failed");
      if (firstFailed || trigger !== mainCheckButton) {
        (firstFailed || checkPanel)?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      if (firstFailed) {
        firstFailed.tabIndex = -1;
        firstFailed.focus({ preventScroll: true });
      } else if (result.completed) {
        nextStepLink?.focus({ preventScroll: true });
      }
    } catch (error) {
      setInlineMessage(message, error.message, "error");
    } finally {
      checkButtons.forEach((button) => { button.disabled = false; button.textContent = labels.get(button); });
    }
  };

  checkButtons.forEach((button) => button.addEventListener("click", () => runCheck(button)));

  const checkDock = document.getElementById("check-dock");
  if (checkDock && checkPanel && "IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => {
      checkDock.classList.toggle("is-hidden", entry.isIntersecting);
    }, { threshold: 0.15 }).observe(checkPanel);
  }

  document.querySelectorAll(".hint-toggle").forEach((button) => {
    button.addEventListener("click", async () => {
      const idx = Number(button.dataset.hintIndex);
      const body = document.getElementById(`hint-body-${idx}`);
      if (!body) return;
      const isExpanded = button.getAttribute("aria-expanded") === "true";
      if (isExpanded) {
        body.hidden = true;
        button.setAttribute("aria-expanded", "false");
        return;
      }
      if (button.dataset.loaded === "yes" && body.textContent.trim()) {
        body.hidden = false;
        button.setAttribute("aria-expanded", "true");
        return;
      }
      if (isExamMode) {
        const confirmed = await askConfirm({
          title: "確認展開提示？",
          message: "考試模式下展開提示會記錄於測驗結果的提示使用次數中，確定要查看這條提示嗎？",
          confirmLabel: "展開提示",
        });
        if (!confirmed) return;
      }
      button.disabled = true;
      try {
        const outcome = await post("hint", { hint_index: idx });
        body.textContent = outcome.hint_text || "";
        body.hidden = false;
        button.dataset.loaded = "yes";
        button.setAttribute("aria-expanded", "true");
        button.textContent = `提示 ${idx + 1}（已檢視）`;
        const counter = document.getElementById("hints-used-count");
        if (counter && typeof outcome.hints_used === "number") {
          counter.textContent = outcome.hints_used;
        }
      } catch (error) {
        setInlineMessage(message, error.message || "無法載入提示", "error");
      } finally {
        button.disabled = false;
      }
    });
  });

  document.getElementById("reset-task")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const confirmed = await askConfirm({
      title: "重設本題？",
      message: "會清除本題的所有 Git 操作與檔案修改，回到題目剛建立時的狀態（歷史檢查與重設次數會保留於結果紀錄）。",
      confirmLabel: "重設本題",
      danger: true,
    });
    if (!confirmed) return;
    button.disabled = true;
    try {
      await post("reset");
      window.location.reload();
    } catch (error) {
      setInlineMessage(message, error.message, "error");
      button.disabled = false;
    }
  });

  document.getElementById("simulate-remote-update")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const remoteMessage = document.getElementById("remote-message");
    button.disabled = true;
    setInlineMessage(remoteMessage, "正在更新模擬遠端…", "");
    try {
      const result = await post("remote-update");
      const msg = isExamMode
        ? (result.updated
            ? "遠端 main 已更新，請回 Terminal 同步遠端變更並完成整合。"
            : "遠端 main 已經是最新模擬狀態，請回 Terminal 同步並完成整合。")
        : (result.updated
            ? "遠端 main 已更新。提示：遠端資料更新後，要先執行 git fetch origin，再觀察 origin/main 的變化。"
            : "遠端 main 已經是最新模擬狀態。請先執行 git fetch origin，再處理分支整合。");
      setInlineMessage(remoteMessage, msg, "success");
      button.textContent = "遠端更新已建立";
    } catch (error) {
      setInlineMessage(remoteMessage, error.message, "error");
      button.disabled = false;
    }
  });

  const repoMessage = document.getElementById("repo-message");
  document.getElementById("open-folder")?.addEventListener("click", async () => {
    try {
      await post("open");
      setInlineMessage(repoMessage, "已在檔案總管開啟資料夾（沒看到的話，請檢查工作列）。", "success");
    } catch (error) {
      setInlineMessage(repoMessage, error.message, "error");
    }
  });
});
