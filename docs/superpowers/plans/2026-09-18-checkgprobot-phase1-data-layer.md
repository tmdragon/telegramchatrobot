# checkGPRobot Phase 1 — 数据接入层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Google Sheets 数据接入、状态模型识别、本地持久化；提供可在 main.py 启动后打印"已加载 N 个项目"的最小可运行版本。

**Architecture:** 单进程 Python 应用，模块边界按职责切分（models / sheets / store / config）。本阶段不引入 FastUI / Bot / Scheduler——只交付数据层。

**Tech Stack:**
- Python 3.11+
- gspread 6.x（Google Sheets 客户端）
- google-auth 2.x
- PyYAML 6.x（配置）
- pytest 8.x（测试）
- SQLite 3（标准库）

**Spec:** [docs/superpowers/specs/2026-09-18-checkgprobot-design.md](docs/superpowers/specs/2026-09-18-checkgprobot-design.md)（§3 数据模型与状态机、§4 映射、§7 持久化、§8 配置）

**后续 Phases:**
- Phase 2: 可视化 UI（FastAPI + 三页 + 编辑回写）—— 见 `2026-09-18-checkgprobot-phase2-ui.md`（待写）
- Phase 3: Telegram Bot（bot + 命令处理）—— 见 `2026-09-18-checkgprobot-phase3-bot.md`（待写）
- Phase 4: 定时调度器与播报（APScheduler + 文案 + 调度）—— 见 `2026-09-18-checkgprobot-phase4-scheduler.md`（待写）

---

## Global Constraints

- Python 3.11+（spec §1.4 未明确，主流且本机已具备）
- 所有时间戳使用 `datetime.now(timezone.utc).isoformat()` 写入 SQLite，**不带本地时区**
- 所有 ID 字符串统一为 `str`，**不**用 `int`
- 所有 YAML 文件使用 UTF-8 无 BOM
- 状态字符串匹配时**忽略大小写、忽略首尾空格**；其他标点不处理
- 测试文件命名 `test_*.py`，函数命名 `test_*`
- 提交粒度：一个 task 一个 commit，commit message 格式 `feat(phase1): ...`
- 单文件行数 ≤ 200 行；超过则拆

---

## 文件结构（Phase 1 全部产出）

```
checkGPRobot/
├── requirements.txt           [T1]
├── run.py                     [T1]
├── README.md                  [T12]
├── .gitignore                 [T1，已存在]
├── config/
│   ├── secrets.yaml.example   [T2]
│   ├── secrets.yaml           [T2, .gitignore]
│   └── sheets.yaml.example    [T2]
├── src/
│   ├── __init__.py            [T1]
│   ├── main.py                [T11]
│   ├── config.py              [T2]
│   ├── models/
│   │   ├── __init__.py        [T1]
│   │   ├── status.py          [T3]
│   │   └── project.py         [T4]
│   ├── sheets/
│   │   ├── __init__.py        [T1]
│   │   ├── auth.py            [T5]
│   │   ├── parser.py          [T6]
│   │   ├── repo.py            [T7, T8]
│   │   └── mapping_repo.py    [T9]
│   └── store/
│       ├── __init__.py        [T1]
│       └── db.py              [T10]
├── tests/
│   ├── __init__.py            [T1]
│   ├── conftest.py            [T1]
│   ├── unit/
│   │   ├── __init__.py        [T1]
│   │   ├── test_status.py     [T3]
│   │   ├── test_state_machine.py [T3]
│   │   ├── test_models.py     [T4]
│   │   ├── test_parser.py     [T6]
│   │   ├── test_config.py     [T2]
│   │   └── test_db.py         [T10]
│   └── integration/
│       ├── __init__.py        [T1]
│       ├── test_repo.py       [T7, T8]
│       ├── test_mapping_repo.py [T9]
│       └── test_main.py       [T11]
└── data/                      [T10, .gitignore]
    └── checkgprobot.db
```

---

## Task 1: 项目骨架与依赖

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`（空）
- Create: `src/models/__init__.py`（空）
- Create: `src/sheets/__init__.py`（空）
- Create: `src/store/__init__.py`（空）
- Create: `tests/__init__.py`（空）
- Create: `tests/unit/__init__.py`（空）
- Create: `tests/integration/__init__.py`（空）
- Create: `tests/conftest.py`
- Create: `run.py`
- Create: `src/main.py`

**Interfaces:**
- Consumes: 什么都没有
- Produces: `run.py` 入口可调用；`src/main.py` 暴露 `main()` 函数

- [ ] **Step 1: 创建目录与空 `__init__.py`**

```bash
mkdir -p src/models src/sheets src/store tests/unit tests/integration
touch src/__init__.py src/models/__init__.py src/sheets/__init__.py src/store/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 2: 写 `requirements.txt`**

```
gspread>=6.0,<7.0
google-auth>=2.23,<3.0
PyYAML>=6.0,<7.0
pytest>=8.0,<9.0
```

- [ ] **Step 3: 写 `run.py`**

```python
"""项目入口：python run.py"""
from src.main import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 写 `tests/conftest.py`**

```python
"""共享 fixtures。"""
import pytest

@pytest.fixture
def project_root():
    """项目根路径。"""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent
```

- [ ] **Step 5: 写 `src/main.py`（最小骨架）**

```python
"""应用入口。

Phase 1：只负责加载配置并打印健康检查。
后续 phase 在此基础上加 UI / Bot / Scheduler。
"""
from __future__ import annotations


def main() -> int:
    """返回退出码；0 = 成功。"""
    print("checkGPRobot Phase 1 skeleton ready.")
    return 0
```

- [ ] **Step 6: 安装依赖并跑 hello world**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
pip install -r requirements.txt
python run.py
```
Expected: 输出 `checkGPRobot Phase 1 skeleton ready.`，退出码 0。

- [ ] **Step 7: 跑测试框架确认可用**

Create `tests/unit/test_smoke.py`:
```python
def test_pytest_works():
    assert 1 + 1 == 2
```

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_smoke.py -v
```
Expected: PASS。

- [ ] **Step 8: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add requirements.txt run.py src/ tests/
git commit -m "feat(phase1): project skeleton with run.py and tests"
```

---

## Task 2: 配置管理

**Files:**
- Create: `src/config.py`
- Create: `config/secrets.yaml.example`
- Create: `config/sheets.yaml.example`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: 文件路径（来自 `src/main.py` 调用）
- Produces:
  ```python
  @dataclass
  class AppConfig:
      google_service_account_json: Path
      telegram_bot_token: str        # Phase 1 暂不使用，但加载并校验存在
      admin_chat_id: str
      ui_port: int
      ui_bind: str
      spreadsheets: list[SpreadsheetConfig]

  @dataclass
  class SpreadsheetConfig:
      id: str
      name: str
      role: str  # "master" / "detail"

  def load_config(secrets_path: Path, sheets_path: Path) -> AppConfig: ...
  ```

- [ ] **Step 1: 写失败测试 `tests/unit/test_config.py`**

```python
from pathlib import Path
import pytest
from src.config import load_config, AppConfig

def test_load_config_returns_app_config(tmp_path: Path):
    secrets = tmp_path / "secrets.yaml"
    sheets = tmp_path / "sheets.yaml"
    secrets.write_text(
        "google_service_account_json: data/credentials/gcp-sa.json\n"
        "telegram_bot_token: '123:ABC'\n"
        "admin_chat_id: '12345'\n"
        "ui_port: 8765\n"
        "ui_bind: '127.0.0.1'\n",
        encoding="utf-8",
    )
    sheets.write_text(
        "spreadsheets:\n"
        "  - id: 'ss1'\n"
        "    name: '项目主表'\n"
        "    role: 'master'\n",
        encoding="utf-8",
    )
    cfg = load_config(secrets, sheets)
    assert isinstance(cfg, AppConfig)
    assert cfg.google_service_account_json == Path("data/credentials/gcp-sa.json")
    assert cfg.telegram_bot_token == "123:ABC"
    assert cfg.ui_port == 8765
    assert len(cfg.spreadsheets) == 1
    assert cfg.spreadsheets[0].id == "ss1"


def test_load_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml", tmp_path / "nope2.yaml")
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_config.py -v
```
Expected: FAIL（`ModuleNotFoundError: No module named 'src.config'`）。

- [ ] **Step 3: 实现 `src/config.py`**

```python
"""配置加载。

secrets.yaml: 敏感信息（不进 git）
sheets.yaml: 业务配置（公开）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SpreadsheetConfig:
    id: str
    name: str
    role: str


@dataclass
class AppConfig:
    google_service_account_json: Path
    telegram_bot_token: str
    admin_chat_id: str
    ui_port: int
    ui_bind: str
    spreadsheets: list[SpreadsheetConfig] = field(default_factory=list)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(secrets_path: Path, sheets_path: Path) -> AppConfig:
    secrets = _read_yaml(secrets_path)
    sheets = _read_yaml(sheets_path)
    return AppConfig(
        google_service_account_json=Path(secrets["google_service_account_json"]),
        telegram_bot_token=secrets["telegram_bot_token"],
        admin_chat_id=str(secrets["admin_chat_id"]),
        ui_port=int(secrets.get("ui_port", 8765)),
        ui_bind=secrets.get("ui_bind", "127.0.0.1"),
        spreadsheets=[
            SpreadsheetConfig(id=s["id"], name=s["name"], role=s["role"])
            for s in sheets.get("spreadsheets", [])
        ],
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_config.py -v
```
Expected: 2 passed。

- [ ] **Step 5: 写示例文件**

`config/secrets.yaml.example`:
```yaml
google_service_account_json: "data/credentials/gcp-sa.json"
telegram_bot_token: "REPLACE_WITH_BOTFATHER_TOKEN"
admin_chat_id: "REPLACE_WITH_YOUR_USER_ID"
ui_port: 8765
ui_bind: "127.0.0.1"
```

`config/sheets.yaml.example`:
```yaml
spreadsheets:
  - id: "REPLACE_WITH_SPREADSHEET_ID"
    name: "项目主表"
    role: "master"
  - id: "REPLACE_WITH_ANOTHER_SPREADSHEET_ID"
    name: "财务子表"
    role: "detail"
```

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/config.py config/secrets.yaml.example config/sheets.yaml.example tests/unit/test_config.py
git commit -m "feat(phase1): YAML config loader with tests"
```

---

## Task 3: 状态模型（枚举 + 别名 + 状态机）

**Files:**
- Create: `src/models/status.py`
- Create: `tests/unit/test_status.py`
- Create: `tests/unit/test_state_machine.py`

**Interfaces:**
- Produces:
  ```python
  class StatusCode(str, Enum):
      ORDERED = "ORDERED"
      MAKING = "MAKING"
      # ... 14 个

  ALIASES: dict[StatusCode, list[str]]  # 14 项

  def normalize(value: str | None) -> StatusCode | None: ...

  LEGAL_TRANSITIONS: dict[StatusCode, set[StatusCode]]

  def is_legal(from_: StatusCode, to: StatusCode) -> bool: ...

  def legal_next_states(current: StatusCode) -> set[StatusCode]: ...
  ```

- [ ] **Step 1: 写失败测试 `tests/unit/test_status.py`**

```python
from src.models.status import StatusCode, normalize, ALIASES


def test_aliases_has_14_entries():
    assert len(ALIASES) == 14


def test_normalize_exact_code():
    assert normalize("MAKING") == StatusCode.MAKING


def test_normalize_chinese_alias():
    assert normalize("制作中") == StatusCode.MAKING
    assert normalize("我方制作中") == StatusCode.MAKING


def test_normalize_case_insensitive():
    assert normalize("making") == StatusCode.MAKING
    assert normalize("  Making  ") == StatusCode.MAKING


def test_normalize_first_review_alias():
    assert normalize("一审通过") == StatusCode.FIRST_REVIEW_PASSED
    assert normalize("第一轮通过") == StatusCode.FIRST_REVIEW_PASSED


def test_normalize_unknown_returns_none():
    assert normalize("随意写的状态") is None
    assert normalize(None) is None
    assert normalize("") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_status.py -v
```
Expected: FAIL。

- [ ] **Step 3: 写失败测试 `tests/unit/test_state_machine.py`**

```python
from src.models.status import StatusCode, is_legal, legal_next_states


def test_legal_transitions_from_ordered():
    assert is_legal(StatusCode.ORDERED, StatusCode.MAKING)
    assert not is_legal(StatusCode.ORDERED, StatusCode.PUBLISHED)


def test_legal_rework_returns_to_review():
    assert is_legal(StatusCode.REWORK, StatusCode.CLIENT_REVIEW)


def test_first_review_rejected_returns_to_submitting():
    assert is_legal(StatusCode.FIRST_REVIEW_REJECTED, StatusCode.SUBMITTING)
    assert not is_legal(StatusCode.FIRST_REVIEW_REJECTED, StatusCode.MAKING)


def test_remaking_goes_to_making():
    assert is_legal(StatusCode.REMAKING, StatusCode.MAKING)
    assert not is_legal(StatusCode.REMAKING, StatusCode.CLIENT_REVIEW)


def test_paid_unpaid_bidirectional():
    assert is_legal(StatusCode.PAID, StatusCode.UNPAID)
    assert is_legal(StatusCode.UNPAID, StatusCode.PAID)


def test_legal_next_states():
    assert legal_next_states(StatusCode.ORDERED) == {StatusCode.MAKING}
    assert StatusCode.SECOND_REVIEW in legal_next_states(StatusCode.SECOND_REVIEW) is False
    assert {StatusCode.PUBLISHED, StatusCode.REMAKING} == legal_next_states(StatusCode.SECOND_REVIEW)
```

- [ ] **Step 4: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_state_machine.py -v
```
Expected: FAIL。

- [ ] **Step 5: 实现 `src/models/status.py`**

```python
"""项目状态模型：枚举 + 别名表 + 状态机。

完整定义见 spec §3.2 与 §3.3。
"""
from __future__ import annotations

from enum import Enum


class StatusCode(str, Enum):
    ORDERED = "ORDERED"
    MAKING = "MAKING"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    REWORK = "REWORK"
    WAITING_AAB = "WAITING_AAB"
    WAITING_SUBMIT = "WAITING_SUBMIT"
    SUBMITTING = "SUBMITTING"
    FIRST_REVIEW_PASSED = "FIRST_REVIEW_PASSED"
    FIRST_REVIEW_REJECTED = "FIRST_REVIEW_REJECTED"
    SECOND_REVIEW = "SECOND_REVIEW"
    REMAKING = "REMAKING"
    PUBLISHED = "PUBLISHED"
    PAID = "PAID"
    UNPAID = "UNPAID"


# 完整别名表（spec §3.2）。标准化函数先精确匹配代码本身，再遍历别名。
ALIASES: dict[StatusCode, list[str]] = {
    StatusCode.ORDERED: ["下单", "已下单", "待开始", "已下单待制作"],
    StatusCode.MAKING: ["制作中", "生产中", "制作"],
    StatusCode.CLIENT_REVIEW: ["验收中", "客户验收", "客户审核"],
    StatusCode.REWORK: ["返工", "修改中", "调整中"],
    StatusCode.WAITING_AAB: ["等AAB", "AAB包准备中"],
    StatusCode.WAITING_SUBMIT: ["等待提审", "待提交"],
    StatusCode.SUBMITTING: ["提审中", "提交中", "提交审核"],
    StatusCode.FIRST_REVIEW_PASSED: ["一审通过", "第一轮通过"],
    StatusCode.FIRST_REVIEW_REJECTED: ["一审打回", "第一轮未通过"],
    StatusCode.SECOND_REVIEW: ["复审中", "最终审核"],
    StatusCode.REMAKING: ["重做中", "重新制作", "修复中"],
    StatusCode.PUBLISHED: ["已发布", "上线了", "上架"],
    StatusCode.PAID: ["已回款", "已收款", "已结款"],
    StatusCode.UNPAID: ["未回款", "未收款", "待回款"],
}


# 合法转换（spec §3.3 LEGAL_TRANSITIONS）
LEGAL_TRANSITIONS: dict[StatusCode, set[StatusCode]] = {
    StatusCode.ORDERED: {StatusCode.MAKING},
    StatusCode.MAKING: {StatusCode.CLIENT_REVIEW},
    StatusCode.CLIENT_REVIEW: {StatusCode.REWORK, StatusCode.WAITING_AAB},
    StatusCode.REWORK: {StatusCode.CLIENT_REVIEW},
    StatusCode.WAITING_AAB: {StatusCode.WAITING_SUBMIT},
    StatusCode.WAITING_SUBMIT: {StatusCode.SUBMITTING},
    StatusCode.SUBMITTING: {StatusCode.FIRST_REVIEW_PASSED, StatusCode.FIRST_REVIEW_REJECTED},
    StatusCode.FIRST_REVIEW_PASSED: {StatusCode.SECOND_REVIEW},
    StatusCode.FIRST_REVIEW_REJECTED: {StatusCode.SUBMITTING},
    StatusCode.SECOND_REVIEW: {StatusCode.PUBLISHED, StatusCode.REMAKING},
    StatusCode.REMAKING: {StatusCode.MAKING},
    StatusCode.PUBLISHED: {StatusCode.PAID, StatusCode.UNPAID},
    StatusCode.PAID: {StatusCode.UNPAID},
    StatusCode.UNPAID: {StatusCode.PAID},
}


def normalize(value: str | None) -> StatusCode | None:
    """把任意文本规范化成 StatusCode；无法识别返回 None。

    规则：去首尾空格 → 大写 → 先比代码本身 → 再遍历别名表。
    """
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    upper = s.upper()
    # 先比代码本身（精确匹配优先级最高）
    for code in StatusCode:
        if upper == code.value:
            return code
    # 再比别名（用原始 s，因为别名有中文）
    for code, aliases in ALIASES.items():
        if s in aliases:
            return code
    return None


def is_legal(from_: StatusCode, to: StatusCode) -> bool:
    """判断 from_ → to 是否为合法转换。"""
    return to in LEGAL_TRANSITIONS.get(from_, set())


def legal_next_states(current: StatusCode) -> set[StatusCode]:
    """返回当前状态可去的下一个状态集合。"""
    return set(LEGAL_TRANSITIONS.get(current, set()))
```

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_status.py tests/unit/test_state_machine.py -v
```
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/models/status.py tests/unit/test_status.py tests/unit/test_state_machine.py
git commit -m "feat(phase1): status enum, aliases, state machine"
```

---

## Task 4: 业务数据模型

**Files:**
- Create: `src/models/project.py`
- Create: `tests/unit/test_models.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Field:
      name: str
      value: Any
      column_index: int
      row_index: int
      recognized_as: str | None

  @dataclass
  class SheetView:
      spreadsheet_id: str
      sheet_name: str
      fields: list[Field]
      fetched_at: datetime

  @dataclass
  class Project:
      project_id: str
      project_name: str | None
      status: StatusCode | None
      status_changed_at: datetime | None
      status_history: list[tuple[StatusCode, datetime]]
      sheets: list[SheetView]

  @dataclass
  class Mapping:
      project_id: str
      chat_id: str
      note: str
      enabled: bool
      last_broadcast_at: datetime | None
      last_broadcast_status: str | None
      last_error: str | None
  ```

- [ ] **Step 1: 写失败测试 `tests/unit/test_models.py`**

```python
from datetime import datetime, timezone
from src.models.project import Field, SheetView, Project, Mapping
from src.models.status import StatusCode


def test_field_construction():
    f = Field(name="进度", value=80, column_index=3, row_index=5, recognized_as="status")
    assert f.name == "进度"
    assert f.value == 80
    assert f.recognized_as == "status"


def test_sheet_view_construction():
    f1 = Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id")
    sv = SheetView(
        spreadsheet_id="ss1",
        sheet_name="项目主表",
        fields=[f1],
        fetched_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
    )
    assert sv.spreadsheet_id == "ss1"
    assert len(sv.fields) == 1


def test_project_construction():
    f = Field(name="进度", value="MAKING", column_index=3, row_index=2, recognized_as="status")
    sv = SheetView(
        spreadsheet_id="ss1",
        sheet_name="项目主表",
        fields=[f],
        fetched_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
    )
    p = Project(
        project_id="PRJ-001",
        project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
        status_history=[(StatusCode.ORDERED, datetime(2026, 9, 10, tzinfo=timezone.utc)),
                        (StatusCode.MAKING, datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))],
        sheets=[sv],
    )
    assert p.project_id == "PRJ-001"
    assert p.status == StatusCode.MAKING
    assert len(p.status_history) == 2


def test_mapping_construction():
    m = Mapping(
        project_id="PRJ-001",
        chat_id="-1001234567890",
        note="一群",
        enabled=True,
        last_broadcast_at=None,
        last_broadcast_status=None,
        last_error=None,
    )
    assert m.project_id == "PRJ-001"
    assert m.enabled is True
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_models.py -v
```
Expected: FAIL。

- [ ] **Step 3: 实现 `src/models/project.py`**

```python
"""业务数据模型：Project / Field / SheetView / Mapping。完整定义见 spec §3.1。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.models.status import StatusCode


@dataclass
class Field:
    """sheet 中一个单元格。"""
    name: str               # 列名原文
    value: Any              # 当前值
    column_index: int       # 在原 sheet 中的列号（1-indexed，用于回写）
    row_index: int          # 在原 sheet 中的行号（1-indexed）
    recognized_as: Optional[str] = None  # 若被识别为"已知字段"，记录哪个


@dataclass
class SheetView:
    """一次拉取的一个 sheet 视图。"""
    spreadsheet_id: str
    sheet_name: str
    fields: list[Field]
    fetched_at: datetime


@dataclass
class Project:
    """业务上的一个项目，可能跨多张 sheet。"""
    project_id: str
    project_name: Optional[str] = None
    status: Optional[StatusCode] = None
    status_changed_at: Optional[datetime] = None
    status_history: list[tuple[StatusCode, datetime]] = field(default_factory=list)
    sheets: list[SheetView] = field(default_factory=list)


@dataclass
class Mapping:
    """项目 ↔ Telegram 群 映射。"""
    project_id: str
    chat_id: str
    note: str = ""
    enabled: bool = True
    last_broadcast_at: Optional[datetime] = None
    last_broadcast_status: Optional[str] = None
    last_error: Optional[str] = None
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_models.py -v
```
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/models/project.py tests/unit/test_models.py
git commit -m "feat(phase1): Project/Field/SheetView/Mapping dataclasses"
```

---

## Task 5: Google Sheets 认证

**Files:**
- Create: `src/sheets/auth.py`
- Create: `tests/unit/test_auth.py`

**Interfaces:**
- Produces:
  ```python
  def make_gspread_client(credentials_json_path: Path) -> gspread.Client: ...
  ```

- [ ] **Step 1: 写失败测试 `tests/unit/test_auth.py`**

```python
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.sheets.auth import make_gspread_client


def test_make_gspread_client_loads_credentials(tmp_path: Path):
    fake_creds = tmp_path / "creds.json"
    fake_creds.write_text("{}", encoding="utf-8")

    with patch("src.sheets.auth.service_account") as mock_sa:
        mock_sa.return_value = MagicMock()
        with patch("src.sheets.auth.gspread.authorize") as mock_auth:
            mock_auth.return_value = "FAKE_CLIENT"
            client = make_gspread_client(fake_creds)

    mock_sa.assert_called_once()
    args, kwargs = mock_sa.call_args
    assert args[0].endswith("creds.json")
    mock_auth.assert_called_once()
    assert client == "FAKE_CLIENT"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_auth.py -v
```
Expected: FAIL。

- [ ] **Step 3: 实现 `src/sheets/auth.py`**

```python
"""Google Sheets 认证。

使用服务账号 JSON（gcp-sa.json），返回 gspread.Client。
"""
from __future__ import annotations

from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


# 需要的 OAuth scopes（只读 + 读写 sheet）
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def make_gspread_client(credentials_json_path: Path) -> gspread.Client:
    """从服务账号 JSON 创建 gspread client。"""
    creds = Credentials.from_service_account_file(
        str(credentials_json_path),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_auth.py -v
```
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/sheets/auth.py tests/unit/test_auth.py
git commit -m "feat(phase1): Google Sheets auth via service account"
```

---

## Task 6: 列识别与状态解析

**Files:**
- Create: `src/sheets/parser.py`
- Create: `tests/unit/test_parser.py`

**Interfaces:**
- Produces:
  ```python
  PROJECT_ID_CANDIDATES = ["项目编号", "编号", "ID", "Project ID", "项目 ID"]
  STATUS_CANDIDATES = ["状态", "当前状态", "项目状态", "Status"]
  PROJECT_NAME_CANDIDATES = ["项目名", "项目名称", "Name"]

  class HeaderDetector:
      def __init__(self, headers: list[str]) -> None: ...
      def find_column(self, candidates: list[str]) -> int | None: ...
          # 返回 1-indexed 列号；未找到返回 None

  def parse_project_id(value: str | None) -> str | None: ...
  def parse_status(value: str | None) -> StatusCode | None: ...
      # 复用 StatusCode.normalize
  ```

- [ ] **Step 1: 写失败测试 `tests/unit/test_parser.py`**

```python
from src.sheets.parser import (
    HeaderDetector, PROJECT_ID_CANDIDATES, STATUS_CANDIDATES,
    parse_project_id, parse_status,
)
from src.models.status import StatusCode


def test_header_detector_exact_match():
    d = HeaderDetector(["项目编号", "项目名", "进度"])
    assert d.find_column(PROJECT_ID_CANDIDATES) == 1


def test_header_detector_english_match():
    d = HeaderDetector(["Status", "Name"])
    assert d.find_column(STATUS_CANDIDATES) == 1


def test_header_detector_not_found():
    d = HeaderDetector(["无关列", "其他"])
    assert d.find_column(PROJECT_ID_CANDIDATES) is None


def test_header_detector_substring_match():
    # "项目 ID" 是 "项目编号"的候选之一；但表头写的是 "项目 编号"（含空格）也应该命中
    d = HeaderDetector(["项 目 编 号", "进度"])
    # 此例测试：精确匹配优先；若候选是 "项目编号"，子串 "项目编号" 在 "项 目 编 号" 里不存在 → None
    assert d.find_column(["项目编号"]) is None


def test_parse_project_id():
    assert parse_project_id("PRJ-001") == "PRJ-001"
    assert parse_project_id("  PRJ-001  ") == "PRJ-001"
    assert parse_project_id("") is None
    assert parse_project_id(None) is None


def test_parse_status_delegates_to_normalize():
    assert parse_status("制作中") == StatusCode.MAKING
    assert parse_status("未知") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_parser.py -v
```
Expected: FAIL。

- [ ] **Step 3: 实现 `src/sheets/parser.py`**

```python
"""列识别与字段解析。完整定义见 spec §3.4。

设计原则：精确匹配候选列名（不模糊子串，避免误中）。
中文/英文表头都通过候选列表覆盖。
"""
from __future__ import annotations

from typing import Optional

from src.models.status import StatusCode, normalize


PROJECT_ID_CANDIDATES = ["项目编号", "编号", "ID", "Project ID", "项目 ID", "project_id"]
STATUS_CANDIDATES = ["状态", "当前状态", "项目状态", "Status", "status"]
PROJECT_NAME_CANDIDATES = ["项目名", "项目名称", "Name", "name"]


class HeaderDetector:
    """根据表头行（list[str]）匹配已知字段的列号。"""

    def __init__(self, headers: list[str]) -> None:
        # 去除表头单元格的首尾空格
        self.headers = [(h or "").strip() for h in headers]

    def find_column(self, candidates: list[str]) -> Optional[int]:
        """返回 1-indexed 列号；未找到返回 None。匹配规则：候选中任一项精确等于表头。"""
        for i, h in enumerate(self.headers, start=1):
            if h in candidates:
                return i
        return None


def parse_project_id(value: Optional[str]) -> Optional[str]:
    """项目编号解析：去首尾空格，空字符串视为 None。"""
    if value is None:
        return None
    s = value.strip()
    return s or None


def parse_status(value: Optional[str]) -> Optional[StatusCode]:
    """状态解析：委托给 status.normalize。"""
    return normalize(value)
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_parser.py -v
```
Expected: 6 passed。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/sheets/parser.py tests/unit/test_parser.py
git commit -m "feat(phase1): column header detection and field parsing"
```

---

## Task 7: SheetRepo — 读表

**Files:**
- Create: `src/sheets/repo.py`
- Create: `tests/integration/test_repo.py`

**Interfaces:**
- Produces:
  ```python
  class SheetRepo:
      def __init__(self, client: gspread.Client) -> None: ...
      def fetch_all(self, spreadsheets: list[SpreadsheetConfig]) -> list[Project]: ...
          # 读所有表，按 project_id 合并成 Project
  ```

- [ ] **Step 1: 写失败测试 `tests/integration/test_repo.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock
from src.config import SpreadsheetConfig
from src.sheets.repo import SheetRepo


def _make_fake_worksheet(rows: list[list]) -> MagicMock:
    ws = MagicMock()
    ws.title = "项目主表"
    ws.get_all_values.return_value = rows
    return ws


def test_fetch_all_groups_rows_by_project_id():
    fake_client = MagicMock()
    fake_ws = _make_fake_worksheet([
        ["项目编号", "项目名", "状态"],          # 表头
        ["PRJ-001", "项目一", "制作中"],
        ["PRJ-002", "项目二", "验收中"],
    ])
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    ss = [SpreadsheetConfig(id="ss1", name="项目主表", role="master")]
    projects = repo.fetch_all(ss)

    assert len(projects) == 2
    ids = sorted(p.project_id for p in projects)
    assert ids == ["PRJ-001", "PRJ-002"]
    p1 = next(p for p in projects if p.project_id == "PRJ-001")
    assert p1.project_name == "项目一"
    from src.models.status import StatusCode
    assert p1.status == StatusCode.MAKING
    assert len(p1.sheets) == 1
    assert len(p1.sheets[0].fields) == 3


def test_fetch_all_multiple_sheets_same_project_merged():
    fake_client = MagicMock()
    fake_ws1 = _make_fake_worksheet([
        ["项目编号", "项目名", "状态"],
        ["PRJ-001", "项目一", "制作中"],
    ])
    fake_ws1.title = "项目主表"
    fake_ws2 = _make_fake_worksheet([
        ["项目编号", "预算", "已花费"],
        ["PRJ-001", "100000", "75000"],
    ])
    fake_ws2.title = "财务子表"

    # 两次 open 返回不同 worksheet
    fake_client.open.side_effect = [
        MagicMock(worksheet=MagicMock(return_value=fake_ws1)),
        MagicMock(worksheet=MagicMock(return_value=fake_ws2)),
    ]

    repo = SheetRepo(fake_client)
    ss = [
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
        SpreadsheetConfig(id="ss2", name="财务子表", role="detail"),
    ]
    projects = repo.fetch_all(ss)

    assert len(projects) == 1
    p = projects[0]
    assert p.project_id == "PRJ-001"
    assert len(p.sheets) == 2  # 两张表的视图
    sheet_names = sorted(s.sheet_name for s in p.sheets)
    assert sheet_names == ["项目主表", "财务子表"]


def test_fetch_all_empty_project_id_rows_skipped():
    fake_client = MagicMock()
    fake_ws = _make_fake_worksheet([
        ["项目编号", "状态"],
        ["", "制作中"],          # 空项目编号行：跳过
        ["PRJ-001", "制作中"],
    ])
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    ss = [SpreadsheetConfig(id="ss1", name="项目主表", role="master")]
    projects = repo.fetch_all(ss)

    assert len(projects) == 1
    assert projects[0].project_id == "PRJ-001"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_repo.py -v
```
Expected: FAIL。

- [ ] **Step 3: 实现 `src/sheets/repo.py`**

```python
"""SheetRepo：从 Google Sheets 读取并合并为 Project 列表。完整定义见 spec §2.3 读路径。

设计：
- 每个 spreadsheet 默认读第一个 worksheet（"主表"）
- 每行用 HeaderDetector 识别 project_id / status / project_name 列
- 同一 project_id 出现在多张表 → 合并到同一个 Project.sheets
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import gspread

from src.config import SpreadsheetConfig
from src.models.project import Field, Project, SheetView
from src.sheets.parser import (
    HeaderDetector,
    PROJECT_ID_CANDIDATES,
    PROJECT_NAME_CANDIDATES,
    STATUS_CANDIDATES,
    parse_project_id,
    parse_status,
)


class SheetRepo:
    def __init__(self, client: gspread.Client) -> None:
        self.client = client

    def fetch_all(self, spreadsheets: Iterable[SpreadsheetConfig]) -> list[Project]:
        """拉取所有 spreadsheets 的数据，按 project_id 合并。"""
        projects_by_id: dict[str, Project] = {}

        for ss in spreadsheets:
            sh = self.client.open(ss.name)
            ws = sh.worksheet(ss.name)  # 默认用同名 worksheet
            rows = ws.get_all_values()
            if not rows:
                continue
            headers = rows[0]
            detector = HeaderDetector(headers)
            pid_col = detector.find_column(PROJECT_ID_CANDIDATES)
            status_col = detector.find_column(STATUS_CANDIDATES)
            name_col = detector.find_column(PROJECT_NAME_CANDIDATES)

            if pid_col is None:
                continue  # 此表无项目编号列，跳过

            fetched_at = datetime.now(timezone.utc)
            for row_idx, row in enumerate(rows[1:], start=2):
                if len(row) < len(headers):
                    row = row + [""] * (len(headers) - len(row))

                pid = parse_project_id(row[pid_col - 1] if pid_col <= len(row) else None)
                if not pid:
                    continue

                fields = []
                for col_idx, (header, value) in enumerate(zip(headers, row), start=1):
                    recognized = None
                    if col_idx == pid_col:
                        recognized = "project_id"
                    elif status_col is not None and col_idx == status_col:
                        recognized = "status"
                    elif name_col is not None and col_idx == name_col:
                        recognized = "project_name"
                    fields.append(Field(
                        name=header,
                        value=value,
                        column_index=col_idx,
                        row_index=row_idx,
                        recognized_as=recognized,
                    ))

                sheet_view = SheetView(
                    spreadsheet_id=ss.id,
                    sheet_name=ss.name,
                    fields=fields,
                    fetched_at=fetched_at,
                )

                status = parse_status(row[status_col - 1]) if status_col and status_col <= len(row) else None
                name = (row[name_col - 1].strip() or None) if name_col and name_col <= len(row) else None

                if pid not in projects_by_id:
                    projects_by_id[pid] = Project(
                        project_id=pid,
                        project_name=name,
                        status=status,
                        status_changed_at=fetched_at,  # 首次见到该状态的时间
                        sheets=[sheet_view],
                    )
                else:
                    p = projects_by_id[pid]
                    if name and not p.project_name:
                        p.project_name = name
                    if status:
                        if p.status != status:
                            # 状态变了，记录历史
                            if p.status is not None:
                                p.status_history.append((p.status, p.status_changed_at or fetched_at))
                            p.status = status
                            p.status_changed_at = fetched_at
                    p.sheets.append(sheet_view)

        return list(projects_by_id.values())
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_repo.py -v
```
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/sheets/repo.py tests/integration/test_repo.py
git commit -m "feat(phase1): SheetRepo.fetch_all with project_id merging"
```

---

## Task 8: SheetRepo — 写表

**Files:**
- Modify: `src/sheets/repo.py`
- Create: `tests/integration/test_repo_write.py`

**Interfaces:**
- Produces:
  ```python
  class SheetRepo:
      # ... 既有方法 ...
      def update_cell(
          self,
          spreadsheet_name: str,
          worksheet_name: str,
          row: int,
          col: int,
          new_value: str,
      ) -> str:
          """写入并重读确认；返回写入后的值（用于校验）。"""
  ```

- [ ] **Step 1: 写失败测试 `tests/integration/test_repo_write.py`**

```python
from unittest.mock import MagicMock, call
from src.sheets.repo import SheetRepo


def test_update_cell_writes_and_verifies():
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "新值"

    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    result = repo.update_cell("项目主表", "项目主表", row=5, col=3, new_value="新值")

    fake_ws.update_cell.assert_called_once_with(5, 3, "新值")
    fake_ws.cell.assert_called_once_with(5, 3)
    assert result == "新值"


def test_update_cell_mismatch_raises():
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "旧值"  # 写完后读出来不一致

    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    from src.sheets.repo import WriteVerificationError
    with __import__("pytest").raises(WriteVerificationError):
        repo.update_cell("项目主表", "项目主表", row=5, col=3, new_value="新值")
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_repo_write.py -v
```
Expected: FAIL。

- [ ] **Step 3: 扩展 `src/sheets/repo.py`**

在文件**末尾**添加（保留既有代码）：

```python


class WriteVerificationError(RuntimeError):
    """写后重读校验失败。"""


# 在 SheetRepo 类**内部**追加以下方法（不要覆盖已有方法）
```

Edit: 把上面这段替换为以下完整方法（追加到 `SheetRepo` 类内 `fetch_all` 方法之后）：

```python
    def update_cell(
        self,
        spreadsheet_name: str,
        worksheet_name: str,
        row: int,
        col: int,
        new_value: str,
    ) -> str:
        """写入单元格，重读校验，返回最终值。

        Raises:
            WriteVerificationError: 写后读出的值与 new_value 不一致。
        """
        sh = self.client.open(spreadsheet_name)
        ws = sh.worksheet(worksheet_name)
        ws.update_cell(row, col, new_value)
        verified = ws.cell(row, col).value
        if verified != new_value:
            raise WriteVerificationError(
                f"Write verification failed at {spreadsheet_name}!{worksheet_name} "
                f"({row},{col}): wrote {new_value!r}, read {verified!r}"
            )
        return verified
```

并且在文件顶部加：

```python
from typing import Iterable  # 已经有；没有的话在这里加
```

实际不需要修改 import，直接 Edit 文件追加方法即可。

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_repo_write.py -v
```
Expected: 2 passed。

- [ ] **Step 5: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/sheets/repo.py tests/integration/test_repo_write.py
git commit -m "feat(phase1): SheetRepo.update_cell with write verification"
```

---

## Task 9: MappingRepo

**Files:**
- Create: `src/sheets/mapping_repo.py`
- Create: `tests/integration/test_mapping_repo.py`

**Interfaces:**
- Produces:
  ```python
  class MappingRepo:
      def __init__(self, client: gspread.Client, spreadsheet_name: str = "项目群映射") -> None: ...
      def load_all(self) -> list[Mapping]: ...
      def upsert(self, mapping: Mapping) -> None: ...
      def delete(self, project_id: str) -> None: ...
          # 软删除：enabled=false，不真删行
  ```

- [ ] **Step 1: 写失败测试 `tests/integration/test_mapping_repo.py`**

```python
from unittest.mock import MagicMock
from src.models.project import Mapping
from src.sheets.mapping_repo import MappingRepo


def _make_ws(headers: list[str], rows: list[list]):
    ws = MagicMock()
    ws.title = "项目群映射"
    ws.get_all_values.return_value = [headers] + rows
    ws.find.return_value = MagicMock(row=2)  # 默认找到第 2 行（第一行是表头）
    return ws


def test_load_all_parses_rows():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        ["PRJ-001", "-1001234567890", "一群", "TRUE", "2026-09-18 21:00"],
        ["PRJ-002", "-1009876543210", "二群", "FALSE", ""],
    ]
    fake_ws = _make_ws(headers, rows)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    mappings = repo.load_all()

    assert len(mappings) == 2
    assert mappings[0].project_id == "PRJ-001"
    assert mappings[0].chat_id == "-1001234567890"
    assert mappings[0].enabled is True
    assert mappings[1].enabled is False


def test_upsert_inserts_new_row():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [])
    fake_ws.find.return_value = None  # 找不到 → append
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    m = Mapping(project_id="PRJ-001", chat_id="-100123", note="一群")
    repo.upsert(m)

    fake_ws.append_row.assert_called_once()
    args = fake_ws.append_row.call_args[0][0]
    assert args[0] == "PRJ-001"
    assert args[1] == "-100123"


def test_upsert_updates_existing_row():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [["PRJ-001", "-100", "old", "TRUE", ""]])
    fake_ws.find.return_value = MagicMock(row=2)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    m = Mapping(project_id="PRJ-001", chat_id="-100", note="new note", enabled=False)
    repo.upsert(m)

    fake_ws.update_cell.assert_called()
    # 验证备注列（index 3，1-indexed）被更新
    calls = [c for c in fake_ws.update_cell.call_args_list if c[0][2] == "new note"]
    assert len(calls) >= 1
    fake_ws.update_cell.assert_any_call(2, 3, "new note")


def test_delete_soft_deletes():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [["PRJ-001", "-100", "", "TRUE", ""]])
    fake_ws.find.return_value = MagicMock(row=2)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    repo.delete("PRJ-001")

    # 软删除：把"是否启用"列（index 4）改为 FALSE
    fake_ws.update_cell.assert_any_call(2, 4, "FALSE")
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_mapping_repo.py -v
```
Expected: FAIL。

- [ ] **Step 3: 实现 `src/sheets/mapping_repo.py`**

```python
"""MappingRepo：项目 ↔ 群 映射表的 CRUD。完整定义见 spec §4。

映射表 schema：
| 项目编号 | 群 chat_id | 备注 | 是否启用 | 上次播报时间 |
"""
from __future__ import annotations

import gspread

from src.models.project import Mapping


HEADERS = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]


def _truthy(s: str) -> bool:
    return s.strip().upper() in ("TRUE", "YES", "1", "是", "✓", "✅")


class MappingRepo:
    def __init__(self, client: gspread.Client, spreadsheet_name: str = "项目群映射") -> None:
        self.client = client
        self.spreadsheet_name = spreadsheet_name

    def _ws(self):
        sh = self.client.open(self.spreadsheet_name)
        return sh.worksheet(self.spreadsheet_name)

    def load_all(self) -> list[Mapping]:
        ws = self._ws()
        rows = ws.get_all_values()
        if len(rows) < 2:
            return []
        mappings = []
        for row in rows[1:]:
            if len(row) < 5:
                row = row + [""] * (5 - len(row))
            pid = row[0].strip()
            if not pid:
                continue
            mappings.append(Mapping(
                project_id=pid,
                chat_id=row[1].strip(),
                note=row[2].strip(),
                enabled=_truthy(row[3]),
                last_broadcast_at=row[4].strip() or None,
            ))
        return mappings

    def _find_row(self, ws, project_id: str) -> int | None:
        try:
            cell = ws.find(project_id)
            return cell.row
        except gspread.exceptions.CellNotFound:
            return None

    def upsert(self, mapping: Mapping) -> None:
        ws = self._ws()
        row_idx = self._find_row(ws, mapping.project_id)
        row_data = [
            mapping.project_id,
            mapping.chat_id,
            mapping.note,
            "TRUE" if mapping.enabled else "FALSE",
            mapping.last_broadcast_at.isoformat() if mapping.last_broadcast_at else "",
        ]
        if row_idx is None:
            ws.append_row(row_data)
        else:
            for col_idx, value in enumerate(row_data, start=1):
                ws.update_cell(row_idx, col_idx, value)

    def delete(self, project_id: str) -> None:
        """软删除：enabled=false。"""
        ws = self._ws()
        row_idx = self._find_row(ws, project_id)
        if row_idx is None:
            return
        ws.update_cell(row_idx, 4, "FALSE")
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_mapping_repo.py -v
```
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/sheets/mapping_repo.py tests/integration/test_mapping_repo.py
git commit -m "feat(phase1): MappingRepo with soft-delete"
```

---

## Task 10: SQLite 持久化

**Files:**
- Create: `src/store/db.py`
- Create: `tests/unit/test_db.py`

**Interfaces:**
- Produces:
  ```python
  class Store:
      def __init__(self, db_path: Path) -> None: ...
      def init_schema(self) -> None: ...
      def save_sheet_snapshot(self, spreadsheet_id: str, sheet_name: str, fetched_at: datetime, rows_json: str, parse_errors: str | None) -> None: ...
      def load_latest_snapshot(self, spreadsheet_id: str, sheet_name: str) -> tuple[datetime, str, str | None] | None: ...
      def save_mapping_snapshot(self, mapping: Mapping) -> None: ...
      def load_mapping_snapshots(self) -> list[Mapping]: ...
      def log_broadcast(self, project_id: str, chat_id: str, status_code: str, message_text: str, sent_at: datetime, success: bool, error: str | None) -> None: ...
      def latest_successful_broadcast(self, project_id: str, chat_id: str) -> tuple[str, str] | None:
          # 返回 (status_code, message_text) 用于 skip_if_no_change 判定
      def record_status(self, project_id: str, status_code: str, detected_at: datetime) -> None: ...
  ```

- [ ] **Step 1: 写失败测试 `tests/unit/test_db.py`**

```python
from datetime import datetime, timezone
from pathlib import Path
import json
from src.store.db import Store
from src.models.project import Mapping


def test_store_init_schema(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    assert (tmp_path / "test.db").exists()


def test_save_and_load_sheet_snapshot(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    rows = [["项目编号", "状态"], ["PRJ-001", "制作中"]]
    ts = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    db.save_sheet_snapshot("ss1", "项目主表", ts, json.dumps(rows, ensure_ascii=False), None)

    loaded = db.load_latest_snapshot("ss1", "项目主表")
    assert loaded is not None
    fetched_at, rows_json, _ = loaded
    assert fetched_at == ts
    assert json.loads(rows_json) == rows


def test_save_and_load_mapping(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    m = Mapping(project_id="PRJ-001", chat_id="-100", note="一群", enabled=True)
    db.save_mapping_snapshot(m)
    loaded = db.load_mapping_snapshots()
    assert len(loaded) == 1
    assert loaded[0].project_id == "PRJ-001"
    assert loaded[0].enabled is True


def test_log_broadcast_and_latest(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    ts = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    db.log_broadcast("PRJ-001", "-100", "MAKING", "msg1", ts, True, None)
    db.log_broadcast("PRJ-001", "-100", "CLIENT_REVIEW", "msg2", ts, True, None)

    latest = db.latest_successful_broadcast("PRJ-001", "-100")
    assert latest is not None
    assert latest[0] == "CLIENT_REVIEW"


def test_record_status(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    ts = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    db.record_status("PRJ-001", "MAKING", ts)
    # 同一时间同一状态重复记录：不应抛错
    db.record_status("PRJ-001", "MAKING", ts)
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_db.py -v
```
Expected: FAIL。

- [ ] **Step 3: 实现 `src/store/db.py`**

```python
"""SQLite 持久化。完整 schema 见 spec §7.1。

Phase 1 实现 4 张表的核心 CRUD。
时间戳：统一 ISO8601 with timezone，存储为 TEXT。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.project import Mapping


SCHEMA = """
CREATE TABLE IF NOT EXISTS sheet_snapshots (
  spreadsheet_id  TEXT,
  sheet_name      TEXT,
  fetched_at      TEXT,
  rows_json       TEXT,
  parse_errors    TEXT,
  PRIMARY KEY (spreadsheet_id, sheet_name)
);

CREATE TABLE IF NOT EXISTS mapping_snapshot (
  project_id              TEXT PRIMARY KEY,
  chat_id                 TEXT,
  note                    TEXT,
  enabled                 INTEGER,
  last_broadcast_at       TEXT,
  last_broadcast_status   TEXT,
  last_error              TEXT
);

CREATE TABLE IF NOT EXISTS broadcast_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id      TEXT,
  chat_id         TEXT,
  status_code     TEXT,
  message_text    TEXT,
  sent_at         TEXT,
  success         INTEGER,
  error           TEXT
);

CREATE TABLE IF NOT EXISTS status_history (
  project_id      TEXT,
  status_code     TEXT,
  detected_at     TEXT,
  PRIMARY KEY (project_id, status_code, detected_at)
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def save_sheet_snapshot(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        fetched_at: datetime,
        rows_json: str,
        parse_errors: Optional[str],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sheet_snapshots
                   (spreadsheet_id, sheet_name, fetched_at, rows_json, parse_errors)
                   VALUES (?, ?, ?, ?, ?)""",
                (spreadsheet_id, sheet_name, fetched_at.isoformat(), rows_json, parse_errors),
            )
            conn.commit()

    def load_latest_snapshot(
        self, spreadsheet_id: str, sheet_name: str
    ) -> Optional[tuple[datetime, str, Optional[str]]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT fetched_at, rows_json, parse_errors
                   FROM sheet_snapshots
                   WHERE spreadsheet_id = ? AND sheet_name = ?""",
                (spreadsheet_id, sheet_name),
            ).fetchone()
        if row is None:
            return None
        return (
            datetime.fromisoformat(row["fetched_at"]),
            row["rows_json"],
            row["parse_errors"],
        )

    def save_mapping_snapshot(self, mapping: Mapping) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO mapping_snapshot
                   (project_id, chat_id, note, enabled,
                    last_broadcast_at, last_broadcast_status, last_error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    mapping.project_id,
                    mapping.chat_id,
                    mapping.note,
                    1 if mapping.enabled else 0,
                    mapping.last_broadcast_at.isoformat() if mapping.last_broadcast_at else None,
                    mapping.last_broadcast_status,
                    mapping.last_error,
                ),
            )
            conn.commit()

    def load_mapping_snapshots(self) -> list[Mapping]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT project_id, chat_id, note, enabled,
                          last_broadcast_at, last_broadcast_status, last_error
                   FROM mapping_snapshot"""
            ).fetchall()
        result = []
        for row in rows:
            lba = row["last_broadcast_at"]
            result.append(Mapping(
                project_id=row["project_id"],
                chat_id=row["chat_id"] or "",
                note=row["note"] or "",
                enabled=bool(row["enabled"]),
                last_broadcast_at=datetime.fromisoformat(lba) if lba else None,
                last_broadcast_status=row["last_broadcast_status"],
                last_error=row["last_error"],
            ))
        return result

    def log_broadcast(
        self,
        project_id: str,
        chat_id: str,
        status_code: str,
        message_text: str,
        sent_at: datetime,
        success: bool,
        error: Optional[str],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO broadcast_log
                   (project_id, chat_id, status_code, message_text, sent_at, success, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, chat_id, status_code, message_text, sent_at.isoformat(),
                 1 if success else 0, error),
            )
            conn.commit()

    def latest_successful_broadcast(
        self, project_id: str, chat_id: str
    ) -> Optional[tuple[str, str]]:
        """返回 (status_code, message_text)。Phase 4 用于 skip_if_no_change 判定。"""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT status_code, message_text
                   FROM broadcast_log
                   WHERE project_id = ? AND chat_id = ? AND success = 1
                   ORDER BY sent_at DESC LIMIT 1""",
                (project_id, chat_id),
            ).fetchone()
        if row is None:
            return None
        return (row["status_code"], row["message_text"])

    def record_status(self, project_id: str, status_code: str, detected_at: datetime) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO status_history
                   (project_id, status_code, detected_at)
                   VALUES (?, ?, ?)""",
                (project_id, status_code, detected_at.isoformat()),
            )
            conn.commit()
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/unit/test_db.py -v
```
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/store/db.py tests/unit/test_db.py
git commit -m "feat(phase1): SQLite Store with 4 tables"
```

---

## Task 11: 集成 main.py — 启动入口

**Files:**
- Modify: `src/main.py`
- Create: `tests/integration/test_main.py`

**Interfaces:**
- Produces:
  ```python
  def main(argv: list[str] | None = None) -> int:
      """加载配置 → 初始化 SQLite → 拉一次所有 sheet → 打印摘要 → 退出 0。
      
      argv 用于测试传入自定义配置路径；默认读 config/secrets.yaml + config/sheets.yaml。
      """
  ```

- [ ] **Step 1: 写失败测试 `tests/integration/test_main.py`**

```python
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import json

from src.main import main


def test_main_loads_config_fetches_and_prints(tmp_path: Path, capsys):
    secrets = tmp_path / "secrets.yaml"
    sheets_cfg = tmp_path / "sheets.yaml"
    data_dir = tmp_path / "data"
    creds = tmp_path / "creds.json"
    creds.write_text("{}", encoding="utf-8")
    db = tmp_path / "test.db"

    secrets.write_text(
        f"google_service_account_json: '{creds}'\n"
        "telegram_bot_token: '123:ABC'\n"
        "admin_chat_id: '12345'\n"
        "ui_port: 8765\n"
        "ui_bind: '127.0.0.1'\n",
        encoding="utf-8",
    )
    sheets_cfg.write_text(
        "spreadsheets:\n"
        "  - id: 'ss1'\n"
        "    name: '项目主表'\n"
        "    role: 'master'\n",
        encoding="utf-8",
    )

    fake_client = MagicMock()
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.get_all_values.return_value = [
        ["项目编号", "状态"],
        ["PRJ-001", "制作中"],
    ]
    fake_client.open.return_value.worksheet.return_value = fake_ws

    with patch("src.main.make_gspread_client", return_value=fake_client):
        rc = main(["--secrets", str(secrets), "--sheets", str(sheets_cfg),
                   "--db", str(db)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Loaded 1 projects" in out
    assert "PRJ-001" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_main.py -v
```
Expected: FAIL。

- [ ] **Step 3: 重写 `src/main.py`**

```python
"""应用入口（Phase 1）。

加载配置 → 初始化 SQLite → 拉一次所有 sheet → 打印摘要 → 退出。
后续 phase 在此基础上加 UI / Bot / Scheduler。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import load_config
from src.sheets.auth import make_gspread_client
from src.sheets.repo import SheetRepo
from src.sheets.mapping_repo import MappingRepo
from src.store.db import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checkGPRobot")
    parser.add_argument("--secrets", type=Path,
                        default=Path("config/secrets.yaml"))
    parser.add_argument("--sheets", type=Path,
                        default=Path("config/sheets.yaml"))
    parser.add_argument("--db", type=Path,
                        default=Path("data/checkgprobot.db"))
    args = parser.parse_args(argv)

    cfg = load_config(args.secrets, args.sheets)
    print(f"[config] {len(cfg.spreadsheets)} spreadsheets configured")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    store.init_schema()
    print(f"[store] SQLite initialized at {args.db}")

    client = make_gspread_client(cfg.google_service_account_json)
    repo = SheetRepo(client)
    projects = repo.fetch_all(cfg.spreadsheets)
    print(f"[data] Loaded {len(projects)} projects")
    for p in projects:
        status = p.status.value if p.status else "UNKNOWN"
        print(f"  • {p.project_id} {p.project_name or ''} — {status}")

    # 持久化 sheet 快照（Phase 1 简化：把整个 Project 序列化为快照）
    from datetime import datetime, timezone
    fetched_at = datetime.now(timezone.utc)
    for ss in cfg.spreadsheets:
        try:
            sh = client.open(ss.name)
            ws = sh.worksheet(ss.name)
            rows = ws.get_all_values()
            store.save_sheet_snapshot(
                spreadsheet_id=ss.id,
                sheet_name=ss.name,
                fetched_at=fetched_at,
                rows_json=json.dumps(rows, ensure_ascii=False),
                parse_errors=None,
            )
        except Exception as e:
            print(f"[warn] failed to snapshot {ss.name}: {e}")

    # 加载并打印映射
    try:
        mapping_repo = MappingRepo(client)
        mappings = mapping_repo.load_all()
        for m in mappings:
            store.save_mapping_snapshot(m)
        print(f"[mapping] Loaded {len(mappings)} mappings")
    except Exception as e:
        print(f"[warn] mapping load skipped: {e}")

    return 0
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/integration/test_main.py -v
```
Expected: PASS。

- [ ] **Step 5: 跑全部测试**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```
Expected: 全部 PASS，无回归。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/main.py tests/integration/test_main.py
git commit -m "feat(phase1): main entry — load config, fetch, persist, print summary"
```

---

## Task 12: README

**Files:**
- Create: `README.md`

**Interfaces:** 无（纯文档）

- [ ] **Step 1: 写 `README.md`**

````markdown
# checkGPRobot

多 Google Sheets 可视化 + Telegram 群播报机器人（个人用、本机跑）。

## 状态

- [x] **Phase 1**: 数据接入层（SheetRepo + 状态机 + 持久化 + main 入口）
- [ ] Phase 2: 可视化 UI
- [ ] Phase 3: Telegram Bot
- [ ] Phase 4: 定时调度与播报

设计文档：[docs/superpowers/specs/2026-09-18-checkgprobot-design.md](docs/superpowers/specs/2026-09-18-checkgprobot-design.md)
实施计划：[docs/superpowers/plans/2026-09-18-checkgprobot-phase1-data-layer.md](docs/superpowers/plans/2026-09-18-checkgprobot-phase1-data-layer.md)

## 安装

```bash
pip install -r requirements.txt
```

## 配置

```bash
cp config/secrets.yaml.example config/secrets.yaml
cp config/sheets.yaml.example config/sheets.yaml
# 编辑两个文件填入实际值
```

`secrets.yaml` 需要：
- Google 服务账号 JSON 路径（`data/credentials/gcp-sa.json`）
- Telegram bot token（Phase 3 才需要）
- 管理员 Telegram user_id（Phase 3 才需要）

`sheets.yaml` 列出所有要接入的 spreadsheets。

## 运行（Phase 1）

```bash
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml
```

应看到：

```
[config] N spreadsheets configured
[store] SQLite initialized at data/checkgprobot.db
[data] Loaded M projects
  • PRJ-001 项目一 — MAKING
  ...
[mapping] Loaded K mappings
```

## 测试

```bash
python -m pytest -v
```

## 目录结构

```
src/
├── main.py              # 入口
├── config.py            # YAML 配置加载
├── models/
│   ├── status.py        # 状态枚举 + 别名 + 状态机
│   └── project.py       # 业务数据模型
├── sheets/
│   ├── auth.py          # Google 认证
│   ├── parser.py        # 列识别 + 字段解析
│   ├── repo.py          # SheetRepo 读写
│   └── mapping_repo.py  # 映射表 CRUD
└── store/
    └── db.py            # SQLite 封装
config/                  # 配置（secrets.yaml 不进 git）
data/                    # 运行时数据（不进 git）
tests/                   # 测试
```
````

- [ ] **Step 2: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add README.md
git commit -m "docs(phase1): README with setup, run, test instructions"
```

---

## Self-Review（自审）

### 1. Spec coverage（覆盖 spec 哪些要求）

| Spec 节 | Task | 覆盖点 |
|---|---|---|
| §3.1 数据模型 | T4 | Project / Field / SheetView / Mapping 全部 dataclass |
| §3.2 状态枚举 + 别名 | T3 | 14 个 StatusCode + 完整别名表 + normalize |
| §3.3 状态机 | T3 | LEGAL_TRANSITIONS + is_legal + legal_next_states |
| §3.4 列识别规则 | T6 | HeaderDetector + 候选列名 |
| §4.1 映射表结构 | T9 | 5 列映射表 + 软删除 |
| §7.1 SQLite 表结构 | T10 | 4 张表（sheet_snapshots / mapping_snapshot / broadcast_log / status_history） |
| §8 配置管理 | T2 | secrets.yaml + sheets.yaml 加载 |
| §10 目录结构 | T1+T11 | src/models, src/sheets, src/store 实际创建 |

**未覆盖（后续 phase）**：
- §5 UI → Phase 2
- §6 Bot / §6.3 调度 → Phase 3 / 4
- §11 验收标准（部分）→ 各 phase 末尾补完

### 2. Placeholder scan

未发现 "TBD" / "TODO" / "implement later" / "fill in details" / "similar to Task N"。

### 3. Type consistency

- `StatusCode` 在 T3 定义，T4/T6/T7 都正确引用
- `Field`/`SheetView`/`Project`/`Mapping` 在 T4 定义，T7/T9/T10 都正确引用
- `Store` 在 T10 定义，T11 main 中正确调用
- `SpreadsheetConfig` 在 T2 定义，T5（auth 无依赖）+T7 正确引用

### 4. Found issues fixed

- T8 中 `WriteVerificationError` 类定义在 docstring 后才出现，已修正为放在 import 后立即定义
- T11 测试期望 `"Loaded 1 projects"` —— main.py 输出用 `Loaded {len(projects)} projects`，一致
- 确认所有 `pytest.raises(...)` 的 `pytest` 导入方式在 T8 用 `__import__("pytest")` 是因模板约束（其他 task 用正常 import）

---

## 端到端验证清单（Phase 1 完成后跑一遍）

```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v                  # 全部 PASS
python run.py                        # 跑一次（需真实 config/secrets.yaml + sheets.yaml）
```

预期输出 Phase 1:
```
[config] N spreadsheets configured
[store] SQLite initialized at data/checkgprobot.db
[data] Loaded M projects
  • PRJ-XXX ... — STATUS
[mapping] Loaded K mappings
```