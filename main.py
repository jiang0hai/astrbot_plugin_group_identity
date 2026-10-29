from __future__ import annotations

import datetime as _dt
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def _message_text(content: Any) -> str:
    """Turn a persisted platform message chain into readable text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ""

    parts = content.get("message")
    if not isinstance(parts, list):
        parts = content.get("content")
    if not isinstance(parts, list):
        return ""

    rendered: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = str(part.get("type") or "")
        if kind == "plain":
            rendered.append(str(part.get("text") or ""))
        elif kind == "at":
            name = str(part.get("name") or part.get("user_id") or "")
            rendered.append("@" + name if name else "@某人")
        elif kind == "reply":
            quoted = _clip(part.get("text") or part.get("sender_name") or "", 80)
            rendered.append(f"[回复：{quoted}]" if quoted else "[回复]")
        elif kind in {"image", "record", "video", "file"}:
            rendered.append(f"[{kind}]")
        else:
            text = str(part.get("text") or "")
            if text:
                rendered.append(text)
    return "".join(rendered).strip()


def _record_time(record: Any) -> str:
    value = getattr(record, "created_at", None)
    if isinstance(value, _dt.datetime):
        try:
            return value.astimezone().strftime("%H:%M")
        except Exception:
            return value.strftime("%H:%M")
    text = str(value or "")
    if len(text) >= 16 and text[10] == " ":
        return text[11:16]
    return ""


def _safe_text(value: Any, limit: int = 160) -> str:
    # Keep user content from closing the injected XML-like block.
    text = _clip(value, limit)
    return text.replace("<", "＜").replace(">", "＞")


@register(
    "astrbot_plugin_group_identity",
    "jiang0hai",
    "为群聊 LLM 上下文注入稳定的 QQ 身份标注，避免昵称重复或改名导致认错人。",
    "1.0.0",
    "",
)
class GroupIdentityPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.max_messages = self._int_config("max_messages", 20, 4, 50)
        self.max_chars = self._int_config("max_chars_per_message", 160, 40, 500)
        logger.info(
            "群聊身份标注已加载：enabled=%s max_messages=%s max_chars=%s",
            self.enabled,
            self.max_messages,
            self.max_chars,
        )

    def _int_config(self, key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except Exception:
            value = default
        return max(low, min(high, value))

    async def _recent_history(self, event: AstrMessageEvent) -> list[Any]:
        manager = getattr(self.context, "message_history_manager", None)
        if manager is None:
            return []
        history = await manager.get(
            platform_id=event.get_platform_id(),
            user_id=event.unified_msg_origin,
            page_size=self.max_messages + 8,
        )
        rows = list(history or [])
        # Defensive sort: normally the manager already returns oldest -> newest.
        rows.sort(key=lambda row: (str(getattr(row, "created_at", "")), str(getattr(row, "id", ""))))
        return rows[-self.max_messages :]

    def _build_block(self, event: AstrMessageEvent, rows: list[Any]) -> str:
        current_text = _clip(event.get_message_str(), 300)
        current_id = str(event.get_sender_id() or "")
        current_name = str(event.get_sender_name() or current_id or "未知")

        lines: list[str] = []
        for row in rows:
            sender_id = str(getattr(row, "sender_id", "") or "")
            sender_name = str(getattr(row, "sender_name", "") or sender_id or "未知")
            text = _safe_text(_message_text(getattr(row, "content", None)), self.max_chars)
            if not text:
                continue
            # The current message is already represented by the live event.
            if sender_id == current_id and current_text and text.strip() == current_text.strip():
                continue
            stamp = _record_time(row)
            prefix = f"[{stamp}] " if stamp else ""
            lines.append(f"{prefix}{_safe_text(sender_name, 40)} (QQ:{_safe_text(sender_id, 32)}): {text}")

        if not lines:
            return ""

        return (
            "<group_identity_context>\n"
            "群聊身份规则：昵称可能重复或更改，QQ 号才是稳定身份。"
            "下面是最近的群聊消息，按时间从旧到新。"
            "不要仅凭昵称把不同 QQ 的发言当成同一人，也不要把上一位发言者的话归到当前发言者。"
            "如果无法确定某句话是谁说的，就用中性说法，不要编造“你刚才说过”。\n"
            f"当前发言者：{_safe_text(current_name, 40)} (QQ:{_safe_text(current_id, 32)})\n"
            "最近群聊：\n"
            + "\n".join(lines)
            + "\n</group_identity_context>"
        )

    @filter.on_llm_request(priority=-100000)
    async def inject_group_identity(self, event: AstrMessageEvent, req: ProviderRequest, *args, **kwargs):
        if not self.enabled:
            return
        if not event.get_group_id():
            return
        if event.get_extra("_group_identity_injected"):
            return

        try:
            rows = await self._recent_history(event)
            block = self._build_block(event, rows)
        except Exception as exc:
            logger.warning("群聊身份标注读取失败: %s", exc)
            return

        if not block:
            return

        try:
            req.extra_user_content_parts.append(TextPart(text=block))
            event.set_extra("_group_identity_injected", True)
            logger.debug("群聊身份标注已注入：umo=%s rows=%s", event.unified_msg_origin, len(rows))
        except Exception as exc:
            logger.warning("群聊身份标注注入失败: %s", exc)

    async def terminate(self) -> None:
        logger.info("群聊身份标注已停止")
