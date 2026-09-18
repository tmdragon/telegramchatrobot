import subprocess
from pathlib import Path


def test_auto_refresh_module_exports():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/auto-refresh.js").read_text(encoding="utf-8")
    assert "export function start" in js
    assert "visibilitychange" in js
    assert "localStorage" in js
    assert "cgr.autoRefresh" in js
    assert "setInterval" in js


def test_auto_refresh_no_throw_on_parse():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    script = f"""
import {{ start }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/auto-refresh.js';
console.log(JSON.stringify({{ type: typeof start }}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr