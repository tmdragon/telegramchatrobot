// online.js：/online 页面的行内重测按钮。

import { postJson } from "./api.js";

async function _recheck(projectId, btn) {
  if (btn.disabled) return;
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "检测中…";
  try {
    const r = await postJson(
      `/api/online/projects/${encodeURIComponent(projectId)}/recheck`,
      {}
    );
    const result = r.result || "unknown";
    const reason = r.reason || "";
    const attempts = r.attempts || 0;
    let msg = "";
    if (result === "online") msg = `✓ ${projectId} 在线`;
    else if (result === "offline_pending") msg = `⚠ ${projectId} 疑似下架(第 ${attempts} 次失败),下次重试`;
    else if (result === "offline_confirmed") msg = `✗ ${projectId} 已确认下架,状态变更 + 已广播`;
    else msg = `? ${projectId} 检测失败: ${reason || "未知"}`;
    alert(msg);
    // 刷新页面以反映新状态
    window.location.reload();
  } catch (e) {
    alert(`重测失败: ${e.detail || e.message}`);
    btn.disabled = false;
    btn.textContent = original;
  }
}

export function init() {
  const tbody = document.querySelector("[data-online-tbody]");
  if (!tbody) return;
  tbody.addEventListener("click", (ev) => {
    const btn = ev.target.closest('button[data-action="online-recheck"]');
    if (!btn) return;
    const projectId = btn.dataset.projectId;
    if (projectId) _recheck(projectId, btn);
  });
}