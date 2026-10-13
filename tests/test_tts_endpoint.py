"""Endpoint compatibility regressions without live speech-service requests."""
from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tts


class EndpointTests(unittest.TestCase):
    def client(self, endpoint):
        sdk = types.ModuleType("edge_tts")
        sdk.communicate = types.SimpleNamespace(WSS_URL=endpoint)
        constants = types.ModuleType("edge_tts.constants")
        constants.TRUSTED_CLIENT_TOKEN = "fictional-client-token"
        constants.VOICE_LIST = "https://speech.platform.bing.com/voices/list"
        requests = []

        class Communicate:
            def __init__(self, text, voice, rate):
                self.text, self.voice, self.rate = text, voice, rate

            async def stream(self):
                requests.append((sdk.communicate.WSS_URL, self.text, self.voice, self.rate))
                yield {"type": "audio", "data": b"fictional-audio"}

        sdk.Communicate = Communicate
        return sdk, constants, requests

    def test_stream_routes_legacy_client_without_changing_voice_discovery(self):
        sdk, constants, requests = self.client(
            "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=old")
        with patch.dict(sys.modules, {"edge_tts": sdk, "edge_tts.constants": constants}), \
                patch.dict(os.environ, {"TTS_VOICE": "fictional-voice", "TTS_RATE": "+10%"}), \
                tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio.mp3"
            self.assertTrue(tts.speak("Fictional passage.", path))
            self.assertEqual(path.read_bytes(), b"fictional-audio")
        self.assertEqual(requests, [(
            "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?Ocp-Apim-Subscription-Key=fictional-client-token",
            "Fictional passage.", "fictional-voice", "+10%")])
        self.assertEqual(constants.VOICE_LIST, "https://speech.platform.bing.com/voices/list")

    def test_future_sdk_endpoint_and_auth_are_not_overwritten(self):
        endpoint = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v2?NewAuth=fictional"
        sdk, constants, requests = self.client(endpoint)
        with patch.dict(sys.modules, {"edge_tts": sdk, "edge_tts.constants": constants}):
            tts.edge_communication("Fictional passage.", "fictional-voice", "+0%")
        self.assertEqual(sdk.communicate.WSS_URL, endpoint)


if __name__ == "__main__":
    unittest.main()
