// settings.js：/settings 页面的"在架监控"section 提交。

import { getJson, putJson } from "./api.js";

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
}