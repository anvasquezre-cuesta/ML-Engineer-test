"""Exercise the real health route while a simulated OCR worker is running."""

import asyncio
import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.main import app as actual_app
from app.models.document import OCRDocument
from app.services.ocr_service import OCRService


def test_health_remains_responsive_during_async_ocr(monkeypatch):
    started = asyncio.Event()
    finish = asyncio.Event()

    async def fake_job(self, source, *, is_bytes):
        started.set()
        await finish.wait()
        return OCRDocument(())

    monkeypatch.setattr(OCRService, "_execute_job", fake_job)
    service = OCRService(Settings(ocr_max_concurrent_jobs=1))
    # Use the real health route with a test-only endpoint, not the unfinished API.
    test_app = FastAPI()
    test_app.include_router(actual_app.router)

    @test_app.post("/_test_ocr")
    async def run_ocr():
        return {"pages": len((await service.extract_async(b"test")).pages)}

    async def run():
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ocr_request = asyncio.create_task(client.post("/_test_ocr"))
            async with asyncio.timeout(15):
                await started.wait()
            health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            assert not ocr_request.done()
            finish.set()
            assert (await ocr_request).json() == {"pages": 0}
            await service.aclose()

    asyncio.run(run())
