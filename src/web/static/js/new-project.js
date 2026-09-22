// new-project.js：新增项目 modal 控制（打开/关闭/提交）。
//
// 流程：
// 1. 点击 "+ 新增项目" 按钮 → 打开 modal
// 2. modal 打开时加载已有群列表（GET /api/groups），填充 <select>
// 3. modal 打开时加载 info 字段列表（GET /api/projects/new-form-fields），渲染可选 inputs
// 4. 用户填写表单 → POST /api/projects（见 form-submit.js）
// 5. 成功后刷新页面
//
// 智能默认值（包名→类名、GP→商店地址）见 smart-defaults.js。

import { submitNewProject } from "./form-submit.js";
import { wireSmartDefaults } from "./smart-defaults.js";

let _groups = []; // [{chat_id, note}, ...] 从 GET /api/groups 缓存
let _infoFields = []; // [{key, label, header}, ...] 从 GET /api/projects/new-form-fields 缓存

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

async function _loadInfoFields(container) {
  try {
    const r = await fetch("/api/projects/new-form-fields", {
      headers: { Accept: "application/json" },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    _infoFields = data.info_fields || [];
  } catch (e) {
    console.warn("load info fields failed:", e);
    _infoFields = [];
  }
  _renderInfoFields(container);
}

function _renderInfoFields(container) {
  container.innerHTML = "";
  if (!_infoFields.length) {
    const empty = document.createElement("div");
    empty.className = "form-info-fields__empty";
    empty.textContent = "当前 master 表头中没有可选的 info 字段";
    container.appendChild(empty);
    return;
  }
  for (const f of _infoFields) {
    const row = document.createElement("div");
    row.className = "form-row";
    const label = document.createElement("label");
    label.className = "form-row__label";
    label.setAttribute("for", `np-info-${f.key}`);
    label.textContent = f.label;
    const input = document.createElement("input");
    input.id = `np-info-${f.key}`;
    input.name = f.key;
    input.type = "text";
    input.dataset.infoKey = f.key;
    input.placeholder = f.header;
    input.autocomplete = "off";
    row.appendChild(label);
    row.appendChild(input);
    container.appendChild(row);
  }
}

function _openModal(modal, form, errorEl, groupSelect) {
  form.reset();
  errorEl.hidden = true;
  errorEl.textContent = "";
  // 重置 user-modified 标记（reset 不会清 data-* 标记）
  form.querySelectorAll("input[data-user-modified]").forEach((el) => {
    delete el.dataset.userModified;
  });
  // 隐藏 mapping 子区
  const mappingFields = form.querySelector("#np-mapping-fields");
  const enableMapping = form.querySelector("#np-enable-mapping");
  enableMapping.checked = false;
  mappingFields.hidden = true;
  modal.hidden = false;
  modal.setAttribute("aria-hidden", "false");
  _loadGroups(groupSelect);
  // 加载 info 字段（按 master 表头动态渲染）
  const infoContainer = form.querySelector("#np-info-fields");
  if (infoContainer) _loadInfoFields(infoContainer);
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

  // 智能默认：包名→类名；GP→商店地址
  wireSmartDefaults(form);

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    submitNewProject(form, errorEl);
  });

  // ESC 关闭
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !modal.hidden) _closeModal(modal);
  });
}