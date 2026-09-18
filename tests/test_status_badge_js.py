import json
import subprocess
from pathlib import Path


def test_status_badge_module():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    script = f"""
import {{ renderBadge, STATUS_META }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/status-badge.js';
const out = {{
  known: renderBadge('MAKING', null),
  unknown: renderBadge(null, '随便写的状态'),
  meta_count: Object.keys(STATUS_META).length,
  making_display: STATUS_META.MAKING.displayName,
}};
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["meta_count"] == 14
    assert out["making_display"] == "我方制作中"
    assert "我方制作中" in out["known"]
    assert "status-badge--making" in out["known"]
    assert "随便写的状态" in out["unknown"]
    assert "status-badge--unknown" in out["unknown"]


def test_page_bootstrap_module_loads():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/page-bootstrap.js").read_text(encoding="utf-8")
    assert "data-page" in js
    assert "status-bar" in js  # base always loads