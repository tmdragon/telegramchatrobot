"""共享 fixtures。"""
import pytest

@pytest.fixture
def project_root():
    """项目根路径。"""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent
