"""Use production startup options: TestServer otherwise enables cancellation implicitly."""
import asyncio
import contextlib
import io
import os
from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview_server


class PreviewCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_disconnect_cancels_work_frees_slot_and_preserves_admission_budget(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        calls = 0
        async def generate(_):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return b'ID3-fictional'
        app = preview_server.create_app(generator=generate, max_concurrent=1)
        with patch.dict(os.environ, {}, clear=True), patch('preview_server.create_app', return_value=app), \
                patch('preview_server.web.run_app') as serve:
            preview_server.main()
        # Do not use TestServer: it silently overrides handler_cancellation=True.
        runner = web.AppRunner(app, handler_cancellation=serve.call_args.kwargs.get('handler_cancellation', False))
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/api/preview'
        try:
            with contextlib.redirect_stdout(io.StringIO()) as logs:
                async with ClientSession() as client:
                    job = asyncio.create_task(client.post(url, json={'text': 'PRIVATE fictional passage'}))
                    await asyncio.wait_for(entered.wait(), 3)
                    job.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await job
                    await asyncio.wait_for(cancelled.wait(), 3)
                    for _ in range(4):
                        async with client.post(url, json={'text': 'A new original passage.'}) as response:
                            self.assertEqual(response.status, 200)
                    async with client.post(url, json={'text': 'Another original passage.'}) as response:
                        self.assertEqual(response.status, 429)
                    self.assertEqual(calls, 5)  # Cancellation does not refund admitted work.
            self.assertNotIn('PRIVATE', logs.getvalue())
        finally:
            await runner.cleanup()

    async def test_cancelled_worker_kills_descendants_waits_and_removes_temporary_audio(self):
        entered = asyncio.Event()
        directories = []
        async def communicate(_):
            entered.set()
            await asyncio.Event().wait()
        process = type('Process', (), {'pid': 98765, 'returncode': None,
                       'communicate': AsyncMock(side_effect=communicate), 'wait': AsyncMock(return_value=0)})()
        async def start(*args, **kwargs):
            directory = Path(args[-1])
            directories.append(directory)
            (directory/'partial.mp3').write_bytes(b'PRIVATE fictional partial audio')
            return process
        with patch('preview_server.asyncio.create_subprocess_exec', side_effect=start), \
                patch('preview_server.os.killpg') as terminate:
            job = asyncio.create_task(preview_server.generate_audio({'text': 'PRIVATE fictional passage'}))
            await asyncio.wait_for(entered.wait(), 3)
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
        terminate.assert_called_once_with(process.pid, signal.SIGKILL)
        process.wait.assert_awaited_once()
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].exists())


if __name__ == '__main__':
    unittest.main()
