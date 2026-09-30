// broadcast-all.js：/groups 页面的"一键广播"modal 控制。
//
// 流程:
// 1. 点 #btn-broadcast-all → 打开 modal
// 2. 点节日 chip → 填充预设祝福语(可继续编辑)
// 3. 点"发送到所有群" → confirmDialog → POST /api/broadcast/custom → alert 结果

import { postJson } from "./api.js";
import { confirmDialog } from "./confirm-dialog.js";

// 节日预设祝福语(简洁版,可继续编辑)
const PRESETS = {
  spring: "🎊 新春快乐!\n祝您和家人新年大吉,万事如意,身体健康,阖家幸福! 🧧",
  midautumn: "🌕 中秋节快乐!\n月圆人团圆,祝您阖家幸福,工作顺利! 🥮",
  lantern: "🏮 元宵节快乐!\n祝您和家人团团圆圆,幸福安康! 🏮",
  dragon: "🐉 端午安康!\n祝您和家人端午快乐,工作顺利! 🍃",
  national: "🇨🇳 国庆节快乐!\n祝您和家人假期愉快,工作顺利,祖国繁荣昌盛! 🎉",
  newyear: "🎆 元旦快乐!\n祝您和家人新年新气象,事业蒸蒸日上! ✨",
  xmas: "🎄 圣诞快乐!\n祝您和家人节日快乐,平安喜乐! 🎅",
  custom: "",  // 占位:不预填,用户自己写
};

function _openModal(modal) {
  modal.hidden = false;
  modal.setAttribute("aria-hidden", "false");
}

function _closeModal(modal) {
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
}

function _clearError(form) {
  const err = form.parentElement.querySelector(".form-error");
  if (err) { err.hidden = true; err.textContent = ""; }
}

function _showError(form, msg) {
  const err = form.parentElement.querySelector(".form-error");
  if (err) { err.hidden = false; err.textContent = msg; return; }
  alert(msg);
}

function _applyPreset(textarea, key) {
  textarea.value = PRESETS[key] ?? "";
  textarea.focus();
}

async function _submitBroadcast(form, content) {
  const btn = form.querySelector("#broadcast-submit");
  btn.disabled = true;
  btn.textContent = "发送中…";
  try {
    const r = await postJson("/api/broadcast/custom", { content });
    alert(
      `广播完成\n` +
      `成功: ${r.sent ?? 0}  失败: ${r.failed ?? 0}  共计: ${r.total ?? 0}`
    );
    return true;
  } catch (e) {
    _showError(form, `广播失败: ${e.detail || e.message}`);
    return false;
  } finally {
    btn.disabled = false;
    btn.textContent = "📨 发送到所有群";
  }
}

export function initBroadcastModal() {
  const btn = document.getElementById("btn-broadcast-all");
  const modal = document.getElementById("broadcast-modal");
  const form = document.getElementById("broadcast-form");
  if (!btn || !modal || !form) return;

  const textarea = form.querySelector("#broadcast-content");

  btn.addEventListener("click", () => {
    _clearError(form);
    form.reset();
    if (textarea) textarea.value = "";
    _openModal(modal);
    if (textarea) textarea.focus();
  });

  modal.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", () => _closeModal(modal));
  });

  // 节日预设按钮
  modal.querySelectorAll("[data-preset]").forEach((el) => {
    el.addEventListener("click", () => {
      if (textarea) _applyPreset(textarea, el.dataset.preset);
    });
  });

  // 提交
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const content = (textarea ? textarea.value : "").trim();
    if (!content) {
      _showError(form, "请先输入广播内容(可点上方节日按钮)");
      return;
    }
    const ok = await confirmDialog(
      `确认向所有启用的客户群发送以下内容?\n\n${content}`
    );
    if (!ok) return;
    const done = await _submitBroadcast(form, content);
    if (done) _closeModal(modal);
  });

  // ESC 关闭
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !modal.hidden) _closeModal(modal);
  });
}