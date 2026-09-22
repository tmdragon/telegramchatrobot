// form-submit.js：把新增项目表单的数据收集成 body 并 POST /api/projects。

import { postJson } from "./api.js";

export async function submitNewProject(form, errorEl) {
  const fd = new FormData(form);
  const body = {
    project_id: (fd.get("project_id") || "").trim(),
    project_name: (fd.get("project_name") || "").trim(),
    package_name: (fd.get("package_name") || "").trim(),
    launch_region: (fd.get("launch_region") || "").trim(),
    store_url: (fd.get("store_url") || "").trim(),
    // === WW 项目基础字段 ===
    a_package: (fd.get("a_package") || "").trim(),
    open_service_url: (fd.get("open_service_url") || "").trim(),
    adjust_key: (fd.get("adjust_key") || "").trim(),
    b_entry_name: (fd.get("b_entry_name") || "").trim(),
  };
  // info 字段（从动态渲染的 inputs 收集；空值不发）
  form.querySelectorAll("input[data-info-key]").forEach((el) => {
    const v = (el.value || "").trim();
    if (v) body[el.dataset.infoKey] = v;
  });
  if (!body.project_id || !body.project_name) {
    errorEl.textContent = "项目编号 和 项目名称 不能为空";
    errorEl.hidden = false;
    return;
  }
  // mapping
  if (form.querySelector("#np-enable-mapping").checked) {
    // 优先用 select 选中的已有群,否则用直接输入的 chat_id
    const sel = form.querySelector("#np-chat-id-select").value;
    const direct = (form.querySelector("#np-chat-id").value || "").trim();
    let chatId = null;
    if (sel && !direct) {
      chatId = parseInt(sel, 10);
    } else if (direct) {
      chatId = parseInt(direct, 10);
    }
    if (chatId === null || Number.isNaN(chatId)) {
      errorEl.textContent = "勾选映射时,必须选已有群或输入新 chat_id";
      errorEl.hidden = false;
      return;
    }
    body.mapping = {
      chat_id: chatId,
      note: (fd.get("mapping_note") || "").trim(),
    };
  }
  errorEl.hidden = true;
  const submitBtn = form.querySelector("#np-submit");
  submitBtn.disabled = true;
  submitBtn.textContent = "保存中...";
  try {
    await postJson("/api/projects", body);
    // 成功:整页 reload（最简单,确保 cache + UI 一致）
    window.location.reload();
  } catch (e) {
    const msg = (e && e.detail) || (e && e.message) || "未知错误";
    errorEl.textContent = `保存失败: ${msg}`;
    errorEl.hidden = false;
    submitBtn.disabled = false;
    submitBtn.textContent = "保存";
  }
}