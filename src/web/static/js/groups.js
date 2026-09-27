// groups.js：/groups 群映射管理页的 CRUD 控制。
//
// 流程：
// 1. "+ 新建群" → modal → POST /api/groups/manage
// 2. 行内"编辑" → modal → PUT /api/groups/manage/{chat_id}(note/enabled)
//    + PUT /api/groups/manage/{chat_id}/projects(关联项目列表)
// 3. 行内"停用" → confirmDialog → DELETE /api/groups/manage/{chat_id}
// 4. 行内"测试" → POST /api/groups/manage/{chat_id}/test-send
//
// 关联项目子逻辑在 edit-projects.js

import { postJson, putJson, delJson } from "./api.js";
import { confirmDialog } from "./confirm-dialog.js";
import {
  initEditState,
  renderEditProjects,
  getEditProjects,
  wireAddProjectControl,
} from "./edit-projects.js";
import { filterSelectOptions, wireSearchInput } from "./select-filter.js";

function _openNewGroupModal(modal, form) {
  _clearError(form);
  form.reset();
  const select = form.querySelector("#ng-project-id");
  if (select) filterSelectOptions(select, "");
  _openModal(modal);
  form.querySelector("#ng-chat-id").focus();
}

function _closeModal(modal) {
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
}

function _clearError(form) {
  const err = form.parentElement.querySelector(".form-error");
  if (err) { err.hidden = true; err.textContent = ""; }
}

function _showError(form, msg) {
  const err = form.parentElement.querySelector(".form-error");
  if (err) { err.hidden = false; err.textContent = msg; return; }
  alert(msg);
}

async function _submitNewGroup(form) {
  const fd = new FormData(form);
  const body = {
    chat_id: (fd.get("chat_id") || "").trim(),
    project_id: (fd.get("project_id") || "").trim(),
    note: (fd.get("note") || "").trim(),
    enabled: true,
  };
  if (!body.chat_id) {
    _showError(form, "chat_id 不能为空(项目可选)");
    return;
  }
  const btn = form.querySelector("#ng-submit");
  btn.disabled = true;
  btn.textContent = "保存中...";
  try {
    await postJson("/api/groups/manage", body);
    window.location.reload();
  } catch (e) {
    _showError(form, `保存失败: ${e.detail || e.message}`);
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

function _openEditModal(row, modal, form) {
  const chatId = row.dataset.chatId;
  form.querySelector("#eg-chat-id").textContent = chatId;
  form.querySelector("#eg-note").value = row.dataset.note || "";
  form.querySelector("#eg-enabled").checked = (row.dataset.enabledState === "all");
  const projects = (row.dataset.projects || "").split(",").filter(Boolean);
  initEditState(chatId, projects);
  renderEditProjects();
  _clearError(form);
  _openModal(modal);
}

async function _submitEditGroup(form) {
  const chatId = form.querySelector("#eg-chat-id").textContent.trim();
  const body = {
    note: (form.querySelector("#eg-note").value || "").trim(),
    enabled: form.querySelector("#eg-enabled").checked,
  };
  const btn = form.querySelector("#eg-submit");
  btn.disabled = true;
  btn.textContent = "保存中...";
  try {
    // 1. 更新 note + enabled
    await putJson(`/api/groups/manage/${encodeURIComponent(chatId)}`, body);
    // 2. 同步关联项目
    await putJson(`/api/groups/manage/${encodeURIComponent(chatId)}/projects`, {
      project_ids: getEditProjects(),
    });
    window.location.reload();
  } catch (e) {
    _showError(form, `保存失败: ${e.detail || e.message}`);
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

async function _deleteGroup(chatId) {
  try {
    await delJson(`/api/groups/manage/${encodeURIComponent(chatId)}`);
    window.location.reload();
  } catch (e) {
    alert(`停用失败: ${e.detail || e.message}`);
  }
}

async function _testSend(chatId) {
  try {
    const r = await postJson(
      `/api/groups/manage/${encodeURIComponent(chatId)}/test-send`,
      {}
    );
    alert(r.message_preview || `已发送: ${chatId}`);
  } catch (e) {
    alert(`测试发送失败: ${e.detail || e.message}`);
  }
}

export function init() {
  const newBtn = document.getElementById("btn-new-group");
  const newModal = document.getElementById("new-group-modal");
  const newForm = document.getElementById("new-group-form");
  const editModal = document.getElementById("edit-group-modal");
  const editForm = document.getElementById("edit-group-form");
  if (!newBtn || !newModal || !newForm) return;

  newBtn.addEventListener("click", () => _openNewGroupModal(newModal, newForm));
  wireSearchInput("ng-project-search", "ng-project-id");

  document.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", () => {
      if (!newModal.hidden) _closeModal(newModal);
      if (editModal && !editModal.hidden) _closeModal(editModal);
    });
  });

  newForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    _submitNewGroup(newForm);
  });
  if (editForm) {
    editForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      _submitEditGroup(editForm);
    });
  }

  // 编辑群:添加项目按钮
  wireAddProjectControl();

  // 行内按钮(委托)
  const tbody = document.querySelector("[data-groups-tbody]");
  if (tbody) {
    tbody.addEventListener("click", async (ev) => {
      const btn = ev.target.closest("button[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      const chatId = btn.dataset.chatId;
      const row = btn.closest(".groups-row");
      if (action === "group-edit" && row && editModal && editForm) {
        _openEditModal(row, editModal, editForm);
      } else if (action === "group-delete") {
        const ok = await confirmDialog(`停用群 ${chatId}(该 chat_id 下所有映射会被设为停用)?`);
        if (ok) await _deleteGroup(chatId);
      } else if (action === "group-test-send") {
        await _testSend(chatId);
      }
    });
  }

  // ESC 关闭任意打开的 modal
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      if (!newModal.hidden) _closeModal(newModal);
      if (editModal && !editModal.hidden) _closeModal(editModal);
    }
  });
}