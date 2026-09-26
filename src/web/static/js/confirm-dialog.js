// confirm-dialog.js：复用 _confirm_dialog.html 提供的全局对话框(渲染为 Promise)。
//
// 用法:
//   const ok = await confirmDialog("确定删除?");
//   if (ok) ...

export function confirmDialog(message) {
  return new Promise((resolve) => {
    const dialog = document.getElementById("confirm-dialog");
    const msgEl = document.getElementById("confirm-dialog-message");
    const okBtn = document.getElementById("confirm-dialog-ok");
    const cancelBtn = document.getElementById("confirm-dialog-cancel");
    if (!dialog || !okBtn || !cancelBtn) {
      // 退化:没有 modal 时用浏览器原生 confirm
      resolve(window.confirm(message));
      return;
    }
    msgEl.textContent = message;
    dialog.hidden = false;
    const cleanup = (result) => {
      dialog.hidden = true;
      okBtn.removeEventListener("click", okHandler);
      cancelBtn.removeEventListener("click", cancelHandler);
      resolve(result);
    };
    const okHandler = () => cleanup(true);
    const cancelHandler = () => cleanup(false);
    okBtn.addEventListener("click", okHandler);
    cancelBtn.addEventListener("click", cancelHandler);
  });
}