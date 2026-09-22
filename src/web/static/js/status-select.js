// status-select.js：项目详情页"状态"列的内联编辑下拉框。
//
// 选项来源 GET /api/statuses,首次调用后缓存。
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

export function buildStatusSelect(currentText) {
  const select = document.createElement("select");
  select.className = "field-cell__select";
  const knownValues = new Set();
  let isCurrentKnown = false;
  for (const s of _statusOptionsCache || []) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = `${s.code} — ${s.display}`;
    // display name 放第一个,更醒目
    const seen = new Set();
    const candidates = [s.display, ...s.aliases];
    for (const v of candidates) {
      if (!v || seen.has(v)) continue;
      seen.add(v);
      knownValues.add(v);
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      if (v === currentText) {
        opt.selected = true;
        isCurrentKnown = true;
      }
      optgroup.appendChild(opt);
    }
    select.appendChild(optgroup);
  }
  if (currentText && !isCurrentKnown) {
    const opt = document.createElement("option");
    opt.value = currentText;
    opt.textContent = `(当前未识别) ${currentText}`;
    opt.selected = true;
    select.insertBefore(opt, select.firstChild);
  }
  return select;
}