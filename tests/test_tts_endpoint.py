"""The upstream SDK owns synthesis routing and authentication."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tts


class EndpointTests(unittest.TestCase):
    def test_stream_preserves_sdk_endpoint_and_authentication(self):
        # The fixed SDK still uses the old hostname; the removed override must
        # not divert its v2 authentication to the temporary alternate endpoint.
        for endpoint in (
            "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=fictional",
            "wss://future.example/speech?NewAuth=fictional",
        ):
            with self.subTest(endpoint=endpoint):
                sdk = types.ModuleType("edge_tts")
                sdk.communicate = types.SimpleNamespace(WSS_URL=endpoint)
                requests = []

                class Communicate:
                    def __init__(self, text, voice, rate):
                        requests.append((sdk.communicate.WSS_URL, text))

                    async def stream(self):
                        yield {"type": "audio", "data": b"fictional-audio"}

                sdk.Communicate = Communicate
                with patch.dict(sys.modules, {"edge_tts": sdk}), tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "audio.mp3"
                    self.assertTrue(tts.speak("Fictional passage.", path))
                    self.assertEqual(path.read_bytes(), b"fictional-audio")
                self.assertEqual(requests, [(endpoint, "Fictional passage.")])
                self.assertEqual(sdk.communicate.WSS_URL, endpoint)


if __name__ == "__main__":
    unittest.main()
