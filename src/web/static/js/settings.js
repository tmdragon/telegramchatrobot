// settings.js：/settings 页面的两个 section 提交(在架监控 + 结算信息)。

import { getJson, putJson, delJson } from "./api.js";

// === 结算信息(全局) ===

function _showPayOk(msg) {
  const el = document.getElementById("pay-success");
  if (el) { el.hidden = false; el.textContent = msg; }
}
function _showPayErr(msg) {
  const el = document.getElementById("pay-error");
  if (el) { el.hidden = false; el.textContent = msg; }
  else alert(msg);
}
function _clearPayMsg() {
  for (const id of ["pay-success", "pay-error"]) {
    const el = document.getElementById(id);
    if (el) { el.hidden = true; el.textContent = ""; }
  }
}

async function _submitPayment(form, btn) {
  const fileInput = form.querySelector("#pay-qr");
  const walletInput = form.querySelector("#pay-wallet");
  if (!fileInput.files || fileInput.files.length === 0) {
    _showPayErr("请先选择二维码图片");
    return;
  }
  const wallet = walletInput.value.trim();
  if (!wallet) {
    _showPayErr("钱包地址不能为空");
    return;
  }
  const fd = new FormData();
  fd.append("qr", fileInput.files[0]);
  fd.append("wallet_address", wallet);

  btn.disabled = true;
  btn.textContent = "上传中…";
  try {
    const r = await fetch("/api/payment", {
      method: "PUT",
      body: fd,
      headers: { Accept: "application/json" },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    _showPayOk("✓ 结算信息已保存(Telegram 已存储图片)");
    setTimeout(() => window.location.reload(), 800);
  } catch (e) {
    _showPayErr(`保存失败: ${e.message}`);
    btn.disabled = false;
    btn.textContent = "💾 保存结算信息";
  }
}

async function _deletePayment(btn) {
  if (!window.confirm("确认删除全局结算信息?(不删 Telegram 图片,只是不再引用)")) return;
  btn.disabled = true;
  try {
    await delJson("/api/payment");
    _showPayOk("✓ 已删除");
    setTimeout(() => window.location.reload(), 600);
  } catch (e) {
    _showPayErr(`删除失败: ${e.message}`);
    btn.disabled = false;
  }
}

function _wirePaymentSection() {
  const form = document.getElementById("pay-form");
  if (!form) return;
  const saveBtn = form.querySelector("#pay-save");
  const deleteBtn = form.querySelector("#pay-delete");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    _clearPayMsg();
    _submitPayment(form, saveBtn);
  });
  // 如果已配置,显示删除按钮
  const current = document.getElementById("pay-current");
  if (current && current.querySelector(".pay-current__info")) {
    if (deleteBtn) deleteBtn.hidden = false;
    if (deleteBtn) deleteBtn.addEventListener("click", () => _deletePayment(deleteBtn));
  }
}

// === 在架监控配置(原有功能) ===

function _showOk(msg) {
  const el = document.getElementById("cfg-success");
  if (el) { el.hidden = false; el.textContent = msg; }
}
function _showErr(msg) {
  const el = document.getElementById("cfg-error");
  if (el) { el.hidden = false; el.textContent = msg; }
  else alert(msg);
}
function _clearMsg() {
  for (const id of ["cfg-success", "cfg-error"]) {
    const el = document.getElementById(id);
    if (el) { el.hidden = true; el.textContent = ""; }
  }
}

async function _populate() {
  try {
    const r = await getJson("/api/config/online-check");
    document.getElementById("cfg-interval").value = r.online_check_interval_hours;
    document.getElementById("cfg-max-attempts").value = r.online_check_max_attempts;
    document.getElementById("cfg-retry-interval").value = r.online_check_retry_interval_minutes;
    document.getElementById("cfg-proxy-api").value = r.online_check_proxy_api_url || "";
    document.getElementById("cfg-default-country").value = r.online_check_default_country || "";
  } catch (e) {
    _showErr(`加载配置失败: ${e.detail || e.message}`);
  }
}

async function _submit(form, btn) {
  const body = {
    online_check_interval_hours: parseInt(form.cfg_interval.value, 10),
    online_check_max_attempts: parseInt(form.cfg_max_attempts.value, 10),
    online_check_retry_interval_minutes: parseInt(form.cfg_retry_interval.value, 10),
    online_check_proxy_api_url: (form.cfg_proxy_api.value || "").trim(),
    online_check_default_country: (form.cfg_default_country.value || "").trim(),
  };
  // 简单校验
  if (body.online_check_interval_hours < 1 || body.online_check_interval_hours > 168) {
    _showErr("检测间隔必须在 1-168 小时之间"); return;
  }
  if (body.online_check_max_attempts < 1 || body.online_check_max_attempts > 10) {
    _showErr("最大重试次数必须在 1-10 之间"); return;
  }
  if (body.online_check_retry_interval_minutes < 1 || body.online_check_retry_interval_minutes > 60) {
    _showErr("重试间隔必须在 1-60 分钟之间"); return;
  }
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const r = await putJson("/api/config/online-check", body);
    if (r.restart_ok) {
      _showOk("✓ 配置已保存,服务已重启(可能几秒后刷新)");
    } else {
      _showOk(
        `✓ 配置已保存到 ${r.config_path},但服务重启失败: ${r.restart_message || "?"}\n` +
        "请手动执行: sudo systemctl restart checkgprobot"
      );
    }
  } catch (e) {
    _showErr(`保存失败: ${e.detail || e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "💾 保存并重启";
  }
}

export function init() {
  const form = document.getElementById("online-check-form");
  if (!form) return;
  const btn = form.querySelector("#cfg-save");
  _populate();
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    _clearMsg();
    _submit(form, btn);
  });
  // 结算信息 section
  _wirePaymentSection();
}