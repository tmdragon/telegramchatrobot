import json
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