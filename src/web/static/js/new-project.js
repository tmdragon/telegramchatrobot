// new-project.js：新增项目 modal 控制 + 表单提交。
//
// 流程：
// 1. 点击 "+ 新增项目" 按钮 → 打开 modal
// 2. modal 打开时加载已有群列表（GET /api/groups），填充 <select>
// 3. 用户填写表单 → POST /api/projects
// 4. 成功后刷新页面（或局部刷新项目列表）

import { postJson, ApiError } from "./api.js";

const STATUS_DEFAULT = "对方下单";

let _groups = []; // [{chat_id, note}, ...] 从 GET /api/groups 缓存

async function _loadGroups(selectEl) {
  try {
    const r = await fetch("/api/groups", { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    _groups = data.groups || [];
  } catch (e) {
    console.warn("load groups failed:", e);
    _groups = [];
  }
  // 填充 select（保留第一个 -- 选择已有群 -- option）
  while (selectEl.options.length > 1) selectEl.remove(1);
  for (const g of _groups) {
    const opt = document.createElement("option");
    opt.value = g.chat_id;
    opt.textContent = `${g.chat_id}${g.note ? " (" + g.note + ")" : ""}`;
    selectEl.appendChild(opt);
  }
}

function _openModal(modal, form, errorEl, groupSelect) {
  form.reset();
  errorEl.hidden = true;
  errorEl.textContent = "";
  // 隐藏 mapping 子区
  const mappingFields = form.querySelector("#np-mapping-fields");
  const enableMapping = form.querySelector("#np-enable-mapping");
  enableMapping.checked = false;
  mappingFields.hidden = true;
  modal.hidden = false;
  modal.setAttribute("aria-hidden", "false");
  _loadGroups(groupSelect);
  form.querySelector("#np-project-id").focus();
}

function _closeModal(modal) {
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
}

function _toggleMappingFields(form) {
  const enabled = form.querySelector("#np-enable-mapping").checked;
  const fields = form.querySelector("#np-mapping-fields");
  fields.hidden = !enabled;
}

async function _submit(form, errorEl) {
  const fd = new FormData(form);
  const body = {
    project_id: (fd.get("project_id") || "").trim(),
    project_name: (fd.get("project_name") || "").trim(),
    package_name: (fd.get("package_name") || "").trim(),
    launch_region: (fd.get("launch_region") || "").trim(),
  };
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

export function init() {
  const btn = document.getElementById("btn-new-project");
  const modal = document.getElementById("new-project-modal");
  const form = document.getElementById("new-project-form");
  const errorEl = document.getElementById("new-project-error");
  const groupSelect = document.getElementById("np-chat-id-select");
  if (!btn || !modal || !form) return;

  btn.addEventListener("click", () => _openModal(modal, form, errorEl, groupSelect));

  modal.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", () => _closeModal(modal));
  });

  form.querySelector("#np-enable-mapping").addEventListener("change", () =>
    _toggleMappingFields(form)
  );

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    _submit(form, errorEl);
  });

  // ESC 关闭
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !modal.hidden) _closeModal(modal);
  });
}