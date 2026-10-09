// smart-defaults.js：新增项目表单的智能默认值。
//
// 行为：
// - class_name 自动跟 package_name 走（默认 `<package_name>.MainActivity`），
//   但用户手动改过 class_name 之后就不再覆盖（data-user-modified 标记）
// - GP checkbox 勾上 + package_name 非空 → store_url 自动填 GP URL
// - project_id 含 "IOS" 子串 → 不触发 GP autofill（iOS 项目商店地址模式不同，由用户手填）

const GP_STORE_URL_PREFIX = "https://play.google.com/store/apps/details?id=";

// iOS 项目约定：project_id 含 "IOS" 子串 → 不触发 GP autofill
function _shouldAutofillGp(form) {
  const projectIdEl = form?.querySelector("#np-project-id");
  const gpEl = form?.querySelector("#np-gp-target");
  const projectId = projectIdEl?.value || "";
  const gpChecked = gpEl?.checked || false;
  return gpChecked && !projectId.includes("IOS");
}

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
  if (!_shouldAutofillGp(form)) {
    // iOS 项目（project_id 含 "IOS"）不自动填 GP URL；让用户手填 iOS App Store URL
    return;
  }
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

function _onProjectIdInput(form) {
  // 用户在 project_id 里输入 "IOS" 时，如果 GP 已勾选，要把已自动填的 store_url 清掉，
  // 让用户手填 iOS App Store URL
  const projectId = form.querySelector("#np-project-id")?.value || "";
  const gpChecked = form.querySelector("#np-gp-target")?.checked || false;
  if (gpChecked && projectId.includes("IOS")) {
    const storeUrlInput = form.querySelector("#np-store-url");
    if (storeUrlInput) storeUrlInput.value = "";
  }
}

export function wireSmartDefaults(form) {
  const pkgInput = form.querySelector("#np-package-name");
  const gpCheckbox = form.querySelector("#np-gp-target");
  const projectIdInput = form.querySelector("#np-project-id");
  if (pkgInput) {
    pkgInput.addEventListener("input", () => _onPackageNameChange(form));
  }
  if (gpCheckbox) {
    gpCheckbox.addEventListener("change", () => _onGpToggle(form));
  }
  if (projectIdInput) {
    projectIdInput.addEventListener("input", () => _onProjectIdInput(form));
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