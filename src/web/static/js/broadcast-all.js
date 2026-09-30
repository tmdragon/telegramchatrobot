// broadcast-all.js：一键广播所有客户群(POST /api/broadcast/all)。
//
// 流程:点 #btn-broadcast-all → confirmDialog → 调用 API → alert 结果。

import { postJson } from "./api.js";
import { confirmDialog } from "./confirm-dialog.js";

const CONFIRM_MSG =
  "一键广播所有客户群?\n\n" +
  "会把每个项目的当前状态发到该项目的对应群。\n" +
  "这是个比较大的操作,请确认后再点确定。";

export async function broadcastAll() {
  const ok = await confirmDialog(CONFIRM_MSG);
  if (!ok) return;
  const btn = document.getElementById("btn-broadcast-all");
  const original = btn ? btn.textContent : null;
  if (btn) { btn.disabled = true; btn.textContent = "广播中…"; }
  try {
    const r = await postJson("/api/broadcast/all", {});
    alert(
      `广播完成\n` +
      `成功: ${r.sent ?? 0}  跳过: ${r.skipped ?? 0}  失败: ${r.failed ?? 0}`
    );
  } catch (e) {
    alert(`广播失败: ${e.detail || e.message}`);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
}