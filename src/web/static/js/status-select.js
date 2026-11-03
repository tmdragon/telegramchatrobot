// status-select.js：项目详情页"状态"列的内联编辑下拉框。
//
// 选项来源 GET /api/statuses,首次调用后缓存。
// 一个状态只显示一项(中文显示名),不再把每个别名都列成选项——13 个状态
// 原本会撑成 55 行,没法用。
// 当前 cell 值不在任何已知 alias 里时,顶部加一条"(当前未识别)"保留原值,免得丢。

let _statusOptionsCache = null;
let _statusOptionsPromise = null;

export async function loadStatusOptions() {
  if (_statusOptionsCache) return _statusOptionsCache;
  if (_statusOptionsPromise) return _statusOptionsPromise;
  _statusOptionsPromise = (async () => {
    try {
      const r = await fetch("/api/statuses", { headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      _statusOptionsCache = data.statuses || [];
    } catch (e) {
      console.warn("load status options failed:", e);
      _statusOptionsCache = [];
    }
    return _statusOptionsCache;
  })();
  return _statusOptionsPromise;
}

/**
 * 判断一段文本属于哪个状态。
 *
 * 识别规则与后端 normalize() 对齐：
 * - 精确等于状态码(如 "PUBLISHED")
 * - 精确等于中文显示名(如 "已发布")
 * - 命中该状态的任一别名(如 "上架"、"已上架")
 *
 * @param {string} currentText cell 里的原始文本
 * @param {Array} statuses /api/statuses 返回的数组
 * @returns {{code: string, display: string, raw: string}|null} 匹配不到返回 null
 */
export function matchStatus(currentText, statuses) {
  const text = (currentText || "").trim();
  if (!text) return null;
  for (const s of statuses || []) {
    const display = s.display || s.code;
    const code = (s.code || "").toUpperCase();
    const hit =
      text === display ||
      text.toUpperCase() === code ||
      (s.aliases || []).includes(text);
    if (hit) return { code: s.code, display, raw: text };
  }
  return null;
}

export function buildStatusSelect(currentText) {
  const select = document.createElement("select");
  select.className = "field-cell__select";
  const statuses = _statusOptionsCache || [];
  const matched = matchStatus(currentText, statuses);
  for (const s of statuses) {
    const display = s.display || s.code;
    const isCurrent = !!matched && matched.code === s.code;
    const opt = document.createElement("option");
    // 值：当前 cell 原文属于这个状态时保留原文——点 OK 不会把 sheet 里的
    // 别名悄悄改写掉；不属于时用规范显示名。
    opt.value = isCurrent ? matched.raw : display;
    opt.textContent = display;
    if (isCurrent) opt.selected = true;
    select.appendChild(opt);
  }
  if (currentText && !matched) {
    const opt = document.createElement("option");
    opt.value = currentText;
    opt.textContent = `(当前未识别) ${currentText}`;
    opt.selected = true;
    select.insertBefore(opt, select.firstChild);
  }
  return select;
}
