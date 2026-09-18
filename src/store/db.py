"""SQLite 持久化。完整 schema 见 spec §7.1。

Phase 1 实现 4 张表的核心 CRUD。
时间戳：统一 ISO8601 with timezone，存储为 TEXT。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.project import Mapping


SCHEMA = """
CREATE TABLE IF NOT EXISTS sheet_snapshots (
  spreadsheet_id  TEXT,
  sheet_name      TEXT,
  fetched_at      TEXT,
  rows_json       TEXT,
  parse_errors    TEXT,
  PRIMARY KEY (spreadsheet_id, sheet_name)
);

CREATE TABLE IF NOT EXISTS mapping_snapshot (
  project_id              TEXT PRIMARY KEY,
  chat_id                 TEXT,
  note                    TEXT,
  enabled                 INTEGER,
  last_broadcast_at       TEXT,
  last_broadcast_status   TEXT,
  last_error              TEXT
);

CREATE TABLE IF NOT EXISTS broadcast_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id      TEXT,
  chat_id         TEXT,
  status_code     TEXT,
  message_text    TEXT,
  sent_at         TEXT,
  success         INTEGER,
  error           TEXT
);

CREATE TABLE IF NOT EXISTS status_history (
  project_id      TEXT,
  status_code     TEXT,
  detected_at     TEXT,
  PRIMARY KEY (project_id, status_code, detected_at)
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def save_sheet_snapshot(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        fetched_at: datetime,
        rows_json: str,
        parse_errors: Optional[str],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sheet_snapshots
                   (spreadsheet_id, sheet_name, fetched_at, rows_json, parse_errors)
                   VALUES (?, ?, ?, ?, ?)""",
                (spreadsheet_id, sheet_name, fetched_at.isoformat(), rows_json, parse_errors),
            )
            conn.commit()

    def load_latest_snapshot(
        self, spreadsheet_id: str, sheet_name: str
    ) -> Optional[tuple[datetime, str, Optional[str]]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT fetched_at, rows_json, parse_errors
                   FROM sheet_snapshots
                   WHERE spreadsheet_id = ? AND sheet_name = ?""",
                (spreadsheet_id, sheet_name),
            ).fetchone()
        if row is None:
            return None
        return (
            datetime.fromisoformat(row["fetched_at"]),
            row["rows_json"],
            row["parse_errors"],
        )

    def save_mapping_snapshot(self, mapping: Mapping) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO mapping_snapshot
                   (project_id, chat_id, note, enabled,
                    last_broadcast_at, last_broadcast_status, last_error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    mapping.project_id,
                    mapping.chat_id,
                    mapping.note,
                    1 if mapping.enabled else 0,
                    mapping.last_broadcast_at.isoformat() if mapping.last_broadcast_at else None,
                    mapping.last_broadcast_status,
                    mapping.last_error,
                ),
            )
            conn.commit()

    def load_mapping_snapshots(self) -> list[Mapping]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT project_id, chat_id, note, enabled,
                          last_broadcast_at, last_broadcast_status, last_error
                   FROM mapping_snapshot"""
            ).fetchall()
        result = []
        for row in rows:
            lba = row["last_broadcast_at"]
            result.append(Mapping(
                project_id=row["project_id"],
                chat_id=row["chat_id"] or "",
                note=row["note"] or "",
                enabled=bool(row["enabled"]),
                last_broadcast_at=datetime.fromisoformat(lba) if lba else None,
                last_broadcast_status=row["last_broadcast_status"],
                last_error=row["last_error"],
            ))
        return result

    def log_broadcast(
        self,
        project_id: str,
        chat_id: str,
        status_code: str,
        message_text: str,
        sent_at: datetime,
        success: bool,
        error: Optional[str],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO broadcast_log
                   (project_id, chat_id, status_code, message_text, sent_at, success, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, chat_id, status_code, message_text, sent_at.isoformat(),
                 1 if success else 0, error),
            )
            conn.commit()

    def latest_successful_broadcast(
        self, project_id: str, chat_id: str
    ) -> Optional[tuple[str, str]]:
        """返回 (status_code, message_text)。Phase 4 用于 skip_if_no_change 判定。"""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT status_code, message_text
                   FROM broadcast_log
                   WHERE project_id = ? AND chat_id = ? AND success = 1
                   ORDER BY sent_at DESC LIMIT 1""",
                (project_id, chat_id),
            ).fetchone()
        if row is None:
            return None
        return (row["status_code"], row["message_text"])

    def record_status(self, project_id: str, status_code: str, detected_at: datetime) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO status_history
                   (project_id, status_code, detected_at)
                   VALUES (?, ?, ?)""",
                (project_id, status_code, detected_at.isoformat()),
            )
            conn.commit()