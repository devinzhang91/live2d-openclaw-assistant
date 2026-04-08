import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class _FakeRealtimeSession:
    def __init__(self):
        self.send_audio_calls = 0
        self.end_asr_calls = 0
        self.finish_calls = 0
        self.close_calls = 0
        self.send_text_calls = []

    @property
    def is_active(self):
        return True

    async def send_audio(self, _audio_chunk: bytes):
        self.send_audio_calls += 1

    async def end_asr(self):
        self.end_asr_calls += 1

    async def send_text(self, text: str):
        self.send_text_calls.append(text)

    async def finish_session(self):
        self.finish_calls += 1

    async def close(self):
        self.close_calls += 1


class _FakeRealtimeService:
    def __init__(self):
        self.sessions = []
        self.create_session_calls = []

    async def create_session(self, session_id: str, config=None, callback=None):
        session = _FakeRealtimeSession()
        self.sessions.append(session)
        self.create_session_calls.append(
            {
                "session_id": session_id,
                "config": config or {},
                "callback": callback,
            }
        )
        return session


class RealtimeWebSocketContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.fake_service = _FakeRealtimeService()
        self.service_patcher = patch(
            "backend.services.realtime_service.create_realtime_service",
            return_value=self.fake_service,
        )
        self.service_patcher.start()

    def tearDown(self):
        self.service_patcher.stop()
        self.client.close()

    def test_audio_end_signals_end_asr_for_active_session(self):
        with self.client.websocket_connect("/api/ws/realtime_volc") as websocket:
            websocket.send_json({"type": "audio_start"})
            websocket.receive_json()
            websocket.send_json({"type": "audio_end"})

        self.assertEqual(len(self.fake_service.sessions), 1)
        self.assertEqual(self.fake_service.sessions[0].end_asr_calls, 1)

    def test_starting_new_audio_session_closes_previous_realtime_session(self):
        with self.client.websocket_connect("/api/ws/realtime_volc") as websocket:
            websocket.send_json({"type": "audio_start"})
            websocket.receive_json()
            first_session = self.fake_service.sessions[0]
            websocket.send_json({"type": "audio_start"})
            websocket.receive_json()

        self.assertEqual(len(self.fake_service.sessions), 2)
        self.assertGreaterEqual(first_session.finish_calls, 1)
        self.assertGreaterEqual(first_session.close_calls, 1)

    def test_realtime_route_uses_push_to_talk_for_vad_driven_turns(self):
        with self.client.websocket_connect("/api/ws/realtime_volc") as websocket:
            websocket.send_json({"type": "audio_start"})
            websocket.receive_json()

        self.assertEqual(len(self.fake_service.create_session_calls), 1)
        self.assertEqual(
            self.fake_service.create_session_calls[0]["config"].get("input_mod"),
            "push_to_talk",
        )


if __name__ == "__main__":
    unittest.main()
