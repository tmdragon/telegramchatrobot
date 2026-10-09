# checkGPRobot iOS 平台支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不新加 sheet 列、不暴露 iOS info 字段的前提下，让 project_id 含子串 `"IOS"` 的项目被识别为 iOS 项目，并复用 iTunes Search API 完成上架检测。

**Architecture:** `Project` 加 `platform` 字段（从 project_id 派生，`__post_init__` 中自动计算）；`store_checker.check_app_published` 增加 `platform` 参数并按平台分发（gp 走原 HTML 路径，ios 走 iTunes Search API）；3 个 scheduler 入口传 `project.platform`；前端 chip / 广播前缀作为最终用户标识。

**Tech Stack:** Python 3 dataclass、httpx（async）、FastAPI、Jinja2、原生 JS、python-telegram-bot

**Spec:** `docs/superpowers/specs/2026-10-09-checkgprobot-ios-platform-design.md`

---

## Global Constraints

- **平台派生规则**: `project_id` 含大小写敏感子串 `"IOS"` → `"ios"`，否则 `"gp"`。唯一真相源是 `project_id`，不二次检查 `store_url` 域名
- **不新加列**: sheet 列结构不变；iOS 项目的 `商店地址` 由用户手动填写完整 `https://apps.apple.com/app/idN` URL
- **不暴露 iOS info 字段**: Bundle ID / App Store ID / SKU / Team ID 等暂不识别为已知字段，落 `recognized_as=None` 与其他未识别字段同等
- **不动 parser / LOCKED_RECOGNIZED_AS / /info / status 枚举 / sheets.yaml schema**
- **`check_app_published` 返回 dict 不变**: `{"published": bool, "title": str | None, "status_code": int, "reason": str, "url_final": str}`
- **iOS 检测 URL 正则**: `r"/id(\d+)(?:$|[/?#])"`，兼容 `apps.apple.com/app/idN` 与 `apps.apple.com/cn/app/.../idN?mt=8`
- **httpx async 模式**: iOS 路径走 `httpx.AsyncClient` 与 GP 路径保持一致
- **每任务独立 commit**，遵循 `feat/fix(task): <verb> <thing>` 格式
- **Project 规约**：单文件 ≤ 200 行；新加字段含默认值，老调用方不需改

---

## File Structure

```
src/
├── models/
│   └── project.py              [MODIFY]  加 platform 字段 + __post_init__
├── store_checker.py            [MODIFY]  _APP_STORE_ID_RE + _check_ios_app + check_app_published 派发
├── scheduler/
│   └── jobs.py                 [MODIFY]  3 处调用点传 platform
├── bot/
│   └── templates.py            [MODIFY]  render_broadcast 加 [iOS] 前缀
├── web/
│   ├── templates/
│   │   ├── overview.html       [MODIFY]  行内 platform chip
│   │   └── project_detail.html [MODIFY]  顶部 platform chip
│   ├── static/
│   │   ├── js/smart-defaults.js [MODIFY]  含 "IOS" 时跳过 GP autofill
│   │   └── css/app.css         [MODIFY]  .platform-chip 样式
└── ...

tests/
├── unit/
│   ├── test_platform_detection.py     [CREATE]  Project.platform 派生
│   ├── test_extract_app_store_id.py   [CREATE]  URL 正则提取
│   └── test_store_checker_ios.py      [CREATE]  iTunes API 路径 + dispatch
└── integration/
    └── test_scheduler_jobs_ios.py     [CREATE]  scheduler 3 入口跑通 iOS

docs/superpowers/specs/2026-10-09-checkgprobot-ios-platform-design.md  [EXISTS]
README.md                             [MODIFY]  加 iOS 支持说明
CLAUDE.md                             [MODIFY]  Phase 状态更新（如果需要）
```

---

## Task 1: Project.platform 字段与派生

**Files:**
- Modify: `src/models/project.py:33-63`（Project dataclass）
- Create: `tests/unit/test_platform_detection.py`

**Interfaces:**
- Consumes: 现有 `Project(...)` 调用方保持不变
- Produces: `project.platform` 字段，类型 `Literal["gp", "ios"]`，构造后总是从 `project_id` 派生

### Step 1: 写失败测试

在 `tests/unit/test_platform_detection.py` 写：

```python
"""Project.platform 派生规则测试。"""
from src.models.project import Project


def test_platform_gp_when_project_id_no_ios():
    p = Project(project_id="PRJ-001")
    assert p.platform == "gp"


def test_platform_ios_when_project_id_contains_uppercase_IOS():
    p = Project(project_id="PRJ-IOS-001")
    assert p.platform == "ios"


def test_platform_ios_when_project_id_is_exactly_IOS():
    p = Project(project_id="IOS")
    assert p.platform == "ios"


def test_platform_case_sensitive_lowercase_ios_is_gp():
    p = Project(project_id="ios-mirror")
    assert p.platform == "gp"


def test_platform_case_sensitive_mixed_Ios_is_gp():
    p = Project(project_id="Ios-game")
    assert p.platform == "gp"


def test_platform_empty_project_id_is_gp():
    p = Project(project_id="")
    assert p.platform == "gp"
```

### Step 2: 跑测试确认失败

Run: `python -m pytest tests/unit/test_platform_detection.py -v`
Expected: FAIL with `AttributeError: type object 'Project' has no field 'platform'`

### Step 3: 实现 platform 字段

修改 `src/models/project.py:33-63` 的 `Project` dataclass：

1. 在顶部 imports 加：`from typing import Literal`
2. 在 `Project` 类的所有字段后、`status_history` 之前或之后的位置加：
   ```python
   platform: Literal["gp", "ios"] = "gp"  # 从 project_id 派生;含 "IOS" → ios
   ```
3. 在 `Project` 类底部加 `__post_init__`：
   ```python
   def __post_init__(self) -> None:
       # platform 唯一真相源是 project_id(大小写敏感子串 "IOS" → ios)
       self.platform = "ios" if "IOS" in self.project_id else "gp"
   ```

字段插入位置（保持现有结构，建议放在 `published_at` 附近作新字段分组）：

```python
    # === 在架监控(PUBLISHED 之后周期性探测是否被下架)===
    check_mode: str = "direct"
    proxy_country: Optional[str] = None
    last_online_check_at: Optional[datetime] = None
    last_online_check_result: Optional[str] = None
    offline_pending_since: Optional[datetime] = None
    offline_pending_attempts: int = 0
    # === 平台派生(project_id → gp / ios)===
    platform: Literal["gp", "ios"] = "gp"
```

### Step 4: 跑测试确认通过

Run: `python -m pytest tests/unit/test_platform_detection.py -v`
Expected: 6 PASS

### Step 5: 跑全量测试确保 GP 路径无回归

Run: `python -m pytest -v`
Expected: 全部通过；如有失败，是别处代码显式构造了 `Project(...)` 又假设了字段顺序，看具体错误回滚。

### Step 6: 提交

```bash
git add src/models/project.py tests/unit/test_platform_detection.py
git commit -m "feat(project): add platform field derived from project_id (\"IOS\" → ios)"
```

---

## Task 2: App Store ID URL 提取

**Files:**
- Modify: `src/store_checker.py` 顶部 imports 附近
- Create: `tests/unit/test_extract_app_store_id.py`

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `extract_app_store_id(url: str) -> Optional[int]`；URL 中含 `/id(\d+)` 时返回数字，否则返回 `None`

### Step 1: 写失败测试

在 `tests/unit/test_extract_app_store_id.py` 写：

```python
"""iOS App Store URL → App Store ID 提取测试。"""
from src.store_checker import extract_app_store_id


def test_basic_app_store_url():
    assert extract_app_store_id("https://apps.apple.com/app/id1234567890") == 1234567890


def test_app_store_url_with_country_and_slug():
    assert extract_app_store_id("https://apps.apple.com/cn/app/my-cool-game/id987654321") == 987654321


def test_app_store_url_with_query_string():
    assert extract_app_store_id("https://apps.apple.com/app/id1234567890?mt=8") == 1234567890


def test_app_store_url_with_fragment():
    assert extract_app_store_id("https://apps.apple.com/app/id1234567890#reviews") == 1234567890


def test_google_play_url_returns_none():
    assert extract_app_store_id("https://play.google.com/store/apps/details?id=com.x") is None


def test_empty_url_returns_none():
    assert extract_app_store_id("") is None


def test_non_app_store_url_returns_none():
    assert extract_app_store_id("https://example.com/foo/bar") is None


def test_id_in_path_but_no_digits_returns_none():
    assert extract_app_store_id("https://apps.apple.com/app/idsomething") is None
```

### Step 2: 跑测试确认失败

Run: `python -m pytest tests/unit/test_extract_app_store_id.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_app_store_id'`

### Step 3: 实现提取函数

在 `src/store_checker.py` 顶部（`_INDICATORS_PUBLISHED` 之前）加：

```python
# iOS App Store URL → App Store ID 提取
# 兼容 apps.apple.com/app/idN 与 apps.apple.com/cn/app/{slug}/idN
# 容忍末尾 query / fragment
_APP_STORE_ID_RE = re.compile(r"/id(\d+)(?:$|[/?#])")


def extract_app_store_id(url: str) -> Optional[int]:
    """从 iOS App Store URL 提取数字 App Store ID。无法提取时返回 None。"""
    if not url:
        return None
    m = _APP_STORE_ID_RE.search(url)
    if not m:
        return None
    return int(m.group(1))
```

### Step 4: 跑测试确认通过

Run: `python -m pytest tests/unit/test_extract_app_store_id.py -v`
Expected: 8 PASS

### Step 5: 提交

```bash
git add src/store_checker.py tests/unit/test_extract_app_store_id.py
git commit -m "feat(store_checker): add extract_app_store_id() for iOS URLs"
```

---

## Task 3: _check_ios_app (iTunes Search API 路径)

**Files:**
- Modify: `src/store_checker.py`
- Create: `tests/unit/test_store_checker_ios.py`

**Interfaces:**
- Consumes: `_check_ios_app(url, proxy, timeout) -> dict` 返回与 `check_app_published` 同 schema
- Produces: 被 Task 4 的 dispatcher 调用

### Step 1: 写失败测试

在 `tests/unit/test_store_checker_ios.py` 写：

```python
"""iOS 上架检测(iTunes Search API)测试。"""
import unittest.mock as mock
import pytest
from src.store_checker import _check_ios_app


def _fake_client(json_data, status_code=200, text=""):
    """构造 httpx.AsyncClient 的 mock。"""
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data
            self.text = text

        def json(self):
            return self._json

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    return _Client()


def test_ios_published_when_result_count_one():
    payload = {"resultCount": 1, "results": [{"trackName": "My Cool Game", "trackId": 12345}]}
    with mock.patch("src.store_checker.httpx.AsyncClient", return_value=_fake_client(payload)):
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is True
    assert result["title"] == "My Cool Game"
    assert result["reason"] == "published"


def test_ios_not_published_when_result_count_zero():
    payload = {"resultCount": 0, "results": []}
    with mock.patch("src.store_checker.httpx.AsyncClient", return_value=_fake_client(payload)):
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is False
    assert result["reason"] == "not_found"


def test_ios_error_when_http_500():
    with mock.patch("src.store_checker.httpx.AsyncClient", return_value=_fake_client({}, status_code=500)):
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is False
    assert result["reason"].startswith("error")
    assert "500" in result["reason"]


def test_ios_error_when_url_has_no_id():
    result = await _check_ios_app("https://play.google.com/store/apps/details?id=com.x",
                                  proxy=None, timeout=10)
    assert result["published"] is False
    assert "App Store ID" in result["reason"]
    assert result["reason"].startswith("error")


def test_ios_error_when_json_malformed():
    with mock.patch("src.store_checker.httpx.AsyncClient", return_value=_fake_client(None)):
        # json() raises ValueError
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is False
    assert result["reason"].startswith("error")


def test_ios_passes_proxy_to_httpx():
    payload = {"resultCount": 1, "results": [{"trackName": "X", "trackId": 1}]}
    captured = {}

    class _Client:
        def __init__(self, *a, **kw):
            captured.update(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            class _R:
                status_code = 200
                def json(self_inner):
                    return payload
            return _R()

    with mock.patch("src.store_checker.httpx.AsyncClient", return_value=_Client()):
        await _check_ios_app("https://apps.apple.com/app/id1", proxy="http://proxy:8080", timeout=10)
    assert captured.get("proxies") == "http://proxy:8080"
```

文件顶部加：`import pytest; pytestmark = pytest.mark.asyncio`（或 `async def` 形式，见项目现有 pytest-asyncio 范式 — 查 `tests/test_scheduler_jobs.py` 顶部 import）。

如果项目用 `@pytest.mark.asyncio` 装饰器风格，则改成：

```python
import unittest.mock as mock
import pytest
from src.store_checker import _check_ios_app

pytestmark = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_ios_published_when_result_count_one():
    ...
```

### Step 2: 跑测试确认失败

Run: `python -m pytest tests/unit/test_store_checker_ios.py -v`
Expected: FAIL with `ImportError: cannot import name '_check_ios_app'`

### Step 3: 实现 _check_ios_app

在 `src/store_checker.py` 底部加（在 `check_app_published` 函数定义之前）：

```python
async def _check_ios_app(
    url: str,
    *,
    proxy: Optional[str] = None,
    timeout: float = 15.0,
) -> dict:
    """iOS 上架检测：通过 iTunes Search API 查询 App Store ID 的发布状态。

    返回 schema 与 check_app_published 一致：
      {published: bool, title: str | None, status_code: int, reason: str, url_final: str}

    reason 取值：
      - "published"：iTunes 返回 resultCount=1
      - "not_found"：iTunes 返回 resultCount=0
      - "no_url"：URL 为空
      - "error: <details>"：HTTP / JSON / URL 异常
    """
    if not url:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "no_url", "url_final": ""}

    app_id = extract_app_store_id(url)
    if app_id is None:
        return {"published": False, "title": None, "status_code": 0,
                "reason": f"error: URL 中未找到 App Store ID: {url}", "url_final": url}

    api_url = f"https://itunes.apple.com/lookup?id={app_id}"
    proxies = proxy if proxy else None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            proxies=proxies,
            headers=headers,
        ) as client:
            r = await client.get(api_url)
            status = r.status_code
            data = r.json()
    except httpx.TimeoutException:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "timeout", "url_final": url}
    except ValueError:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "error: iTunes API 返回非 JSON", "url_final": url}
    except Exception as e:  # noqa: BLE001
        return {"published": False, "title": None, "status_code": 0,
                "reason": f"error: {type(e).__name__}: {e}", "url_final": url}

    if status != 200:
        return {"published": False, "title": None, "status_code": status,
                "reason": f"error: iTunes API HTTP {status}", "url_final": url}

    count = data.get("resultCount", 0)
    if count == 0 or not data.get("results"):
        return {"published": False, "title": None, "status_code": status,
                "reason": "not_found", "url_final": url}

    track_name = data["results"][0].get("trackName")
    return {"published": True, "title": track_name, "status_code": status,
            "reason": "published", "url_final": url}
```

### Step 4: 跑测试确认通过

Run: `python -m pytest tests/unit/test_store_checker_ios.py -v`
Expected: 6 PASS

### Step 5: 提交

```bash
git add src/store_checker.py tests/unit/test_store_checker_ios.py
git commit -m "feat(store_checker): add _check_ios_app via iTunes Search API"
```

---

## Task 4: check_app_published 派发 + 单元测试

**Files:**
- Modify: `src/store_checker.py:86-172`（`check_app_published` 签名 + 内部派发）
- Modify: `tests/unit/test_store_checker_ios.py`（追加 dispatch 测试）

**Interfaces:**
- Consumes: 现有 GP 调用者 `check_app_published(url, proxy=...)` 不需修改（默认 platform="gp"）
- Produces: `check_app_published(url, platform="gp"|"ios", proxy=..., timeout=...)`；iOS 项目自动走 `_check_ios_app`

### Step 1: 追加失败测试

在 `tests/unit/test_store_checker_ios.py` 末尾追加：

```python
"""check_app_published 按 platform 派发的 dispatch 测试。"""
from src.store_checker import check_app_published


@pytest.mark.asyncio
async def test_dispatch_to_ios_when_platform_ios():
    payload = {"resultCount": 1, "results": [{"trackName": "iOS App", "trackId": 999}]}
    with mock.patch("src.store_checker.httpx.AsyncClient", return_value=_fake_client(payload)):
        result = await check_app_published(
            "https://apps.apple.com/app/id999", platform="ios", proxy=None, timeout=10
        )
    assert result["published"] is True
    assert result["title"] == "iOS App"


@pytest.mark.asyncio
async def test_default_platform_is_gp():
    """不传 platform 时默认 gp 走原 HTML 路径；传 GP URL 应触发 HTTP 请求。"""
    fake_html = '<title>Fake App - Apps on Google Play</title><span itemprop="name">Fake App</span>'
    # 不 mock httpx；期望抛 httpx.ConnectError 或返回 error（非 iOS 路径）
    # 此处用更稳的方式：传不存在的 host，GP 路径会因 ConnectError 返回 error
    result = await check_app_published(
        "http://this-domain-definitely-does-not-exist-abc123.invalid/foo",
        timeout=2,
    )
    assert result["published"] is False
    assert result["reason"].startswith("error") or result["reason"] in ("timeout", "ambiguous")
```

### Step 2: 跑测试确认失败

Run: `python -m pytest tests/unit/test_store_checker_ios.py -v -k "dispatch or default"`
Expected: FAIL（`check_app_published` 还不接受 `platform` 参数）

### Step 3: 修改 check_app_published 签名

修改 `src/store_checker.py:86-90` 的签名：

```python
async def check_app_published(
    url: str,
    platform: Literal["gp", "ios"] = "gp",
    proxy: Optional[str] = None,
    timeout: float = 15.0,
) -> dict:
```

在函数体最顶部（`if not url:` 之前）加：

```python
    from typing import Literal  # 顶部 imports 已加则省略
    if platform == "ios":
        return await _check_ios_app(url, proxy=proxy, timeout=timeout)
    # platform == "gp"：沿用原 HTML 路径
```

`Literal` 在文件顶部 imports 加：

```python
from typing import Literal, Optional
```

### Step 4: 跑测试确认通过

Run: `python -m pytest tests/unit/test_store_checker_ios.py -v`
Expected: 全部 PASS（包括 Task 3 的 6 个 + 这里的 2 个）

### Step 5: 跑全量测试确认无回归

Run: `python -m pytest -v`
Expected: 全部通过；GP 路径调用方无 platform 参数时默认 gp → 行为不变

### Step 6: 提交

```bash
git add src/store_checker.py tests/unit/test_store_checker_ios.py
git commit -m "feat(store_checker): dispatch check_app_published on platform (gp | ios)"
```

---

## Task 5: scheduler 三处调用点传 project.platform

**Files:**
- Modify: `src/scheduler/jobs.py:162-164, 301-303, 389`（3 处 `check_app_published` 调用）
- Create: `tests/integration/test_scheduler_jobs_ios.py`

**Interfaces:**
- Consumes: Task 4 的 `check_app_published(url, platform=..., proxy=...)`
- Produces: 三个 scheduler 入口对 iOS 项目调用时 platform="ios"

### Step 1: 写失败测试

在 `tests/integration/test_scheduler_jobs_ios.py` 写：

```python
"""scheduler jobs 调用 check_app_published 时传 project.platform。"""
import unittest.mock as mock
import pytest

from src.models.project import Project
from src.scheduler.jobs import (
    _store_monitor_wrapper,
    trigger_store_check_now,
    _online_check_one,
)


def _make_ios_project():
    return Project(
        project_id="PRJ-IOS-001",
        project_name="Test iOS App",
        store_url="https://apps.apple.com/app/id12345",
    )


def _make_gp_project():
    return Project(
        project_id="PRJ-001",
        project_name="Test GP App",
        store_url="https://play.google.com/store/apps/details?id=com.test",
    )


@pytest.mark.asyncio
async def test_trigger_store_check_now_passes_platform_ios():
    """手动监测 iOS 项目时，check_app_published 第二参数为 'ios'。"""
    # 构造最小 refresher / broadcast_svc / cache mock（参考 tests/test_scheduler_jobs.py 现有范式）
    # 此处只验证 jobs.check_app_published 被以 platform='ios' 调用
    ...
```

> **重要**：本任务的测试应**严格模仿 `tests/test_scheduler_jobs.py` 现有 mock 范式**。先 Read 该文件了解 fixture 结构（project / refresher / broadcast_svc / broadcast_cfg），再按同样模式写。三个 test 分别覆盖 `_store_monitor_wrapper`、`trigger_store_check_now`、`_online_check_one`，每个都断言 `check_app_published` 被以 `platform="ios"` 调用。

测试核心断言（每个 test 都有）：

```python
with mock.patch("src.scheduler.jobs.check_app_published",
                new=mock.AsyncMock(return_value={"published": True, ...})) as mock_check:
    await <call the scheduler function>
    args, kwargs = mock_check.call_args
    assert kwargs.get("platform") == "ios" or args[1] == "ios"
```

### Step 2: 跑测试确认失败

Run: `python -m pytest tests/integration/test_scheduler_jobs_ios.py -v`
Expected: FAIL（`check_app_published` 收到 `proxy` 但没 `platform`，断言失败）

### Step 3: 修改 jobs.py 三处调用

修改 `src/scheduler/jobs.py` 三处。逐处替换：

**第 1 处**（`trigger_store_check_now`，约 162-164 行）：
```python
    result = await check_app_published(
        proj.store_url, proj.platform, proxy=broadcast_cfg.store_monitor_proxy_url or None,
    )
```

**第 2 处**（`_store_monitor_wrapper`，约 301-303 行）：
```python
        result = await check_app_published(
            project.store_url, project.platform,
            proxy=broadcast_cfg.store_monitor_proxy_url or None,
        )
```

**第 3 处**（`_online_check_one`，约 389 行）：
```python
    result = await check_app_published(url, project.platform, proxy=proxy)
```

### Step 4: 跑测试确认通过

Run: `python -m pytest tests/integration/test_scheduler_jobs_ios.py -v`
Expected: 全部 PASS

### Step 5: 跑全量测试确认无回归

Run: `python -m pytest -v`
Expected: 全部通过

### Step 6: 提交

```bash
git add src/scheduler/jobs.py tests/integration/test_scheduler_jobs_ios.py
git commit -m "feat(scheduler): pass project.platform to check_app_published in 3 entry points"
```

---

## Task 6: smart-defaults.js 跳过 GP autofill（含 "IOS" 时）

**Files:**
- Modify: `src/web/static/js/smart-defaults.js`

**Interfaces:**
- Consumes: `#np-project-id` 输入框、`#np-gp-target` 复选框
- Produces: 任一输入变化时，project_id 含 "IOS" 时**不**自动写入 GP URL

### Step 1: 阅读现有文件

Read `src/web/static/js/smart-defaults.js` 完整内容，了解 `_maybeUpdateStoreUrl` / `_onGpToggle` / 现有事件绑定

### Step 2: 加 detection 函数

在文件顶部（`GP_STORE_URL_PREFIX` 定义后）加：

```javascript
// iOS 项目约定：project_id 含 "IOS" 子串 → 不触发 GP autofill
function _shouldAutofillGp() {
  const projectIdEl = document.querySelector('#np-project-id');
  const gpEl = document.querySelector('#np-gp-target');
  const projectId = projectIdEl?.value || '';
  const gpChecked = gpEl?.checked || false;
  return gpChecked && !projectId.includes('IOS');
}
```

### Step 3: 改造 _onGpToggle / _maybeUpdateStoreUrl

找到现有 `_maybeUpdateStoreUrl` 或 `_onGpToggle` 函数。在 GP autofill 触发判断处加 `_shouldAutofillGp()` 守卫：

```javascript
// 伪代码示意（按现有函数实际结构调整）：
function _onGpToggle() {
  if (!_shouldAutofillGp()) return;  // 新增守卫
  // 原有 GP autofill 逻辑...
}
```

如果现有逻辑是直接绑 `change` 事件到 `#np-gp-target`，把 handler 包成 `_onGpToggle()` 调用。

### Step 4: 监听 #np-project-id input 重新计算

在文件末尾或 DOMContentLoaded 中加：

```javascript
document.querySelector('#np-project-id')?.addEventListener('input', () => {
  // 用户输入 project_id 时，如果勾了 GP 且 ID 含 IOS，要清掉已填的 GP URL
  const projectId = document.querySelector('#np-project-id')?.value || '';
  const gpChecked = document.querySelector('#np-gp-target')?.checked || false;
  if (gpChecked && projectId.includes('IOS')) {
    // 含 IOS 时强制清掉 #np-store-url，让用户手动填 iOS URL
    const storeEl = document.querySelector('#np-store-url');
    if (storeEl) storeEl.value = '';
  }
});
```

### Step 5: 手动验证

启动 dev 服务：

```bash
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml
```

浏览器开 `http://127.0.0.1:8765/` → 点"新增项目"：

- 输入 `PRJ-IOS-001` + 不勾 GP → 商店地址应为空（用户手填）
- 输入 `PRJ-001` + 勾 GP → 商店地址应自动填 GP URL
- 先勾 GP 自动填了 URL，再改 project_id 为 `PRJ-IOS-001` → URL 应被清空

### Step 6: 提交

```bash
git add src/web/static/js/smart-defaults.js
git commit -m "feat(web): skip GP autofill when project_id contains IOS"
```

---

## Task 7: Web UI platform chip

**Files:**
- Modify: `src/web/templates/overview.html`（项目行）
- Modify: `src/web/templates/project_detail.html`（顶部）
- Modify: `src/web/static/css/app.css`（追加 chip 样式）

**Interfaces:**
- Consumes: `project.platform`（来自 Task 1）
- Produces: 每个项目显示 `📱 iOS` 或 `🤖 GP` chip

### Step 1: 在 overview.html 项目行加 chip

找到 overview.html 项目表格行（`{% for project in projects %}` 循环体内），在项目编号单元格内的 chip 插入位置加：

```html
<span class="platform-chip platform-chip--{{ project.platform }}">
  {% if project.platform == "ios" %}📱 iOS{% else %}🤖 GP{% endif %}
</span>
```

（建议放在 project_id 文字之后，视觉上是「PRJ-IOS-001 📱 iOS」并排）

### Step 2: 在 project_detail.html 顶部加 chip

找到 project_detail.html 顶部项目标题区，在 `<h1>` 或项目编号 span 后加同一段 chip 代码。

### Step 3: 在 app.css 加 chip 样式

定位到 `app.css` 末尾（或 `status-chip` 样式附近），追加：

```css
.platform-chip {
  display: inline-block;
  padding: 2px 8px;
  margin-left: 6px;
  border-radius: 4px;
  font-size: 0.75em;
  font-weight: 500;
  vertical-align: middle;
}
.platform-chip--ios {
  background: #e3f2fd;
  color: #1565c0;
}
.platform-chip--gp {
  background: #f1f3f4;
  color: #5f6368;
}
```

### Step 4: 手动验证

启动 dev 服务，浏览器检查：

- 项目总览：GP 项目的 chip 是灰底「🤖 GP」；iOS 项目的 chip 是蓝底「📱 iOS」
- 项目详情页：标题旁有对应 chip

### Step 5: 提交

```bash
git add src/web/templates/overview.html src/web/templates/project_detail.html src/web/static/css/app.css
git commit -m "feat(web): add platform chip (iOS/GP) on overview and project detail"
```

---

## Task 8: Bot 广播 [iOS] 前缀

**Files:**
- Modify: `src/bot/templates.py`（`render_broadcast` 函数）

**Interfaces:**
- Consumes: `project.platform`（来自 Task 1）
- Produces: iOS 项目广播标题前加 `[iOS] ` 前缀

### Step 1: 读现有 render_broadcast

Read `src/bot/templates.py` 完整内容，定位 `render_broadcast(project, ...)` 函数和 MarkdownV2 转义工具（参考 `bot/commands.py:settle_cmd` 已有的转义模式）

### Step 2: 加前缀

在 `render_broadcast` 函数体内，最初组装 `title` 字符串前加：

```python
    from src.bot.templates import escape_markdown_v2  # 或项目现有转义函数
    platform_prefix = "[iOS] " if project.platform == "ios" else ""
    # 然后在组装标题时把 platform_prefix 拼到 project_id 前
```

注意：
- `[iOS] ` 含 `[` 和 `]`，是 MarkdownV2 reserved 字符，必须走现有 `escape_markdown_v2` 函数转义
- 拼装后标题示例：`📊 *[iOS] PRJ-IOS\-001 项目一*`（实际转义规则按现有 helper 处理）
- 如果 helper 名字不是 `escape_markdown_v2`，按 grep `escape` 在 `src/bot/` 找到的实际函数名替换

### Step 3: 手动验证

启动 dev 服务 + bot，用管理员账号私聊 bot 触发 `/dryrun`：

```bash
/dryrun
```

预期输出：iOS 项目标题以 `[iOS] ` 开头；GP 项目标题不变

### Step 4: 提交

```bash
git add src/bot/templates.py
git commit -m "feat(bot): prefix [iOS] in render_broadcast title for iOS projects"
```

---

## Task 9: 文档更新（README + CLAUDE.md）

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`（仅在 Phase 状态处加一行）

### Step 1: README 加 iOS 支持段

在 README 适当位置（功能介绍或使用说明章节）加：

```markdown
## 平台支持

- **Google Play**：`project_id` 不含 "IOS" 子串 → 自动识别为 GP 项目
- **iOS App Store**：`project_id` 含 "IOS" 子串（如 `PRJ-IOS-001`）→ 自动识别为 iOS 项目

iOS 项目的"商店地址"列填写完整 App Store URL（如 `https://apps.apple.com/app/id1234567890`），系统通过 iTunes Search API 判断上架状态。

平台支持可通过提交 commit history 追溯：
- GP：HTML 启发式解析
- iOS：`https://itunes.apple.com/lookup?id={N}`
```

### Step 2: CLAUDE.md Phase 状态更新

在 CLAUDE.md「Phase 状态」段（line 88 附近）追加：

```markdown
- **iOS 平台支持**（已完成于 commit <HASH>）：`project_id` 含 "IOS" 子串的项目被识别为 iOS，走 iTunes Search API
```

（实际 commit hash 在 Task 1-8 完成后填）

### Step 3: 提交

```bash
git add README.md CLAUDE.md
git commit -m "docs: document iOS platform support"
```

---

## Self-Review

按 writing-plans skill 要求做：

**1. Spec 覆盖检查**：spec §1.4 → §12 各要求项对应到任务：
- §1.2 目标 1 (不新加列) → 全部任务未新加列 ✓
- §1.2 目标 2 (不上锁新字段) → 未动 `LOCKED_RECOGNIZED_AS` ✓
- §1.2 目标 3 (复用 StatusCode) → 未动 `status.py` ✓
- §1.2 目标 4 (iTunes Search API) → Task 3 实施 ✓
- §1.3 不做清单 → 全部不在任务范围 ✓
- §3.1 `Project.platform` 派生 → Task 1 ✓
- §4.3 `_check_ios_app` → Task 3 ✓
- §5.1-5.3 scheduler 三处调用 → Task 5 ✓
- §6.1 chip → Task 7 ✓
- §6.2 smart-defaults → Task 6 ✓
- §7.1 广播前缀 → Task 8 ✓
- §9.1 测试文件清单 → Task 1, 2, 3, 4, 5 ✓
- §10.1 验收标准 → 跨任务覆盖（每个 task 结尾"跑全量测试"）✓
- §11 回滚 → 每任务独立 commit ✓
- §12 不做清单 → 不在任务范围 ✓

**2. 占位扫描**：检查无 TBD / TODO / "fill in"；`tests/integration/test_scheduler_jobs_ios.py` 在 Task 5 中明确要求"先 Read `tests/test_scheduler_jobs.py` 再按现有 mock 范式写"，不是占位，是必要的实施指引。

**3. 类型一致性**：
- `Project.platform: Literal["gp", "ios"]` 在 Task 1 定义，Task 5 / 7 / 8 都直接读 `project.platform` ✓
- `extract_app_store_id(url) -> Optional[int]` 在 Task 2 定义，Task 3 调用 ✓
- `_check_ios_app(url, *, proxy=None, timeout=15.0) -> dict` 在 Task 3 定义，Task 4 dispatcher 调用 ✓
- `check_app_published(url, platform="gp", proxy=None, timeout=15.0) -> dict` 在 Task 4 定义，Task 5 三处调用 ✓

**4. 范围检查**：9 个任务，每任务独立 commit + 独立测试。一个 commit reviewer 可独立批准。

---

## 验收确认（最后一个 commit 后）

执行：

```bash
python -m pytest -v
```

预期：
- `tests/unit/test_platform_detection.py`：6 PASS
- `tests/unit/test_extract_app_store_id.py`：8 PASS
- `tests/unit/test_store_checker_ios.py`：8 PASS（6 from Task 3 + 2 from Task 4）
- `tests/integration/test_scheduler_jobs_ios.py`：3 PASS（按现有 mock 范式完成后）

手动验证（Task 6 / 7 / 8 各一次）：
- 新项目表单输入 `PRJ-IOS-001` → GP autofill 不触发 ✓
- overview + project_detail 显示 `📱 iOS` / `🤖 GP` chip ✓
- `/dryrun` 输出 iOS 项目带 `[iOS] ` 前缀 ✓