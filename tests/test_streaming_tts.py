"""
E2E 流式 TTS 测试 — 验证 token-level 喂入 + 并发接收音频帧
"""
import asyncio
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 加载 .env 环境变量
env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


async def test_streaming():
    import uuid
    from backend.services.tts_volc import VolcTTSService

    svc = VolcTTSService()
    session = await svc.create_session(session_id=str(uuid.uuid4()))
    print("Session started OK")

    texts = ["你好，", "今天天气不错，", "适合外出散步。"]
    total_bytes = 0
    first_chunk_time = None
    start = time.time()

    async def feeder():
        for t in texts:
            await session.send_task(t)
            print(f"  → send_task({t!r})")
            await asyncio.sleep(0.05)
        await session.finish_session()
        print("  → finish_session")

    async def receiver():
        nonlocal total_bytes, first_chunk_time
        async for chunk in session.get_audio_chunks():
            if first_chunk_time is None:
                first_chunk_time = time.time() - start
                print(
                    f"  ← 首帧音频延迟: {first_chunk_time:.3f}s, size={len(chunk)}"
                )
            total_bytes += len(chunk)
        elapsed = time.time() - start
        print(f"  ← 全部接收完成, total={total_bytes} bytes, elapsed={elapsed:.3f}s")

    await asyncio.gather(feeder(), receiver())
    await session.close()
    print("Session closed OK")
    assert total_bytes > 1000, f"音频太少: {total_bytes}"
    print("✅ E2E 流式 TTS 测试通过")


if __name__ == "__main__":
    asyncio.run(test_streaming())
