// smart-defaults.js：新增项目表单的智能默认值。
//
// 行为：
// - class_name 自动跟 package_name 走（默认 `<package_name>.MainActivity`），
//   但用户手动改过 class_name 之后就不再覆盖（data-user-modified 标记）
// - GP checkbox 勾上 + package_name 非空 → store_url 自动填 GP URL

const GP_STORE_URL_PREFIX = "https://play.google.com/store/apps/details?id=";

function _onPackageNameChange(form) {
  const pkg = (form.querySelector("#np-package-name").value || "").trim();
  const classInput = form.querySelector("input[data-info-key='class_name']");
  if (!classInput) {
    _maybeUpdateStoreUrl(form, pkg);
    return;
  }
  // 用户手动改过 class_name 就不覆盖
  if (classInput.dataset.userModified === "true") {
    _maybeUpdateStoreUrl(form, pkg);
    return;
  }
  classInput.value = pkg ? `${pkg}.MainActivity` : "";
  _maybeUpdateStoreUrl(form, pkg);
}

function _onClassNameInput(classInput) {
  // 标记为用户手动改过
  classInput.dataset.userModified = "true";
}

function _maybeUpdateStoreUrl(form, pkg) {
  const gpCheckbox = form.querySelector("#np-gp-target");
  const storeUrlInput = form.querySelector("#np-store-url");
  if (!gpCheckbox || !storeUrlInput) return;
  if (gpCheckbox.checked && pkg) {
    storeUrlInput.value = GP_STORE_URL_PREFIX + pkg;
  } else if (gpCheckbox.checked && !pkg) {
    storeUrlInput.value = "";
  }
  // GP 未勾选不动 store_url（用户可能手填了别的）
}

function _onGpToggle(form) {
  const pkg = (form.querySelector("#np-package-name").value || "").trim();
  _maybeUpdateStoreUrl(form, pkg);
}

export function wireSmartDefaults(form) {
  const pkgInput = form.querySelector("#np-package-name");
  const gpCheckbox = form.querySelector("#np-gp-target");
  if (pkgInput) {
    pkgInput.addEventListener("input", () => _onPackageNameChange(form));
  }
  if (gpCheckbox) {
    gpCheckbox.addEventListener("change", () => _onGpToggle(form));
  }
  // 监听 class_name input（动态渲染的，需事件委托）
  const infoContainer = form.querySelector("#np-info-fields");
  if (infoContainer) {
    infoContainer.addEventListener("input", (ev) => {
      const t = ev.target;
      if (t && t.dataset && t.dataset.infoKey === "class_name") {
        _onClassNameInput(t);
      }
    });
  }
}