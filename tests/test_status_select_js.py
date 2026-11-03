"""status-select.js 单测(node 跑 ES module)。

覆盖 /projects 之外的状态列内联编辑下拉框：
- 一个状态只渲染一个选项(不再把每个别名都列出来)
- 当前 cell 原文属于某状态时,该项被选中且**保留原文**(点 OK 不会改写 sheet)
- 识别不出来的原文保留成"(当前未识别)"选项,不丢值
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node 才能跑 JS 测试")

STATIC_DIR = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")

# /api/statuses 的真实结构(裁剪版)
STATUSES = [
    {
        "code": "ORDERED",
        "display": "对方下单",
        "aliases": ["下单", "已下单", "待开始", "已下单待制作"],
    },
    {
        "code": "PUBLISHED",
        "display": "已发布",
        "aliases": ["已发布", "上线了", "上架", "已上架"],
    },
    {
        "code": "OFF_SHELF",
        "display": "已下架",
        "aliases": ["已下架", "下架", "下架了", "已下线"],
    },
]

# 最小 DOM stub：只实现 status-select.js 用到的那几个方法
_DOM_STUB = """
class FakeEl {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.selected = false;
    this.className = "";
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(c, ref) {
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? 0 : i, 0, c);
    return c;
  }
}
globalThis.document = { createElement: (t) => new FakeEl(t) };
globalThis.fetch = async () => ({ ok: true, json: async () => ({ statuses: STATUSES }) });
"""


def _run_js(body: str) -> dict:
    """在 node 里跑一段脚本，返回它打印的 JSON。"""
    script = f"""
import {{ matchStatus, buildStatusSelect, loadStatusOptions }} from 'file:///{STATIC_DIR.as_posix()}/js/status-select.js';
const STATUSES = {json.dumps(STATUSES, ensure_ascii=False)};
{_DOM_STUB}
{body}
"""
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_match_status_recognizes_display_alias_and_code():
    out = _run_js("""
console.log(JSON.stringify({
  byDisplay: matchStatus("已发布", STATUSES),
  byAlias: matchStatus("上架", STATUSES),
  byCode: matchStatus("PUBLISHED", STATUSES),
  unknown: matchStatus("瞎写的", STATUSES),
  empty: matchStatus("", STATUSES),
}));
""")
    assert out["byDisplay"]["code"] == "PUBLISHED"
    assert out["byAlias"]["code"] == "PUBLISHED"
    assert out["byAlias"]["raw"] == "上架"
    assert out["byCode"]["code"] == "PUBLISHED"
    assert out["unknown"] is None
    assert out["empty"] is None


def test_build_status_select_renders_one_option_per_status():
    """每个状态只出一个选项，别名不再撑爆下拉框"""
    out = _run_js("""
await loadStatusOptions();
const sel = buildStatusSelect("上架");
console.log(JSON.stringify({
  count: sel.children.length,
  texts: sel.children.map(o => o.textContent),
}));
""")
    assert out["count"] == len(STATUSES)
    assert out["texts"] == ["对方下单", "已发布", "已下架"]
    # 别名不该再作为独立选项出现
    assert "上架" not in out["texts"]
    assert "下线" not in out["texts"]


def test_build_status_select_marks_current_and_keeps_raw_value():
    """当前状态被选中，且选项值保留 sheet 原文（点 OK 不会改写）"""
    out = _run_js("""
await loadStatusOptions();
const sel = buildStatusSelect("上架");
console.log(JSON.stringify({
  selectedIndex: sel.children.findIndex(o => o.selected),
  currentValue: sel.children[1].value,
  otherValue: sel.children[0].value,
}));
""")
    assert out["selectedIndex"] == 1
    assert out["currentValue"] == "上架"
    assert out["otherValue"] == "对方下单"


def test_build_status_select_keeps_unrecognized_value():
    """识别不出来的原文要保留，不能被静默丢掉"""
    out = _run_js("""
await loadStatusOptions();
const sel = buildStatusSelect("瞎写的");
console.log(JSON.stringify({
  count: sel.children.length,
  firstText: sel.children[0].textContent,
  firstValue: sel.children[0].value,
  firstSelected: sel.children[0].selected,
}));
""")
    assert out["count"] == len(STATUSES) + 1
    assert "当前未识别" in out["firstText"]
    assert out["firstValue"] == "瞎写的"
    assert out["firstSelected"] is True
