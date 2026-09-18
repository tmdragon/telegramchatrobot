import subprocess
from pathlib import Path


def test_inline_edit_module_delegates_on_sheet_section():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/inline-edit.js").read_text(encoding="utf-8")
    # 委托目标必须是 .sheet-section（稳定祖先），不是 tbody
    assert ".sheet-section" in js
    assert ".sheet-table tbody" not in js, "must NOT delegate on tbody (gets replaced by auto-refresh)"
    assert "export function init" in js


def test_inline_edit_no_throw_on_parse():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    script = f"""
import {{ init }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/inline-edit.js';
console.log(JSON.stringify({{ type: typeof init }}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr