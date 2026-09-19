// overview-filter.js：状态/支付筛选 + chip 拖拽排序 + 一键全选/全不选。
//
// 功能：
// - 搜索框（项目编号子串匹配）
// - 状态 chip 筛选（默认全勾）
// - 支付 chip 筛选（默认全勾）
// - chip 拖拽排序（持久化到 localStorage）
// - 一键"全选/全不选"按钮

const STORAGE_KEY = "cgr.statusChipOrder";

function _applyFilters() {
  const idInput = document.getElementById("filter-id");
  const statusFilter = document.getElementById("filter-status");
  const paymentFilter = document.getElementById("filter-payment");
  const counter = document.getElementById("filter-count");

  const q = (idInput?.value || "").trim().toLowerCase();
  const checkedStatuses = new Set();
  statusFilter?.querySelectorAll("input[type=checkbox]:checked").forEach((cb) => {
    checkedStatuses.add(cb.value);
  });
  const checkedPayments = new Set();
  paymentFilter?.querySelectorAll("input[type=checkbox]:checked").forEach((cb) => {
    checkedPayments.add(cb.value);
  });

  let shown = 0, total = 0;
  document.querySelectorAll("#overview-table .overview-row").forEach((tr) => {
    total++;
    const id = (tr.dataset.projectId || "").toLowerCase();
    const rowSt = tr.dataset.status || "";
    const rowPay = tr.dataset.payment || "";
    const match =
      (!q || id.includes(q)) &&
      checkedStatuses.has(rowSt) &&
      checkedPayments.has(rowPay);
    tr.style.display = match ? "" : "none";
    if (match) shown++;
  });
  if (counter) counter.textContent = total === shown ? "" : `显示 ${shown} / ${total}`;
  return { shown, total };
}

function _persistOrder(container) {
  if (!container) return;
  const order = Array.from(container.querySelectorAll(".status-chip"))
    .map((c) => c.querySelector("input")?.value)
    .filter(Boolean);
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(order)); } catch {}
}

function _restoreOrder(container) {
  if (!container) return;
  let saved;
  try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); } catch {}
  if (!Array.isArray(saved)) return;
  const byValue = new Map();
  container.querySelectorAll(".status-chip").forEach((c) => {
    const v = c.querySelector("input")?.value;
    if (v) byValue.set(v, c);
  });
  // 按保存顺序重排 DOM
  saved.forEach((v) => {
    const c = byValue.get(v);
    if (c) container.appendChild(c); // append 会移到末尾
  });
}

function _wireDrag(container) {
  if (!container) return;
  let dragSrc = null;

  container.querySelectorAll(".status-chip").forEach((chip) => {
    chip.setAttribute("draggable", "true");
    chip.addEventListener("dragstart", (e) => {
      dragSrc = chip;
      chip.classList.add("status-chip--dragging");
      // Firefox 需要 setData
      try { e.dataTransfer.setData("text/plain", chip.querySelector("input")?.value || ""); } catch {}
      e.dataTransfer.effectAllowed = "move";
    });
    chip.addEventListener("dragend", () => {
      chip.classList.remove("status-chip--dragging");
      container.querySelectorAll(".status-chip--drop-target").forEach((c) =>
        c.classList.remove("status-chip--drop-target")
      );
      dragSrc = null;
      _persistOrder(container);
    });
    chip.addEventListener("dragover", (e) => {
      if (!dragSrc || dragSrc === chip) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      chip.classList.add("status-chip--drop-target");
    });
    chip.addEventListener("dragleave", () => {
      chip.classList.remove("status-chip--drop-target");
    });
    chip.addEventListener("drop", (e) => {
      e.preventDefault();
      chip.classList.remove("status-chip--drop-target");
      if (!dragSrc || dragSrc === chip) return;
      // 决定插入位置：在 chip 之前还是之后
      const rect = chip.getBoundingClientRect();
      const after = e.clientY > rect.top + rect.height / 2;
      if (after) chip.parentNode.insertBefore(dragSrc, chip.nextSibling);
      else chip.parentNode.insertBefore(dragSrc, chip);
      _applyFilters();
    });
  });
}

function _wireSelectAll(container, btn) {
  if (!container || !btn) return;
  function updateLabel() {
    const boxes = container.querySelectorAll("input[type=checkbox]");
    const checked = container.querySelectorAll("input[type=checkbox]:checked");
    btn.textContent = checked.length === boxes.length && boxes.length > 0
      ? "全不选"
      : "全选";
  }
  updateLabel();
  container.addEventListener("change", updateLabel);
  btn.addEventListener("click", () => {
    const boxes = container.querySelectorAll("input[type=checkbox]");
    const allChecked = boxes.length > 0 &&
      container.querySelectorAll("input[type=checkbox]:checked").length === boxes.length;
    boxes.forEach((cb) => { cb.checked = !allChecked; });
    updateLabel();
    _applyFilters();
  });
}

export function start() {
  const idInput = document.getElementById("filter-id");
  const statusFilter = document.getElementById("filter-status");
  const paymentFilter = document.getElementById("filter-payment");
  const statusAllBtn = document.getElementById("filter-status-all");
  const paymentAllBtn = document.getElementById("filter-payment-all");

  // 恢复排序
  _restoreOrder(statusFilter);
  _restoreOrder(paymentFilter);

  // 拖拽
  _wireDrag(statusFilter);
  _wireDrag(paymentFilter);

  // 全选/全不选
  _wireSelectAll(statusFilter, statusAllBtn);
  _wireSelectAll(paymentFilter, paymentAllBtn);

  // 搜索框
  if (idInput) idInput.addEventListener("input", _applyFilters);

  // 单个 chip 变化
  statusFilter?.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", _applyFilters);
  });
  paymentFilter?.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", _applyFilters);
  });

  _applyFilters();
  // 暴露给 overview-live.js：动态刷新后重新过滤
  window.__cgr_applyFilters = _applyFilters;
}