#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图路由测试。"""
import os
import sys
import unittest
from unittest.mock import AsyncMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.services.intent_router import IntentRouter, OPENCLAW_ROUTE, LLM_ROUTE


class IntentRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = IntentRouter()

    async def test_explicit_openclaw_alias_routes_to_openclaw(self):
        decision = await self.router.decide("请用小龙虾帮我查一下今天的待办")
        self.assertEqual(decision.route, OPENCLAW_ROUTE)
        self.assertEqual(decision.intent_type, "explicit_openclaw")

    async def test_explicit_openclaw_opt_out_routes_to_llm(self):
        decision = await self.router.decide("这个问题不要用openclaw，直接回答我就行")
        self.assertEqual(decision.route, LLM_ROUTE)
        self.assertEqual(decision.intent_type, "explicit_no_openclaw")

    async def test_task_fallback_routes_to_openclaw_when_classifier_unavailable(self):
        self.router._classify_with_llm = AsyncMock(return_value=None)
        decision = await self.router.decide("帮我创建一个明天上午九点的提醒")
        self.assertEqual(decision.route, OPENCLAW_ROUTE)
        self.assertEqual(decision.intent_type, "task")

    async def test_chat_fallback_routes_to_llm_when_classifier_unavailable(self):
        self.router._classify_with_llm = AsyncMock(return_value=None)
        decision = await self.router.decide("你今天心情怎么样")
        self.assertEqual(decision.route, LLM_ROUTE)
        self.assertEqual(decision.intent_type, "chat")


if __name__ == "__main__":
    unittest.main()
