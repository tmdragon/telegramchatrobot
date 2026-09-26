// page-bootstrap.js：page dispatcher。
// 读 <body data-page="...">，动态 import 对应的 feature module 并调用 init()。
// base 页面（所有页面都挂的）放这里统一 import。

import { mount as mountStatusBar } from "./status-bar.js";
import { start as startAutoRefresh } from "./auto-refresh.js";

// base 模块：状态栏 + 自动刷新（所有页都启用；超时/暂停由 status-bar 控件决定）
mountStatusBar();
startAutoRefresh();

// page-specific 模块：按 data-page 加载
// 注意：mappings 页面的 CRUD JS 处理器不在 Phase 2 范围（T10b 决定）；
// 该页面仅渲染，按钮存在但不响应 —— 无 mapping-crud.js 模块。
const PAGE_MODULES = {
  overview: () => import("./overview-live.js").then(async (m) => {
    m.start();
    const np = await import("./new-project.js");
    np.init();
  }),
  detail: () => import("./inline-edit.js"),
  groups: () => import("./groups.js"),
};

const page = document.body.dataset.page || "overview";
const loader = PAGE_MODULES[page];
if (loader) {
  loader().then((mod) => {
    if (typeof mod.init === "function") mod.init();
  }).catch((err) => {
    console.error("page module load failed", err);
  });
}

// 左导航 active 标记:根据 <body data-page> 高亮当前链接
document.querySelectorAll(".sidebar__link").forEach((el) => {
  if (el.dataset.pageTarget === page) el.classList.add("sidebar__link--active");
});