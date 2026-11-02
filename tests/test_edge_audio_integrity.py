"""Provider corruption, mid-stream cancellation and text boundaries need no live TTS."""
import asyncio
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from xml.sax.saxutils import unescape

from aiohttp import ClientSession, ClientResponseError, web
import edge_tts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import checkpoints
import preview
import preview_server
import tts

TEXT = 'An original sentence for a local speech test.'
VOICE = 'en-US-AndrewNeural'
VALID = DAMAGED = b''


def setUpModule():
    global VALID, DAMAGED
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'tone.mp3'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=3', '-c:a', 'libmp3lame', '-b:a', '48k',
                        '-ar', '24000', '-ac', '1', str(path)], check=True, timeout=15)
        VALID = path.read_bytes()
    third = len(VALID) // 3
    DAMAGED = VALID[:third] + b'\0' * third + VALID[2 * third:]


def speech_factory(outputs, calls):
    class Speech:
        def __init__(self, *args, **kwargs):
            self.attempt = len(calls)
            calls.append((args, kwargs))

        async def stream(self):
            output = outputs[min(self.attempt, len(outputs) - 1)]
            if isinstance(output, Exception):
                raise output
            yield {'type': 'audio', 'data': output}
    return Speech


class AudioIntegrityTests(unittest.TestCase):
    def test_header_duration_does_not_establish_full_decodability(self):
        with tempfile.TemporaryDirectory() as directory:
            good, bad = Path(directory) / 'good.mp3', Path(directory) / 'bad.mp3'
            good.write_bytes(VALID)
            bad.write_bytes(DAMAGED)
            self.assertEqual(tts.duration(good), tts.duration(bad))
            self.assertGreater(tts.duration(good, verify=True), 3)
            with self.assertRaises(subprocess.SubprocessError):
                tts.duration(bad, verify=True)

    def test_personal_speech_retries_corruption_before_caching_or_joining(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory, \
                patch('edge_tts.Communicate', speech_factory([DAMAGED, VALID], calls)), patch('tts.time.sleep'):
            path = Path(directory) / 'speech.mp3'
            self.assertTrue(tts.speak(TEXT, path))
            self.assertEqual(path.read_bytes(), VALID)
        self.assertEqual(len(calls), 2)

    def test_damaged_cached_clip_is_regenerated_without_losing_valid_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {}, clear=True):
            root = Path(directory)
            with checkpoints.use(root / 'state'):
                cache = checkpoints.current()
                key = cache.key(TEXT, tts.VOICE, tts.RATE)
                cache.put(key, b'audio:' + DAMAGED)
                calls = []
                with patch('edge_tts.Communicate', speech_factory([VALID], calls)):
                    paths = tts.speak_pieces(TEXT, root, 'recovered')
                self.assertEqual(paths[0].read_bytes(), VALID)
                self.assertEqual(cache.get(key), b'audio:' + VALID)
                with patch('tts.speak') as speech:
                    reused = tts.speak_pieces(TEXT, root, 'reused')
                speech.assert_not_called()
                self.assertEqual(reused[0].read_bytes(), VALID)

    def test_probe_and_decode_processes_have_finite_deadlines(self):
        for failure_at, timeout in ((1, 15), (2, 30)):
            def run(args, **kwargs):
                if (args[0] == 'ffprobe') == (failure_at == 1):
                    self.assertEqual(kwargs['timeout'], timeout)
                    raise subprocess.TimeoutExpired(args[0], timeout)
                return subprocess.CompletedProcess(args, 0, stdout='3.048\n')
            with self.subTest(failure_at=failure_at), patch('tts.subprocess.run', side_effect=run):
                with self.assertRaises(subprocess.TimeoutExpired):
                    tts.duration(Path('fictional.mp3'), verify=True)

    def test_long_chunks_and_sdk_escaping_preserve_visible_characters(self):
        text = ('Dr. García said <example> & "quotes" are literal; keep &amp; too. '
                '研究の記録には細かい観察が含まれています。\n') * 120
        chunks = tts.chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= tts.CHUNK_CHARS for chunk in chunks))
        received = []
        for chunk in chunks:
            request = edge_tts.Communicate(chunk, VOICE)
            received.extend(unescape(part.decode()) for part in request.texts)
        self.assertEqual(''.join(''.join(received).split()), ''.join(text.split()))
        self.assertEqual(' '.join(tts.article_chunks(text)).split(), text.split())


class PreviewIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_and_damaged_media_retry_with_fresh_audio(self):
        for broken in (b'not an MP3', DAMAGED):
            calls = []
            errors = io.StringIO()
            with self.subTest(broken_size=len(broken)), tempfile.TemporaryDirectory() as directory, \
                    patch('edge_tts.Communicate', speech_factory([broken, VALID], calls)), \
                    patch('preview.asyncio.sleep', AsyncMock()), patch('sys.stderr', errors):
                path = Path(directory) / 'speech.mp3'
                await preview.narrate(TEXT, VOICE, path)
                self.assertEqual(path.read_bytes(), VALID)
            self.assertEqual(len(calls), 2)
            self.assertIn('status=retry', errors.getvalue())
            self.assertNotIn('not an MP3', errors.getvalue())

    async def test_persistent_corruption_stops_after_three_attempts(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory, \
                patch('edge_tts.Communicate', speech_factory([DAMAGED], calls)), \
                patch('preview.asyncio.sleep', AsyncMock()) as pause:
            with self.assertRaises(preview.IncompleteSpeechError):
                await preview.narrate(TEXT, VOICE, Path(directory) / 'speech.mp3')
        self.assertEqual(len(calls), 3)
        self.assertEqual([call.args[0] for call in pause.await_args_list], [1, 2])

    async def test_http_retries_distinguish_transient_from_permanent_failures(self):
        for status, attempts in ((403, 1), (429, 2), (503, 2)):
            error = ClientResponseError(None, (), status=status, message='PRIVATE provider details')
            calls = []
            logs = io.StringIO()
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, \
                    patch('edge_tts.Communicate', speech_factory([error, VALID], calls)), \
                    patch('preview.asyncio.sleep', AsyncMock()), patch('sys.stderr', logs):
                if status == 403:
                    with self.assertRaises(ClientResponseError):
                        await preview.narrate(TEXT, VOICE, Path(directory) / 'speech.mp3')
                else:
                    await preview.narrate(TEXT, VOICE, Path(directory) / 'speech.mp3')
            self.assertEqual(len(calls), attempts)
            self.assertNotIn('PRIVATE', logs.getvalue())

    async def test_cancellation_after_first_audio_closes_stream_and_releases_capacity(self):
        entered, closed, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls, directories = [], []
        class Speech:
            def __init__(self, *args, **kwargs):
                calls.append(args)
                self.first = len(calls) == 1
            async def stream(self):
                try:
                    yield {'type': 'audio', 'data': VALID[:1024] if self.first else VALID}
                    if self.first:
                        entered.set()
                        await asyncio.Event().wait()
                finally:
                    if self.first:
                        closed.set()
        async def generate(payload):
            first = not directories
            try:
                with tempfile.TemporaryDirectory() as directory:
                    directories.append(Path(directory))
                    path = Path(directory) / 'speech.mp3'
                    await preview.narrate(payload['text'], payload['voice'], path)
                    return path.read_bytes()
            finally:
                if first:
                    cleaned.set()
        runner = web.AppRunner(preview_server.create_app(generator=generate, max_concurrent=1),
                               handler_cancellation=True)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/api/preview'
        try:
            with patch('edge_tts.Communicate', Speech), patch('preview.asyncio.sleep', AsyncMock()) as pause, \
                    contextlib.redirect_stdout(io.StringIO()):
                async with ClientSession() as client:
                    job = asyncio.create_task(client.post(url, json={'text': TEXT}))
                    await asyncio.wait_for(entered.wait(), 3)
                    job.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await job
                    await asyncio.wait_for(closed.wait(), 3)
                    await asyncio.wait_for(cleaned.wait(), 3)
                    self.assertFalse(directories[0].exists())
                    async with client.post(url, json={'text': TEXT}) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(await response.read(), VALID)
                self.assertEqual(len(calls), 2)
                pause.assert_not_awaited()
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
