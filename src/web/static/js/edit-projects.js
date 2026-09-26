// edit-projects.js：编辑群 modal 里的"关联项目"管理(state + 渲染 + 添加/移除)。
//
// state: { chat_id, projects: Set<string> }
// - 打开 modal 时初始化(从 row.dataset.projects 读当前 enabled 的项目)
// - 用户点 × 移除 → 从 Set 删除 + 重渲染
// - 用户从 select 选项目 + 添加 → 加进 Set + 重渲染
// - 保存时由 groups.js 读取 state 转 array,PUT 到后端

let _editState = null;  // null = 未打开 edit modal

export function getEditProjects() {
  return _editState ? Array.from(_editState.projects) : [];
}

export function initEditState(chatId, projectIds) {
  _editState = { chat_id: chatId, projects: new Set(projectIds || []) };
}

export function clearEditState() {
  _editState = null;
}

function _render() {
  const projEl = document.querySelector("#eg-projects-current");
  if (!projEl || !_editState) return;
  projEl.innerHTML = "";
  if (_editState.projects.size === 0) {
    projEl.innerHTML =
      '<span class="groups-row__empty-hint">未关联任何项目(保存后将为空群)</span>';
    return;
  }
  for (const pid of _editState.projects) {
    const chip = document.createElement("span");
    chip.className = "eg-project-chip";
    chip.dataset.projectId = pid;
    const nameMatch = document.querySelector(
      `#eg-projects-add-select option[value="${pid}"]`
    );
    const name = nameMatch ? nameMatch.dataset.projectName : "";
    chip.innerHTML =
      `<a href="/project/${encodeURIComponent(pid)}">${pid}</a>` +
      (name ? ` <span class="eg-project-chip__name">(${name})</span>` : "") +
      ` <button type="button" class="eg-project-chip__remove" title="移除" aria-label="移除 ${pid}">×</button>`;
    chip.querySelector(".eg-project-chip__remove").addEventListener("click", () => {
      _editState.projects.delete(pid);
      _render();
    });
    projEl.appendChild(chip);
  }
}

export function renderEditProjects() {
  _render();
}

export function addProjectToEdit(pid) {
  if (!_editState || !pid || _editState.projects.has(pid)) return;
  _editState.projects.add(pid);
  _render();
}

export function wireAddProjectControl() {
  const addBtn = document.getElementById("eg-projects-add-btn");
  const addSelect = document.getElementById("eg-projects-add-select");
  if (!addBtn || !addSelect) return;
  addBtn.addEventListener("click", () => {
    const pid = addSelect.value;
    if (pid) {
      addProjectToEdit(pid);
      addSelect.value = "";
      addSelect.focus();
    }
  });
}