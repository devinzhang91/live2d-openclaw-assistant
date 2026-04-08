import asyncio
import contextlib
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.realtime_volc import (
    DEFAULT_REALTIME_VOICE,
    EVENT_CONNECTION_STARTED,
    EVENT_TASK_REQUEST,
    EVENT_SESSION_STARTED,
    SUPPORTED_REALTIME_VOICES,
    VolcRealtimeService,
    VolcRealtimeSession,
    _build_audio_message,
    _parse_message,
)


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


class VolcRealtimeSessionProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_realtime_service_falls_back_for_invalid_speaker(self):
        service = VolcRealtimeService(voice="zh_female_vv_jupiter_bigtt")
        self.assertEqual(service.voice, DEFAULT_REALTIME_VOICE)

    def test_realtime_service_keeps_supported_speaker(self):
        known_voice = next(iter(SUPPORTED_REALTIME_VOICES))
        service = VolcRealtimeService(voice=known_voice)
        self.assertEqual(service.voice, known_voice)

    def test_audio_message_matches_demo_protocol_layout(self):
        audio_chunk = b"\x01\x02\x03\x04" * 32
        session_id = "test-session"

        frame = _build_audio_message(audio_chunk, session_id)

        self.assertEqual(frame[0], 0x11)  # version=1, header_size=1
        self.assertEqual(frame[1], 0x24)  # audio-only request + MSG_WITH_EVENT
        self.assertEqual(frame[2], 0x01)  # no serialization + gzip

        parsed = _parse_message(frame)
        self.assertEqual(parsed["event"], EVENT_TASK_REQUEST)
        self.assertEqual(parsed["session_id"], session_id)
        self.assertEqual(parsed["payload"], audio_chunk)

    async def test_start_session_places_input_mod_in_dialog_extra(self):
        fake_ws = _FakeWebSocket()

        session = VolcRealtimeSession(
            session_id="test-session",
            app_id="app",
            access_key="ak",
            resource_id="volc.speech.dialog",
            app_key="app-key",
            ws_url="wss://example.invalid/realtime",
            input_mod="push_to_talk",
        )

        async def fake_wait(expected_event, _error_events=None):
            if expected_event == EVENT_CONNECTION_STARTED:
                return {"event": EVENT_CONNECTION_STARTED}
            if expected_event == EVENT_SESSION_STARTED:
                return {
                    "event": EVENT_SESSION_STARTED,
                    "payload_json": {"dialog_id": "dialog-1"},
                }
            raise AssertionError(f"unexpected event: {expected_event}")

        session._wait_for_event = fake_wait
        session._recv_loop = AsyncMock(return_value=None)

        with patch("websockets.connect", new=AsyncMock(return_value=fake_ws)):
            await session.start_session()

        self.assertGreaterEqual(len(fake_ws.sent), 2)
        start_session_frame = _parse_message(fake_ws.sent[1])
        payload = start_session_frame["payload_json"]

        self.assertEqual(payload["dialog"]["extra"]["input_mod"], "push_to_talk")
        self.assertNotIn("input_mod", payload["asr"]["extra"])

        if session._recv_task:
            session._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session._recv_task


if __name__ == "__main__":
    unittest.main()
