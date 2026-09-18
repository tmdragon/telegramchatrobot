// status-badge.js：与 src/web/filters.py:STATUS_DISPLAY 严格对齐的 JS 版。
// 单一事实源：Phase 1 的 StatusCode 枚举（src/models/status.py）。
// 此处手写 14 项是因为 ES module 没有直接 import Python 数据的途径。

export const STATUS_META = {
  ORDERED:               { modifier: "ordered",        displayName: "对方下单" },
  MAKING:                { modifier: "making",         displayName: "我方制作中" },
  CLIENT_REVIEW:         { modifier: "client-review",  displayName: "对方验收中" },
  REWORK:                { modifier: "rework",         displayName: "返工中" },
  WAITING_AAB:           { modifier: "waiting-aab",    displayName: "等待AAB包" },
  WAITING_SUBMIT:        { modifier: "waiting-submit", displayName: "等待提审" },
  SUBMITTING:            { modifier: "submitting",     displayName: "提审中" },
  FIRST_REVIEW_PASSED:   { modifier: "first-passed",   displayName: "一审通过" },
  FIRST_REVIEW_REJECTED: { modifier: "first-rejected", displayName: "一审打回" },
  SECOND_REVIEW:         { modifier: "second-review",  displayName: "复审中" },
  REMAKING:              { modifier: "remaking",       displayName: "我方重做中" },
  PUBLISHED:             { modifier: "published",      displayName: "已发布" },
  PAID:                  { modifier: "paid",           displayName: "对方已回款" },
  UNPAID:                { modifier: "unpaid",         displayName: "对方未回款" },
};

export function renderBadge(code, raw) {
  const meta = code ? STATUS_META[code] : null;
  if (meta) {
    return (
        `<span class="status-badge status-badge--${meta.modifier}" data-status-code="${code}">`
      + `<span class="status-badge__dot" aria-hidden="true"></span>`
      + `<span class="status-badge__name">${meta.displayName}</span>`
      + `</span>`
    );
  }
  const text = raw || "未知";
  return (
      `<span class="status-badge status-badge--unknown" data-status-code="">`
    + `<span class="status-badge__dot" aria-hidden="true"></span>`
    + `<span class="status-badge__name">${text}</span>`
    + `</span>`
  );
}