# -*- coding: utf-8 -*-
"""
对话路由服务。

在 OpenClaw 接入开启后，负责判定当前用户输入应该：
1. 走 OpenClaw 执行任务；或
2. 直接走普通 LLM 闲聊/问答。

判定策略：
- 硬规则优先：明确指定 OpenClaw / 明确拒绝 OpenClaw
- 然后使用 LLM 做一次轻量意图分类
- 如果分类失败，再使用任务型语句启发式兜底
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional


OPENCLAW_ROUTE = "openclaw"
LLM_ROUTE = "llm"

_ALIAS_PATTERN = r"(?:open\s*claw|openclaw|小龙虾|龙虾|机器人)"

_EXPLICIT_OPENCLAW_PATTERNS = [
    re.compile(
        rf"(?:用|走|调用|交给|让|请|麻烦|通过|转给|切到|切换到|使用)(?:.{0,4})?(?P<alias>{_ALIAS_PATTERN})(?:.{0,8})?(?:来|处理|执行|帮我|帮下|一下|完成|搞定)?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<alias>{_ALIAS_PATTERN})(?:.{0,8})?(?:来|处理|执行|帮我|帮下|接管|一下|安排|搞定)",
        re.IGNORECASE,
    ),
]

_EXPLICIT_NO_OPENCLAW_PATTERNS = [
    re.compile(
        rf"(?:不要|别|不用|不必|无需|不需要|别再|先别|不用再)(?:.{0,4})?(?:用|走|调用|交给|让|通过)?(?:.{0,4})?(?P<alias>{_ALIAS_PATTERN})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<alias>{_ALIAS_PATTERN})(?:.{0,6})?(?:不要|别|不用|不必|免了|算了)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:直接|仅|只)(?:用|走)?(?:LLM|大模型|聊天|回答)",
        re.IGNORECASE,
    ),
]

_TASK_HINT_PATTERNS = [
    re.compile(
        r"(?:帮我|请帮我|请你|麻烦你|麻烦帮我|能不能帮我|可以帮我|替我|给我)(?:.{0,12})?"
        r"(?:打开|关闭|启动|停止|运行|执行|处理|安排|提醒|记录|创建|新建|添加|删除|修改|编辑|重命名|整理|搜索|查|查询|检索|抓取|下载|上传|发送|同步|触发|调用|总结文件|生成文件)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:提醒我|帮我记一下|记一下|记个|加个待办|建个待办|创建待办|创建提醒|设个闹钟|定个闹钟|定个提醒|安排一下)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:打开|关闭|启动|停止|运行|执行|创建|新建|添加|删除|修改|编辑|查询|搜索|下载|上传|发送|同步|部署|安装|预约|预订|下单|订票|订餐)",
        re.IGNORECASE,
    ),
]


@dataclass
class IntentRoutingDecision:
    route: str
    intent_type: str
    reason: str
    confidence: float = 0.0
    matched_alias: Optional[str] = None


class IntentRouter:
    """基于规则 + LLM 的 OpenClaw 路由器。"""

    async def decide(self, user_text: str, history: Optional[list] = None) -> IntentRoutingDecision:
        text = (user_text or "").strip()
        if not text:
            return IntentRoutingDecision(
                route=LLM_ROUTE,
                intent_type="chat",
                reason="empty",
                confidence=1.0,
            )

        alias = self._match_explicit_no_openclaw(text)
        if alias:
            return IntentRoutingDecision(
                route=LLM_ROUTE,
                intent_type="explicit_no_openclaw",
                reason="explicit opt-out",
                confidence=1.0,
                matched_alias=alias,
            )

        alias = self._match_explicit_openclaw(text)
        if alias:
            return IntentRoutingDecision(
                route=OPENCLAW_ROUTE,
                intent_type="explicit_openclaw",
                reason="explicit openclaw",
                confidence=1.0,
                matched_alias=alias,
            )

        llm_decision = await self._classify_with_llm(text, history or [])
        if llm_decision is not None:
            return llm_decision

        if self._looks_like_task(text):
            return IntentRoutingDecision(
                route=OPENCLAW_ROUTE,
                intent_type="task",
                reason="task heuristic fallback",
                confidence=0.55,
            )

        return IntentRoutingDecision(
            route=LLM_ROUTE,
            intent_type="chat",
            reason="default llm fallback",
            confidence=0.5,
        )

    def _match_explicit_openclaw(self, text: str) -> Optional[str]:
        for pattern in _EXPLICIT_OPENCLAW_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group("alias")
        return None

    def _match_explicit_no_openclaw(self, text: str) -> Optional[str]:
        for pattern in _EXPLICIT_NO_OPENCLAW_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.groupdict().get("alias") or "llm"
        return None

    def _looks_like_task(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in _TASK_HINT_PATTERNS)

    async def _classify_with_llm(
        self,
        user_text: str,
        history: list,
    ) -> Optional[IntentRoutingDecision]:
        from backend.services.llm_service import llm_service

        system_prompt = (
            "你是一个对话路由器，只负责决定当前消息应该走哪条链路。"
            "候选链路只有两种：\n"
            "1. openclaw：当用户明确要求使用 OpenClaw/小龙虾/龙虾/机器人，"
            "或者虽然没点名，但本轮消息本质上是在要求系统替他执行任务、调用外部能力、"
            "查询实时信息、操作软件/文件/设备、创建提醒/待办/日程、发送消息、触发自动化。\n"
            "2. llm：闲聊、情感互动、解释概念、纯知识问答、润色改写、泛泛建议、角色扮演，"
            "以及用户明确说不要使用 OpenClaw。\n"
            "\n"
            "请严格输出 JSON，不要输出任何额外文字："
            '{"route":"openclaw|llm","intent_type":"explicit_openclaw|task|chat|explicit_no_openclaw","confidence":0.0,"reason":"不超过20字"}'
            "\n"
            "如果只是普通聊天、问候、闲聊、情绪表达、主观讨论，必须选 llm。"
            "如果用户需要一个真正去执行或查询的结果，选 openclaw。"
        )

        recent_history = self._build_recent_history(history)
        user_prompt = (
            "最近上下文：\n"
            f"{recent_history}\n\n"
            "当前用户消息：\n"
            f"{user_text}"
        )

        try:
            result = await llm_service.chat_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                max_tokens=180,
                temperature=0.0,
            )
        except Exception as exc:
            print(f"[IntentRouter] LLM 分类失败: {exc}")
            return None

        content = self._extract_response_text(result)
        if not content:
            return None

        payload = self._parse_json_payload(content)
        if not payload:
            print(f"[IntentRouter] 无法解析分类结果: {content}")
            return None

        route = str(payload.get("route", "")).strip().lower()
        if route not in {OPENCLAW_ROUTE, LLM_ROUTE}:
            return None

        intent_type = str(payload.get("intent_type", "chat")).strip().lower() or "chat"
        if intent_type not in {"explicit_openclaw", "task", "chat", "explicit_no_openclaw"}:
            intent_type = "chat" if route == LLM_ROUTE else "task"

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        reason = str(payload.get("reason", "")).strip() or "llm intent router"
        return IntentRoutingDecision(
            route=route,
            intent_type=intent_type,
            reason=reason[:40],
            confidence=max(0.0, min(confidence, 1.0)),
        )

    def _build_recent_history(self, history: list, limit: int = 6) -> str:
        if not history:
            return "（无）"

        chunks = []
        for item in history[-limit:]:
            role = str(item.get("role", "user"))
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            chunks.append(f"{role}: {content[:200]}")

        return "\n".join(chunks) if chunks else "（无）"

    def _extract_response_text(self, result: object) -> str:
        if not isinstance(result, dict):
            return ""

        try:
            return str(result["choices"][0]["message"]["content"]).strip()
        except Exception:
            return ""

    def _parse_json_payload(self, text: str) -> Optional[dict]:
        text = text.strip()
        if not text:
            return None

        candidates = [text]
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1))

        brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace_match:
            candidates.append(brace_match.group(1))

        for candidate in candidates:
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                continue

        return None


intent_router = IntentRouter()


__all__ = [
    "IntentRoutingDecision",
    "IntentRouter",
    "OPENCLAW_ROUTE",
    "LLM_ROUTE",
    "intent_router",
]
