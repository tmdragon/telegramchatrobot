# checkGPRobot iOS 平台支持 — 设计

| 项 | 值 |
|---|---|
| 日期 | 2026-10-09 |
| 状态 | Draft（待用户审阅） |
| 项目名 | checkGPRobot |
| 路径 | `D:\soft\checkGPRobot\.spyproject` |
| 前置 | `docs/superpowers/specs/2026-09-18-checkgprobot-design.md` |

## 1. 目的与范围

### 1.1 背景

`checkGPRobot` 当前所有"过包"链路（在线监控、上架检测、URL 构造）都硬编码为 Google Play。`store_checker.py` 用 Google Play 的 HTML 启发式判断上架状态；新项目表单只有一个 GP 复选框 + GP URL 前缀。用户开始管理 iOS 项目，需要把 iOS 作为**对等平台**接入，而不破坏现有 GP 流程。

### 1.2 目标

让一个 `project_id` 在含子串 `IOS` 时被识别为 iOS 项目：

- **不新加列**（最小改动）：iOS 项目的 `商店地址` 由用户手动填写完整 `https://apps.apple.com/app/idN` URL
- **不上锁新字段**：iOS 专属信息字段（Bundle ID、App Store ID、SKU 等）暂不暴露，sheet 现有结构不变
- **复用 `StatusCode` 14 态**：`PUBLISHED` / `OFF_SHELF` 等对两个平台同等适用
- **检测机制按平台分发**：GP 走现有 HTML 启发式；iOS 走 **iTunes Search API**（`https://itunes.apple.com/lookup?id={N}`，官方公开 JSON）

### 1.3 范围

**做**：
- `Project` 加 `platform` 字段，从 `project_id` 派生（大小写敏感子串 `"IOS"` → `"ios"`，否则 `"gp"`）
- `store_checker.check_app_published` 按 platform 分发调用
- 三个 scheduler 入口（store_monitor / 立即监测 / online_check）传递 `platform`
- 新项目表单：`smart-defaults.js` 检测 `project_id` 含 `"IOS"` 时跳过 GP autofill
- Web UI：项目行 + 详情页加 `📱 iOS` / `🤖 GP` 小角标（纯 CSS chip）
- Bot 广播：`render_broadcast` 在 iOS 项目标题前加 `[iOS] ` 前缀

**不做**（YAGNI）：
- 新增 iOS 专属 sheet 列（App Store ID / Bundle ID / SKU / Team ID）
- 暴露 `/info` 命令的 iOS 信息差异
- 改造 `HeaderDetector` / `parser.py` 候选列表
- 改 `LOCKED_RECOGNIZED_AS`（仍只有 `project_id`）
- 增加 `sheets.yaml` 平台字段
- 处理多平台同一项目（一个 project = 一个平台 = 一行）

### 1.4 名词术语

| 术语 | 含义 |
|---|---|
| platform | 项目所属商店，取值 `"gp"` 或 `"ios"` |
| iTunes Search API | Apple 公开搜索接口，返回 JSON，无需鉴权 |
| App Store ID | iOS 应用在 App Store 的数字 ID（9-10 位），从 `apps.apple.com/.../idN` 末段提取 |

---

## 2. 架构影响

### 2.1 改动范围一览

| 层 | 文件 | 改动 |
|---|---|---|
| 模型 | `src/models/project.py` | `Project` 加 `platform: Literal["gp", "ios"]`，`__post_init__` 派生 |
| 检测 | `src/store_checker.py` | `check_app_published(url, platform, ...)` 分发；新增 iOS 路径 `_check_ios_app` |
| 调度 | `src/scheduler/jobs.py` | `_store_monitor_wrapper` / `trigger_store_check_now` / `_online_check_one` 传 `platform` |
| UI（JS） | `src/web/static/js/smart-defaults.js` | 检测 `project_id` 含 `"IOS"` 时禁用 GP autofill |
| UI（HTML） | `src/web/templates/overview.html`、`project_detail.html` | 加 `📱 iOS` / `🤖 GP` chip |
| Bot | `src/bot/templates.py` | `render_broadcast` 加 `[iOS]` 前缀 |
| 测试 | `tests/unit/test_platform_detection.py` | 新增 |
| 测试 | `tests/unit/test_store_checker_ios.py` | 新增 |
| 测试 | `tests/unit/test_extract_app_store_id.py` | 新增 |
| 测试 | `tests/integration/test_scheduler_jobs_ios.py` | 新增 |

**不动**：parser 不新加候选；`LOCKED_RECOGNIZED_AS` 不变；`/info` 不改；`status.py` 不改；`sheets.yaml` schema 不变。

### 2.2 数据流变化

**读路径**（无变化，仍由 `SheetRepo.fetch_all` → parser → `Project`）：
```
SheetRepo.fetch_all()
  → parser 识别 project_id / status / project_name（不变）
  → Project.__post_init__ 从 project_id 派生 platform   ← 新增
```

**上架检测路径**（按 platform 分发）：
```
trigger_store_check_now(project) / _store_monitor_wrapper(project)
  → store_checker.check_app_published(project.store_url, project.platform, ...)
      ├─ platform == "ios" → _check_ios_app(url)   ← 新增
      └─ platform == "gp"  → 现有 GP HTML 路径    （不变）
  → CheckResult(published / not_published / error / ambiguous)
```

**Bot 广播路径**（iOS 项目加前缀）：
```
render_broadcast(project, ...)
  ├─ project.platform == "ios" → 标题前加 "[iOS] "   ← 新增
  └─ project.platform == "gp"  → 现有渲染           （不变）
```

---

## 3. 数据模型

### 3.1 `Project.platform` 字段

```python
from typing import Literal

@dataclass
class Project:
    project_id: str
    project_name: Optional[str] = None
    status: Optional["StatusCode"] = None
    status_changed_at: Optional[datetime] = None
    status_history: list[tuple["StatusCode", datetime]] = field(default_factory=list)
    sheets: list[SheetView] = field(default_factory=list)
    platform: Literal["gp", "ios"] = "gp"  # NEW

    def __post_init__(self):
        # 从 project_id 派生 platform
        # 规则: project_id 含大小写敏感子串 "IOS" → "ios"，否则 "gp"
        self.platform = "ios" if "IOS" in self.project_id else "gp"
```

**派生语义**：
- 派生在 `__post_init__` 中，调用方无需手动设值
- `Project(...)` 构造后 `project.platform` 总是正确的
- 反序列化路径（从 SQLite 快照恢复时）也走 `__post_init__`，所以历史快照加载后 platform 也正确
- 唯一真相源是 `project_id`，**不二次检查** `store_url` 域名
  - 例外处理：iOS 项目但 `store_url` 域名是 `play.google.com`（用户笔误），系统按 ios 走，iTunes API 用 URL 提取不到 ID 时返回 `error` 状态，由用户在 UI 看到

### 3.2 `Field.recognized_as` 不变

仍只有 `project_id` / `status` / `project_name` 等已知键。iOS 专属字段（如 Bundle ID / App Store ID）暂不识别，落 `recognized_as=None`，与其他未识别字段同等处理（详情页可编辑，sheet 回写）。

---

## 4. 上架检测（store_checker）

### 4.1 入口签名

```python
def check_app_published(
    url: str,
    platform: Literal["gp", "ios"],
    *,
    proxy: Optional[str] = None,
    timeout: int = 10,
) -> CheckResult:
    ...
```

### 4.2 GP 路径（不变）

保留现有 HTML 启发式：`store_checker.py` 当前 `_INDICATORS_PUBLISHED` / `_INDICATORS_NOT_FOUND` / `_TITLE_RE` / `_PAGE_TITLE_RE` 全部沿用。

### 4.3 iOS 路径（新）

```python
_APP_STORE_ID_RE = re.compile(r"/id(\d+)(?:$|[/?#])")

def _check_ios_app(url: str, *, proxy: Optional[str], timeout: int) -> CheckResult:
    """iOS 上架检测：用 iTunes Search API 查询 App Store ID 的发布状态。

    URL 提取 App Store ID（兼容 apps.apple.com/app/idN 与 apps.apple.com/cn/app/.../idN）。
    """
    m = _APP_STORE_ID_RE.search(url)
    if not m:
        return CheckResult(
            status="error",
            reason=f"URL 中未找到 App Store ID: {url}",
        )
    app_id = m.group(1)
    api_url = f"https://itunes.apple.com/lookup?id={app_id}"

    proxies = {"https": proxy} if proxy else None
    try:
        resp = requests.get(api_url, proxies=proxies, timeout=timeout)
    except requests.RequestException as e:
        return CheckResult(status="error", reason=f"iTunes API 请求失败: {e}")

    if resp.status_code != 200:
        return CheckResult(status="error", reason=f"iTunes API 返回 HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        return CheckResult(status="error", reason="iTunes API 返回非 JSON")

    count = data.get("resultCount", 0)
    if count == 0:
        return CheckResult(status="not_published", reason="iTunes 搜索无结果")

    results = data.get("results", [])
    if not results:
        return CheckResult(status="error", reason="iTunes 响应缺 results")

    track_name = results[0].get("trackName", "")
    return CheckResult(
        status="published",
        reason="",
        track_name=track_name,
    )
```

### 4.4 `CheckResult` 不变

`status` 枚举 `"published" / "not_published" / "error" / "ambiguous"`，新增 `track_name` 可选字段（GP 路径填入 `<h1 itemprop="name">` 内容；iOS 路径填入 iTunes `trackName`）。

### 4.5 下架检测（offline check）

`check_online_status`（`_online_check_one` 调用）当前依赖 `check_app_published` 判断 `not_published` 即下架候选。iOS 路径自然兼容：iTunes API `resultCount: 0` → `not_published` → 走现有 OFF_SHELF 流转逻辑。无新增代码。

---

## 5. 调度入口改动

### 5.1 `_store_monitor_wrapper`（`src/scheduler/jobs.py:269-354`）

```python
def _store_monitor_wrapper(project: Project) -> None:
    ...
    result = check_app_published(
        project.store_url,
        project.platform,   # NEW
        proxy=store_monitor_proxy_url,
        timeout=...,
    )
    ...
```

### 5.2 `trigger_store_check_now`（`src/scheduler/jobs.py:147-230`）

同步改动：`check_app_published` 第二参数传 `project.platform`。

### 5.3 `_online_check_one`（`src/scheduler/jobs.py:391-447`）

同步改动：`check_app_published` 第二参数传 `project.platform`。offline 流转沿用项目当前 status 决定落点（`PUBLISHED → OFF_SHELF`），无新增 status 转换逻辑。

---

## 6. Web UI

### 6.1 平台 chip

**overview.html** 项目表格每行第一列后插入：

```html
<span class="platform-chip platform-chip--{{ project.platform }}">
  {% if project.platform == "ios" %}📱 iOS{% else %}🤖 GP{% endif %}
</span>
```

**project_detail.html** 顶部项目编号旁同样插入。

**CSS**（`src/web/static/css/app.css` 新增）：

```css
.platform-chip {
  display: inline-block;
  padding: 2px 6px;
  margin-left: 6px;
  border-radius: 4px;
  font-size: 0.75em;
  font-weight: 500;
}
.platform-chip--ios { background: #e3f2fd; color: #1565c0; }
.platform-chip--gp  { background: #f1f3f4; color: #5f6368; }
```

### 6.2 新项目表单（零新增控件）

**当前**：`<input type="checkbox" id="np-gp-target">` + `smart-defaults.js` 的 `_onGpToggle`。

**改动**：`smart-defaults.js` 在 GP autofill 触发前，检测 `#np-project-id` 输入值含 `"IOS"`：

```javascript
function _shouldAutofillGp() {
  const projectId = document.querySelector('#np-project-id')?.value || '';
  const gpChecked = document.querySelector('#np-gp-target')?.checked;
  return gpChecked && !projectId.includes('IOS');
}

function _onGpToggle() {
  if (_shouldAutofillGp()) {
    // 现有 GP autofill 逻辑
  }
}

// 同时监听 #np-project-id 的 input 事件，重新计算
document.querySelector('#np-project-id')?.addEventListener('input', _onGpToggle);
```

iOS 项目跳过 autofill，用户手动填写完整 `商店地址`。

**UI 标签不变**：`<span>上架 GP（Google Play）</span>` 文案保留（iOS 用户不勾选，行为合理）。

---

## 7. Bot

### 7.1 广播前缀（`src/bot/templates.py:render_broadcast`）

```python
def render_broadcast(project: Project, ...) -> str:
    title_prefix = "[iOS] " if project.platform == "ios" else ""
    body = f"""
📊 *{title_prefix}{project.project_id} {project.project_name or ''}*
▸ 当前状态：...
    """
    ...
```

iOS 项目示例：`📊 *[iOS] PRJ-IOS-001 项目一*`；GP 项目不变：`📊 *PRJ-001 项目一*`。

### 7.2 `/info` 命令不变

仍输出 `class_name / SHA-1 / SHA-256 / hash_value / privacy_policy / store_url`。iOS 项目这些字段多数为空（iOS sheet 不含这些列），输出表现为空白项，等用户后续评估是否加列。**本次不改**。

### 7.3 MarkdownV2 转义

新增前缀 `[iOS] ` 含 `[` / `]` —— **MarkdownV2 reserved 字符**。需在 `render_broadcast` 中走现有转义函数（与 `settle_cmd` caption 处理同一工具函数）。**复用现有工具，不新增**。

---

## 8. 配置

无新增配置项：

- `secrets.yaml` 不变（仍只需 Google SA + Telegram token）
- `sheets.yaml` 不变（仍按 spreadsheet id/name/role 配）
- `scheduler.yaml` 不变（`store_monitor_*` / `online_check_*` 共用，proxy / retry 策略对两平台一致）

---

## 9. 测试

### 9.1 新增

| 文件 | 覆盖 |
|---|---|
| `tests/unit/test_platform_detection.py` | `Project.platform` 派生：`"PRJ-001"` → gp；`"PRJ-IOS-001"` → ios；`"IOS"` → ios；`""` → gp；`"ios"` 小写 → gp（大小写敏感） |
| `tests/unit/test_extract_app_store_id.py` | URL 正则：`https://apps.apple.com/app/id123` → 123；`https://apps.apple.com/cn/app/my-app/id456` → 456；`https://play.google.com/...` → None；末尾 query 容忍 `id789?mt=8` → 789 |
| `tests/unit/test_store_checker_ios.py` | mock `requests.get`：`resultCount: 1` → published；`resultCount: 0` → not_published；HTTP 500 → error；JSON 异常 → error；URL 无 id → error |
| `tests/integration/test_scheduler_jobs_ios.py` | 构造 iOS `Project` + mock store_checker，跑 `_store_monitor_wrapper` / `trigger_store_check_now` / `_online_check_one`，断言调用 `check_app_published(url, "ios", ...)` |

### 9.2 不变

现有 GP 测试全部不变。`tests/integration/test_repo_write.py` / `test_info_command.py` 等仍用 GP fixture。覆盖率目标：iOS 路径 ≥ 80% 行覆盖。

---

## 10. 验收标准

### 10.1 功能

- [ ] `Project(project_id="PRJ-001").platform == "gp"`
- [ ] `Project(project_id="PRJ-IOS-001").platform == "ios"`
- [ ] `Project(project_id="ios-mirror").platform == "gp"`（大小写敏感）
- [ ] overview 表格每行显示 `📱 iOS` 或 `🤖 GP` chip
- [ ] iOS 项目 store_url = `https://apps.apple.com/app/id123` 时，点"立即监测"返回 `published`
- [ ] iOS 项目 store_url 缺 id 时返回 `error`
- [ ] iOS 项目 store_url 是 GP URL 时按 ios 走、iTunes API 返回 error
- [ ] 立即监测 / store_monitor / online_check 三处对 iOS 项目均正常
- [ ] bot 广播 iOS 项目标题前有 `[iOS] ` 前缀
- [ ] bot 广播 GP 项目不变
- [ ] 新项目表单：project_id 输入 `"PRJ-IOS-001"` 时 GP autofill 不触发

### 10.2 非功能

- [ ] 现有 GP 测试 100% 通过（零回归）
- [ ] iTunes API 调用 < 2 秒（10 秒超时容错）
- [ ] iOS 监控失败不影响 GP 监控（同进程并行）

### 10.3 安全

- [ ] iTunes Search API 无凭证调用，仅暴露用户手填的 store_url 中的 App Store ID

---

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| iTunes API 限流 / 不可用 | GP 项目不受影响；iOS 检测返回 `error`，用户手动判断 |
| 用户填错 URL 格式 | 正则不匹配 → `error` + UI 红字 |
| `project_id` 含 "IOS" 巧合（如 `BIOS-001`） | 用户命名规范兜底；MVP 不做白名单 |
| iOS 项目信息字段缺失 | `/info` 输出空白；等用户评估后续是否加列 |
| 项目名歧义（同一项目 GP+iOS 跨表） | 不支持：每个 project_id 一行一平台 |

**回滚**：所有改动加在 `Project.__post_init__` / `store_checker` 分发 / 单一模板函数，回滚即删 commit。无需数据迁移。

---

## 12. 后续（不在本次实现范围）

- iOS 专属 sheet 列（Bundle ID / App Store ID / SKU / Team ID）
- `/info` 命令 iOS 信息差异
- App Store Connect API（需要 Apple Developer 凭证，发布状态更详细）
- 多平台同项目（一行双平台）
- iOS review 状态细化（In Review / Rejected / Metadata Rejected 等独立 StatusCode）