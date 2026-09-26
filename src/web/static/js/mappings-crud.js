// mappings-crud.js：/mappings 页面行内 CRUD(编辑/删除/测试发送)+ 新增 modal。
//
// 用 /api/mappings/{project_id} (PUT/DELETE) 和 /api/mappings/{project_id}/test-send (POST)。
// 编辑/新增共用 partials/_mapping_modal.html。

import { putJson, delJson, postJson } from "./api.js";
import { confirmDialog } from "./confirm-dialog.js";

function _openModal(modal) {
  modal.hidden = false;
  modal.setAttribute("aria-hidden", "false");
}

function _closeModal(modal) {
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
}

function _fillModal(row) {
  const modal = document.getElementById("mapping-modal");
  if (!modal) return;
  const title = modal.querySelector("[data-modal-title]");
  const form = modal.querySelector("[data-modal-form]");
  if (title) title.textContent = `编辑映射 — ${row.dataset.projectId}`;
  if (form) {
    form.querySelector('[data-field="project_id"]').value = row.dataset.projectId || "";
    form.querySelector('[data-field="chat_id"]').value = row.dataset.chatId || "";
    form.querySelector('[data-field="note"]').value = row.dataset.note || "";
    form.querySelector('[data-field="enabled"]').checked = row.dataset.enabled === "1";
    // 清掉上一个 modal 可能残留的 error
    const err = form.parentElement.querySelector(".form-error");
    if (err) { err.hidden = true; err.textContent = ""; }
  }
  _openModal(modal);
}

async function _submitEdit() {
  const modal = document.getElementById("mapping-modal");
  const form = modal.querySelector("[data-modal-form]");
  const projectId = form.querySelector('[data-field="project_id"]').value.trim();
  const body = {
    chat_id: form.querySelector('[data-field="chat_id"]').value.trim(),
    note: form.querySelector('[data-field="note"]').value.trim(),
    enabled: form.querySelector('[data-field="enabled"]').checked,
  };
  const submitBtn = form.querySelector('[data-action="modal-submit"]');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "保存中..."; }
  try {
    await putJson(`/api/mappings/${encodeURIComponent(projectId)}`, body);
    window.location.reload();
  } catch (e) {
    const err = form.parentElement.querySelector(".form-error");
    if (err) { err.hidden = false; err.textContent = `保存失败: ${e.detail || e.message}`; }
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "保存"; }
  }
}

async function _deleteMapping(projectId) {
  const ok = await confirmDialog(`删除项目 ${projectId} 的映射?`);
  if (!ok) return;
  try {
    await delJson(`/api/mappings/${encodeURIComponent(projectId)}`);
    window.location.reload();
  } catch (e) {
    alert(`删除失败: ${e.detail || e.message}`);
  }
}

async function _testSend(projectId) {
  try {
    const r = await postJson(
      `/api/mappings/${encodeURIComponent(projectId)}/test-send`,
      {}
    );
    alert(r.message_preview || `已发送: ${projectId}`);
  } catch (e) {
    alert(`测试发送失败: ${e.detail || e.message}`);
  }
}

export function init() {
  const tbody = document.querySelector("[data-mappings-tbody]");
  const modal = document.getElementById("mapping-modal");
  const addBtn = document.querySelector("[data-action='mapping-add']");
  const form = modal ? modal.querySelector("[data-modal-form]") : null;

  // 关闭按钮
  document.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", () => { if (modal) _closeModal(modal); });
  });

  if (form) {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      _submitEdit();
    });
  }

  // 取消按钮:只是关闭
  const cancelBtn = modal && modal.querySelector('[data-action="modal-cancel"]');
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => { if (modal) _closeModal(modal); });
  }

  // 新增按钮:打开空 modal 让用户填
  if (addBtn && modal && form) {
    addBtn.addEventListener("click", () => {
      const title = modal.querySelector("[data-modal-title]");
      if (title) title.textContent = "新增映射";
      form.reset();
      const err = form.parentElement.querySelector(".form-error");
      if (err) { err.hidden = true; err.textContent = ""; }
      _openModal(modal);
    });
  }

  // 行内按钮(委托)
  if (tbody) {
    tbody.addEventListener("click", async (ev) => {
      const btn = ev.target.closest("button[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      const projectId = btn.dataset.projectId;
      const row = btn.closest(".mappings-row");
      if (action === "mapping-edit" && row) {
        _fillModal(row);
      } else if (action === "mapping-delete") {
        await _deleteMapping(projectId);
      } else if (action === "test-send") {
        await _testSend(projectId);
      }
    });
  }
}