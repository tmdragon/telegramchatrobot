import json
import re
import subprocess
from pathlib import Path

import pytest


def _run_node(script: str) -> dict:
    """执行 Node.js 脚本（ES module），stdin 输入 JSON，stdout 期望 JSON 结果。"""
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({}),
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node failed: {result.stderr}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def static_dir():
    return Path("D:/soft/checkGPRobot/.spyproject/src/web/static")


def test_format_dwell_days_hours(static_dir):
    js = (static_dir / "js/time.js").read_text(encoding="utf-8")
    script = f"""
import {{ formatDwell }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/time.js';
console.log(JSON.stringify({{
  d_h: formatDwell(183600),
  m: formatDwell(15 * 60),
  s: formatDwell(45),
  z: formatDwell(0),
  n: formatDwell(null),
  neg: formatDwell(-10),
}}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["d_h"] == "2 天 3 小时"
    assert out["m"] == "15 分钟"
    assert out["s"] == "45 秒"
    assert out["z"] == "0 秒"
    assert out["n"] == "—"
    assert out["neg"] == "—"


def test_escape_html(static_dir):
    js = (static_dir / "js/dom.js").read_text(encoding="utf-8")
    script = f"""
import {{ escapeHtml }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/dom.js';
console.log(JSON.stringify(escapeHtml('<script>alert(1)</script>')));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_api_error_shape(static_dir):
    """api.js 必须 export ApiError 类。"""
    js = (static_dir / "js/api.js").read_text(encoding="utf-8")
    assert "class ApiError" in js
    assert "status" in js and "message" in js and "detail" in js


# --- 模块内私有 helper 调用完整性 ---------------------------------------
#
# 回归测试：groups.js 的 _openEditModal() 调用了 _openModal()，但该函数的
# function 定义在某个重构 commit 里被删掉了 —— 页面点击「编辑」抛
# ReferenceError，又被委托处的 try/catch 吞掉，表现为「按钮点了没反应」。
# ES module 里没有全局兜底，所以静态扫描即可提前发现这类漏网之鱼。

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_DEFINITION_RES = (
    re.compile(r"^\s*(?:async\s+)?function\s+_(\w+)", re.M),
    re.compile(r"^\s*(?:const|let|var)\s+_(\w+)\s*=", re.M),
)


def _strip_comments(js: str) -> str:
    return _COMMENT_RE.sub("", js)


@pytest.mark.parametrize(
    "filename",
    [
        "groups.js",
        "mappings-crud.js",
        "broadcast-all.js",
        "edit-projects.js",
        "new-project.js",
        "confirm-dialog.js",
        "inline-edit.js",
        "online.js",
        "settings.js",
    ],
)
def test_private_helpers_are_defined(static_dir, filename):
    """模块内调用的 `_helper(...)` 必须在本模块有定义或被 import。"""
    js = (static_dir / "js" / filename).read_text(encoding="utf-8")
    code = _strip_comments(js)

    defined = set()
    for rx in _DEFINITION_RES:
        defined.update(rx.findall(code))
    for m in re.finditer(r"import\s*\{([^}]*)\}", code):
        defined.update(n.strip().split(" as ")[-1].strip() for n in m.group(1).split(","))

    called = set(re.findall(r"(?<![\w.$])_(\w+)\s*\(", code))
    missing = sorted(n for n in called if n not in defined)
    assert not missing, f"{filename} 调用了未定义的 helper: {['_' + n for n in missing]}"