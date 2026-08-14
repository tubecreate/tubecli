"""CapCut TTS — text-to-speech through the user's own CapCut account.

Wraps the bundled CapCut-TTS Node server (server/, MIT). The user adds their
CapCut account(s) in the dashboard; the extension stores them encrypted, runs
the Node server on loopback seeded with one account, and proxies synthesize /
speaker calls to it — each request carrying the chosen account's credentials.
"""
import logging

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("CapCutTTS")


class CapCutTtsExtension(Extension):
    name = "capcut_tts"
    version = "1.0.0"
    description = "Text-to-speech qua tài khoản CapCut của bạn (giọng CapCut / ElevenLabs)."
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        # Nothing heavy here — the Node server is built and started lazily on the
        # first synthesize call, so enabling the extension is instant and does
        # not block startup on an npm install. Just make sure the data dir is there.
        try:
            from tubecli.config import ext_data_path
            ext_data_path(self.name).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("[CapCut] could not prepare data dir: %s", e)

    def on_disable(self):
        # Stop the background Node process when the extension is turned off.
        try:
            from tubecli.extensions.capcut_tts.process_manager import node_manager
            node_manager.stop()
        except Exception:
            pass

    def get_routes(self):
        from tubecli.extensions.capcut_tts.routes import router
        return router

    def get_commands(self):
        from tubecli.extensions.capcut_tts.commands import capcut_tts_group
        return capcut_tts_group
