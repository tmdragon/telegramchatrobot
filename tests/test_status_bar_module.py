import json
import subprocess
from pathlib import Path


def test_status_bar_module_exports():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/status-bar.js").read_text(encoding="utf-8")
    assert "export function mount" in js
    assert "EventTarget" in js
    assert "refresh:start" in js
    assert "refresh:done" in js
    assert "refresh:error" in js
    assert "errors.bump" in js or "errors" in js and "bump" in js


def test_status_bar_module_no_throw_on_parse():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    # 简单语法检查
    script = f"""
import {{ mount }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/status-bar.js';
console.log(JSON.stringify({{ type: typeof mount }}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["type"] == "function"