// overview-live.js：项目管理页动态刷新。
//
// 行为：
// - 每 N 秒（默认 30s）fetch /api/projects
// - 比对上次数据，只更新变化行（status / name / dwell / package）
// - 新项目 → 插入并 fade-in；删除项目 → fade-out 后移除
// - 数据真有变 → 整行闪一下（row-flash 动画）
// - 状态栏 last_refresh 时间由 status-bar 自己维护；这里只 emit 'refresh:done'

import { bus, errors } from "./status-bar.js";

const POLL_MS = 30_000;

/** 当前 DOM 状态：project_id → {status, name, package, dwell_seconds, el} */
const rows = new Map();

function _rowKey(tr) {
  return tr.dataset.projectId;
}

function _rowSnapshot(tr) {
  return {
    status: tr.dataset.status || "",
    name: tr.dataset.name || "",
    package: tr.dataset.package || "",
    dwell_seconds: Number(tr.querySelector("[data-dwell-seconds]")?.dataset.dwellSeconds || 0),
    el: tr,
  };
}

function _initFromDom() {
  document.querySelectorAll("#overview-table .overview-row").forEach((tr) => {
    rows.set(_rowKey(tr), _rowSnapshot(tr));
  });
}

function _formatDwell(sec) {
  if (sec < 60) return `${sec} 秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟`;
  if (sec < 86400) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return m ? `${h} 小时 ${m} 分钟` : `${h} 小时`;
  }
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  return h ? `${d} 天 ${h} 小时` : `${d} 天`;
}

function _badgeHtml(status, rawName) {
  // rawName 来自 API（status.value 或 "NONE"）；保留服务端渲染逻辑
  if (!status) {
    return `<span class="status-badge status-badge--unknown" data-status-code="">
      <span class="status-badge__dot" aria-hidden="true"></span>
      <span class="status-badge__name">未知</span>
    </span>`;
  }
  const slug = String(status).toLowerCase().replace(/_/g, "-");
  return `<span class="status-badge status-badge--${slug}" data-status-code="${status}">
    <span class="status-badge__dot" aria-hidden="true"></span>
    <span class="status-badge__name">${rawName || status}</span>
  </span>`;
}

function _diffRow(tr, fresh) {
  // fresh = {project_id, project_name, status, package_name, dwell_seconds}
  let changed = false;
  if ((tr.dataset.status || "") !== (fresh.status || "")) {
    tr.dataset.status = fresh.status || "NONE";
    const cell = tr.children[2];
    if (cell) cell.innerHTML = _badgeHtml(fresh.status);
    changed = true;
  }
  if ((tr.dataset.name || "") !== (fresh.project_name || "")) {
    tr.dataset.name = fresh.project_name || "";
    const cell = tr.children[1];
    if (cell) {
      cell.innerHTML = fresh.project_name
        ? `<span class="overview-row__name">${_escape(fresh.project_name)}</span>`
        : `<span class="overview-row__name--placeholder">（未命名）</span>`;
    }
    changed = true;
  }
  if ((tr.dataset.package || "") !== (fresh.package_name || "")) {
    tr.dataset.package = fresh.package_name || "";
    changed = true;
  }
  const dwellEl = tr.querySelector("[data-dwell-seconds]");
  if (dwellEl && Number(dwellEl.dataset.dwellSeconds) !== fresh.dwell_seconds) {
    dwellEl.dataset.dwellSeconds = String(fresh.dwell_seconds);
    dwellEl.textContent = _formatDwell(fresh.dwell_seconds);
    changed = true;
  }
  if (changed) {
    tr.classList.remove("overview-row--changed");
    void tr.offsetWidth; // restart animation
    tr.classList.add("overview-row--changed");
  }
}

function _escape(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function _createRow(p) {
  const tr = document.createElement("tr");
  tr.className = "overview-row overview-row--new";
  tr.dataset.projectId = p.project_id;
  tr.dataset.status = p.status || "NONE";
  tr.dataset.name = p.project_name || "";
  tr.dataset.package = p.package_name || "";
  const dwellSec = p.dwell_seconds || 0;
  tr.innerHTML = `
    <td><a href="/project/${_escape(p.project_id)}" class="overview-row__id">${_escape(p.project_id)}</a></td>
    <td>${p.project_name
      ? `<span class="overview-row__name">${_escape(p.project_name)}</span>`
      : `<span class="overview-row__name--placeholder">（未命名）</span>`}</td>
    <td>${_badgeHtml(p.status)}</td>
    <td><span class="overview-row__dwell" data-dwell-seconds="${dwellSec}">${_formatDwell(dwellSec)}</span></td>
    <td style="text-align: right;"><a href="/project/${_escape(p.project_id)}" class="overview-row__view">查看 →</a></td>`;
  return tr;
}

function _applyDiff(freshList) {
  const tbody = document.querySelector("#overview-table tbody");
  if (!tbody) return;
  const freshById = new Map(freshList.map((p) => [p.project_id, p]));
  const seen = new Set();

  // 更新 / 新增行
  for (const p of freshList) {
    seen.add(p.project_id);
    const existing = rows.get(p.project_id);
    if (existing) {
      _diffRow(existing.el, p);
      existing.status = p.status || "";
      existing.name = p.project_name || "";
      existing.package = p.package_name || "";
      existing.dwell_seconds = p.dwell_seconds || 0;
    } else {
      const tr = _createRow(p);
      tbody.appendChild(tr);
      rows.set(p.project_id, _rowSnapshot(tr));
    }
  }

  // 删除消失的行
  for (const [pid, snap] of rows.entries()) {
    if (!seen.has(pid)) {
      snap.el.classList.add("overview-row--removed");
      setTimeout(() => {
        snap.el.remove();
        rows.delete(pid);
      }, 300);
    }
  }

  // 更新项目计数
  const counter = document.querySelector("[data-project-count]");
  if (counter) counter.textContent = String(freshList.length);
}

async function _tick() {
  try {
    const r = await fetch("/api/projects", { headers: { "Accept": "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const list = (data.projects || []).map((p) => ({
      project_id: p.project_id,
      project_name: p.project_name,
      status: p.status,
      package_name: p.package_name,
      dwell_seconds: p.dwell_seconds,
    }));
    _applyDiff(list);
    bus.dispatchEvent(new CustomEvent("refresh:done", { detail: data }));
  } catch (e) {
    errors.bump(`overview refresh failed: ${e.message}`);
  }
}

export function start() {
  _initFromDom();
  setInterval(_tick, POLL_MS);
  // 手动刷新完成时立即拉一次（不等 poll）
  document.addEventListener("cgr:trigger-refresh", _tick);
}