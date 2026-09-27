// select-filter.js：通用的 <select> 实时过滤 utility。
//
// 用法:
//   const search = document.getElementById("my-search");
//   const select = document.getElementById("my-select");
//   search.addEventListener("input", () => filterSelectOptions(select, search.value));

export function filterSelectOptions(select, query) {
  const q = (query || "").toLowerCase().trim();
  let firstVisible = null;
  for (const opt of select.options) {
    if (!opt.value) continue;  // 占位 option 始终保留
    // 匹配:option.value + 任意 data-* 属性
    const hay = [opt.value, opt.dataset.projectName || "", opt.dataset.packageName || ""]
      .join(" ")
      .toLowerCase();
    const visible = !q || hay.includes(q);
    opt.hidden = !visible;
    if (visible && firstVisible === null) firstVisible = opt;
  }
  if (firstVisible) select.value = firstVisible.value;
  else select.value = "";
}

// 给指定 select 绑一个搜索 input,实时过滤
export function wireSearchInput(searchInputId, selectId) {
  const searchInput = document.getElementById(searchInputId);
  const select = document.getElementById(selectId);
  if (!searchInput || !select) return;
  searchInput.addEventListener("input", () => {
    filterSelectOptions(select, searchInput.value);
  });
  searchInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      if (select.value) select.focus();
    }
  });
}