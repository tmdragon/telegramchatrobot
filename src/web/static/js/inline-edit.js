// inline-edit.js：内联编辑（事件委托在 .sheet-section）。
//
// 关键：委托目标必须是稳定的祖先（.sheet-section），绝对不能挂在 innerHTML 会被替换的子树上。
// auto-refresh 替换子树时，挂在子树上的 listener 会被 GC；只有稳定祖先上的 listener 才会存活。
//
// 状态列(recognized_as="status")特殊处理:点编辑时渲染 <select> 而不是 <input>,
// 选项来自 GET /api/statuses(见 status-select.js)。

import { putJson, ApiError } from "./api.js";
import { errors } from "./status-bar.js";
import { buildStatusSelect, loadStatusOptions } from "./status-select.js";

const LOCKED_RECOGNIZED_AS = new Set(["project_id"]);
const FIELD_ID_KEY = "field-id";
const ORIGINAL_KEY = "data-original";
const SELECTOR_EDITABLE = ".field-cell[data-editable]";
const SELECTOR_SECTION = ".sheet-section";
const STATUS_RECOGNIZED = "status";

function _encodeFieldId(raw) {
  // 服务端期望 {spreadsheet_name}::{sheet_name}::{row}::{col}
  return encodeURIComponent(raw);
}

function _isLocked(cell) {
  return LOCKED_RECOGNIZED_AS.has(cell.dataset.recognizedAs);
}

function _isStatusCell(cell) {
  return cell.dataset.recognizedAs === STATUS_RECOGNIZED;
}

function _newValueFromCell(cell) {
  // 优先取 select/input,否则 fallback 到 display 文本
  const editable = cell.querySelector(".field-cell__select, .field-cell__input");
  if (editable) return editable.value;
  const display = cell.querySelector(".field-cell__display");
  return display ? display.textContent : "";
}

async function _commit(cell) {
  const tr = cell.closest(".sheet-row");
  if (!tr) return;
  const fieldId = tr.dataset.fieldId;
  const projectId = document.querySelector("[data-project-id]")?.dataset.projectId;
  if (!fieldId || !projectId) return;

  const newValue = _newValueFromCell(cell);
  const originalValue = tr.getAttribute(ORIGINAL_KEY) || "";

  // 乐观更新
  cell.classList.remove("field-cell--editing");
  const display = cell.querySelector(".field-cell__display");
  if (display) {
    display.textContent = newValue;
    display.style.display = "";
  }
  cell.querySelectorAll(".field-cell__select, .field-cell__input").forEach((n) => n.remove());
  cell.querySelectorAll(".field-cell__actions").forEach((n) => n.remove());
  tr.setAttribute(ORIGINAL_KEY, newValue);

  try {
    await putJson(`/api/projects/${encodeURIComponent(projectId)}/fields/${_encodeFieldId(fieldId)}`, { new_value: newValue });
    cell.classList.remove("field-cell--error");
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      if (display) display.textContent = originalValue;
      tr.setAttribute(ORIGINAL_KEY, originalValue);
      cell.classList.add("field-cell--error");
      cell.title = `WriteVerificationError: ${e.detail || ""}`;
      errors.bump(`field edit failed: ${e.detail || e.message}`);
    } else if (e instanceof ApiError && e.status === 400) {
      cell.classList.add("field-cell--error");
      cell.title = `Locked / invalid: ${e.detail || ""}`;
      errors.bump(`field edit rejected: ${e.detail || e.message}`);
      if (display) display.textContent = originalValue;
    } else {
      cell.classList.add("field-cell--error");
      cell.title = `Error: ${e.message}`;
      errors.bump(`field edit error: ${e.message}`);
      if (display) display.textContent = originalValue;
    }
  }
}

function _cancel(cell) {
  cell.classList.remove("field-cell--editing");
  const display = cell.querySelector(".field-cell__display");
  if (display) display.style.display = "";
  cell.querySelectorAll(".field-cell__select, .field-cell__input").forEach((n) => n.remove());
  cell.querySelectorAll(".field-cell__actions").forEach((n) => n.remove());
}

function _wireActions(cell, ok, cancel, editable) {
  ok.addEventListener("click", (ev) => { ev.stopPropagation(); _commit(cell); });
  cancel.addEventListener("click", (ev) => { ev.stopPropagation(); _cancel(cell); });
  editable.addEventListener("click", (ev) => ev.stopPropagation());
  editable.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); _commit(cell); }
    else if (ev.key === "Escape") { ev.preventDefault(); _cancel(cell); }
  });
}

function _buildActions() {
  const actions = document.createElement("span");
  actions.className = "field-cell__actions";
  const ok = document.createElement("button");
  ok.textContent = "OK";
  ok.title = "确认";
  const cancel = document.createElement("button");
  cancel.textContent = "Cancel";
  cancel.title = "取消";
  actions.append(ok, cancel);
  return { actions, ok, cancel };
}

async function _enterEdit(cell) {
  if (cell.classList.contains("field-cell--editing")) return;
  if (_isLocked(cell)) return;

  cell.classList.add("field-cell--editing");
  const display = cell.querySelector(".field-cell__display");
  const currentText = display ? display.textContent : "";
  if (display) display.style.display = "none";

  let editable;
  if (_isStatusCell(cell)) {
    // 状态列:渲染下拉框(选项来自 status-select.js)
    await loadStatusOptions();
    editable = buildStatusSelect(currentText);
  } else {
    // 其他列:文本输入框
    editable = document.createElement("input");
    editable.type = "text";
    editable.value = currentText;
    editable.className = "field-cell__input";
  }

  const { actions, ok, cancel } = _buildActions();
  cell.append(editable, actions);
  _wireActions(cell, ok, cancel, editable);
  editable.focus();
  if (editable.tagName === "INPUT") editable.select();
}

export function init() {
  // 委托到稳定的祖先 .sheet-section —— 不会被 innerHTML 替换
  const sections = document.querySelectorAll(SELECTOR_SECTION);
  sections.forEach((section) => {
    section.addEventListener("click", (ev) => {
      const target = ev.target;
      if (!(target instanceof Element)) return;
      const editing = section.querySelector(".field-cell--editing");
      if (editing) {
        if (target instanceof Element && !editing.contains(target)) {
          if (target.closest(SELECTOR_EDITABLE) && target.closest(SELECTOR_EDITABLE) !== editing) {
            _cancel(editing);
          } else if (!target.closest(SELECTOR_EDITABLE)) {
            _cancel(editing);
          }
        }
      }
      const cell = target.closest(SELECTOR_EDITABLE);
      if (!cell) return;
      if (cell.classList.contains("field-cell--editing")) return;
      _enterEdit(cell);
    });
  });
}