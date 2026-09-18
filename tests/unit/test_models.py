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