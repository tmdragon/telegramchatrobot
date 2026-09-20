"""BroadcastSvc：全员播报服务。

对每条 enabled 映射：
1. cache.get(project_id) 拿 Project
2. 计算 dwell_seconds、判定是否超阈值
3. skip_if_no_change 且与上次成功播报完全相同 → skip
4. 渲染 Markdown → BotService.send_message
5. 失败 1s/2s/4s 指数退避；最终失败 → mapping.last_error = "❌ 无法发送"
6. 成功 → store.log_broadcast + store.record_status + store.save_mapping_snapshot

dryrun=True 时只渲染首条 enabled 映射的 preview，不发、不写 log。

管理员告警：失败 > 0 时调 notify_admin（懒加载，避免循环 import）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from src.bot.service import BotService
from src.bot.templates import render_broadcast, render_dryrun_preview
from src.models.project import Mapping, Project
from src.sheets.mapping_repo import MappingRepo
from src.store.db import Store
from src.web.cache import ProjectCache


class BroadcastSvc:
    def __init__(
        self,
        bot_service: BotService,
        mapping_repo: MappingRepo,
        store: Store,
        cache: ProjectCache,
        admin_chat_id: int,
        *,
        per_status_thresholds: Optional[dict[str, int]] = None,
        admin_broadcast_chats: Optional[list[str]] = None,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
    ) -> None:
        self.bot_service = bot_service
        self.mapping_repo = mapping_repo
        self.store = store
        self.cache = cache
        self.admin_chat_id = admin_chat_id
        # 默认 14 天阈值；显式传入则覆盖
        self.per_status_thresholds: dict[str, int] = {
            "MAKING": 14, "CLIENT_REVIEW": 7, "UNPAID": 30,
            **(per_status_thresholds or {}),
        }
        # 内部管理群（与 admin_chat_id 私聊告警不同；这些群收所有项目的播报）
        self.admin_broadcast_chats: list[str] = list(admin_broadcast_chats or [])
        self.retry_delays = retry_delays

    def _exceeded_threshold(self, project) -> bool:
        if project.status is None or project.status_changed_at is None:
            return False
        dwell_days = (datetime.now(timezone.utc) - project.status_changed_at).days
        threshold = self.per_status_thresholds.get(project.status.value, 14)
        return dwell_days > threshold

    async def _send_with_retry(self, chat_id: str | int, text: str) -> bool:
        """返回 True = 成功，False = 全部重试失败。失败时把最后一个异常存在 self._last_send_error。"""
        last_error: Optional[BaseException] = None
        # 首发 + len(retry_delays) 次重试
        for attempt in range(len(self.retry_delays) + 1):
            try:
                await self.bot_service.send_message(chat_id, text)
                return True
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < len(self.retry_delays):
                    await asyncio.sleep(self.retry_delays[attempt])
        self._last_send_error = last_error
        return False

    async def broadcast_project(self, project: Project) -> dict:
        """单项目播报（事件驱动）。

        与 broadcast_all 的区别：
        - 不读 cache（直接用传入的 project 对象）
        - 不受 skip_if_no_change 影响（已确认变化才调进来）
        - 失败时也 notify_admin

        Returns:
            {sent, skipped, failed}
        """
        self._last_send_error = None

        try:
            mappings: list[Mapping] = await asyncio.to_thread(self.mapping_repo.load_all)
        except Exception:  # noqa: BLE001
            mappings = []

        enabled_mappings = {m.project_id: m for m in mappings if m.enabled}
        proj_mapping = enabled_mappings.get(project.project_id)

        targets: list[tuple[str, Optional[Mapping]]] = []
        if proj_mapping is not None:
            targets.append((proj_mapping.chat_id, proj_mapping))
        for ac in self.admin_broadcast_chats:
            if not any(chat_id == ac for chat_id, _ in targets):
                targets.append((ac, None))

        if not targets:
            return {"sent": 0, "skipped": 0, "failed": 0}

        sent = 0
        failed = 0
        now = datetime.now(timezone.utc)
        exceeded = self._exceeded_threshold(project)

        for chat_id, target_mapping in targets:
            if target_mapping is None:
                target_mapping = proj_mapping or Mapping(
                    project_id=project.project_id,
                    chat_id=chat_id,
                )
            text = render_broadcast(project, target_mapping, now, exceeded)
            ok = await self._send_with_retry(chat_id, text)
            sent_at = datetime.now(timezone.utc)
            if ok:
                sent += 1
                self.store.log_broadcast(
                    project_id=project.project_id,
                    chat_id=chat_id,
                    status_code=project.status.value if project.status else "UNKNOWN",
                    message_text=text,
                    sent_at=sent_at,
                    success=True,
                    error=None,
                )
                if project.status and project.status_changed_at:
                    self.store.record_status(
                        project.project_id, project.status.value, project.status_changed_at
                    )
            else:
                failed += 1
                if proj_mapping is not None and chat_id == proj_mapping.chat_id:
                    proj_mapping.last_error = f"❌ 无法发送: {self._last_send_error}"
                    await asyncio.to_thread(self.store.save_mapping_snapshot, proj_mapping)

        if failed > 0:
            from src.bot.notifications import notify_admin
            await notify_admin(
                self.bot_service, self.admin_chat_id,
                f"⚠ 状态变化播报失败: project={project.project_id} failed={failed}",
            )

        return {"sent": sent, "skipped": 0, "failed": failed}

    async def broadcast_internal_only(self, project: Project) -> dict:
        """只发到内部管理群（admin_broadcast_chats），不发给项目映射群。

        用途：滞留阈值播报等只提醒管理员/内部群、不打扰客户群的场景。
        """
        return await self.broadcast_internal_only_with_text(
            self._render_internal_text(project)
        )

    async def broadcast_internal_only_with_text(self, text: str) -> dict:
        """发任意文本到所有 admin_broadcast_chats（不重渲染模板）。"""
        sent = 0
        failed = 0
        for ac in self.admin_broadcast_chats:
            try:
                ok = await self._send_with_retry(ac, text)
                if ok:
                    sent += 1
                else:
                    failed += 1
            except Exception:  # noqa: BLE001
                failed += 1
        return {"sent": sent, "failed": failed, "skipped": 0}

    def _render_internal_text(self, project: Project) -> str:
        """渲染"滞留提醒"专用文案：包含项目 ID / 状态 / 停留时长。"""
        from src.web.filters import humanize_duration
        from src.bot.templates import status_display_text
        now = datetime.now(timezone.utc)
        dwell_seconds = 0
        if project.status_changed_at:
            dwell_seconds = max(0, int((now - project.status_changed_at).total_seconds()))
        status_text = status_display_text(project) or "未知"
        name = project.project_name or "（未命名）"
        return (
            f"⏰ *滞留提醒* — {project.project_id} {name}\n"
            f"▸ 状态：`{status_text}`\n"
            f"▸ 停留时长：`{humanize_duration(dwell_seconds)}`（超时未变）"
        )

    async def broadcast_all(
        self,
        skip_if_no_change: bool = True,
        dryrun: bool = False,
    ) -> dict:
        """全员播报。

        Returns:
            {sent, skipped, failed, dryrun, preview?}
        """
        self._last_send_error = None

        # mapping_repo.load_all 同步 gspread → to_thread
        try:
            mappings: list[Mapping] = await asyncio.to_thread(self.mapping_repo.load_all)
        except Exception:  # noqa: BLE001
            mappings = []  # 整段失败视为无可播报

        # project_id → enabled mapping 索引
        enabled_mappings = {m.project_id: m for m in mappings if m.enabled}

        sent = 0
        skipped = 0
        failed = 0
        first_preview: Optional[str] = None

        for project in self.cache.list_projects():
            if project.status is None or project.status_changed_at is None:
                continue  # 没状态的项目跳过

            now = datetime.now(timezone.utc)
            exceeded = self._exceeded_threshold(project)

            # 构建该项目的播报目标：(chat_id, 可选 source Mapping)
            proj_mapping = enabled_mappings.get(project.project_id)
            targets: list[tuple[str, Optional[Mapping]]] = []
            if proj_mapping is not None:
                targets.append((proj_mapping.chat_id, proj_mapping))
            for ac in self.admin_broadcast_chats:
                # 去重：如果 admin chat 恰好等于项目自己的 chat，不再重复发送
                if not any(chat_id == ac for chat_id, _ in targets):
                    targets.append((ac, None))

            for chat_id, target_mapping in targets:
                # skip_if_no_change 判定：(project_id, chat_id) 对独立计数
                if skip_if_no_change:
                    last = self.store.latest_successful_broadcast(project.project_id, chat_id)
                    if last is not None:
                        last_code, last_changed_at, _last_text = last
                        curr_changed_at = project.status_changed_at.isoformat()
                        if last_changed_at == curr_changed_at and last_code == project.status.value:
                            skipped += 1
                            continue

                # admin chat 没有自己的 mapping，用项目自身 mapping 或 stub
                if target_mapping is None:
                    target_mapping = proj_mapping or Mapping(
                        project_id=project.project_id,
                        chat_id=chat_id,
                    )

                text = render_broadcast(project, target_mapping, now, exceeded)

                if dryrun:
                    if first_preview is None:
                        first_preview = render_dryrun_preview(project, target_mapping, now)
                    continue

                ok = await self._send_with_retry(chat_id, text)
                sent_at = datetime.now(timezone.utc)
                if ok:
                    sent += 1
                    self.store.log_broadcast(
                        project_id=project.project_id,
                        chat_id=chat_id,
                        status_code=project.status.value,
                        message_text=text,
                        sent_at=sent_at,
                        success=True,
                        error=None,
                    )
                    self.store.record_status(
                        project.project_id,
                        project.status.value,
                        project.status_changed_at,
                    )
                else:
                    failed += 1
                    # 仅在项目自己的 mapping 上写 last_error（admin chat 无对应 mapping）
                    if proj_mapping is not None and chat_id == proj_mapping.chat_id:
                        proj_mapping.last_error = f"❌ 无法发送: {self._last_send_error}"
                        await asyncio.to_thread(self.store.save_mapping_snapshot, proj_mapping)

        # 失败汇总 → 管理员告警
        if failed > 0 and not dryrun:
            from src.bot.notifications import notify_admin

            await notify_admin(
                self.bot_service, self.admin_chat_id,
                f"⚠ 播报部分失败: sent={sent} skipped={skipped} failed={failed}",
            )

        result = {
            "sent": sent, "skipped": skipped, "failed": failed,
            "dryrun": dryrun,
        }
        if first_preview is not None:
            result["preview"] = first_preview
        return result
