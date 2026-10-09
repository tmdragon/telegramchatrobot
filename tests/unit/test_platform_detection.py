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