// page-bootstrap.js：page dispatcher。
// 读 <body data-page="...">，动态 import 对应的 feature module 并调用 init()。
// base 页面（所有页面都挂的）放这里统一 import。

import { mount as mountStatusBar } from "./status-bar.js";
import { start as startAutoRefresh } from "./auto-refresh.js";

// base 模块：状态栏 + 自动刷新（所有页都启用；超时/暂停由 status-bar 控件决定）
mountStatusBar();
startAutoRefresh();

// page-specific 模块：按 data-page 加载
const PAGE_MODULES = {
  detail: () => import("./inline-edit.js"),
  mappings: () => import("./mapping-crud.js"),
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