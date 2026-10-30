"""Private-content-free generation diagnostics and workflow health counts."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
import os
from pathlib import Path
import subprocess


EPISODE_STAGES = frozenset({'unknown', 'extract', 'prepare', 'summary', 'speech', 'audio_metadata'})
_episode_diagnostic = ContextVar('episode_diagnostic', default=None)


def failure_reason(error):
    """Return only fixed codes, never provider messages or exception class names."""
    categories = ((TimeoutError, 'timeout'), (subprocess.TimeoutExpired, 'timeout'),
                  (ConnectionError, 'connection_error'), (FileNotFoundError, 'missing_file'),
                  (PermissionError, 'permission_denied'), (OSError, 'io_error'),
                  (subprocess.SubprocessError, 'subprocess_error'), (ValueError, 'invalid_value'),
                  (RuntimeError, 'runtime_error'))
    return next((code for kind, code in categories if isinstance(error, kind)), 'unexpected_error')


@dataclass
class EpisodeDiagnostic:
    stage: str = 'unknown'

    def fields(self, error):
        stage = self.stage if type(self.stage) is str and self.stage in EPISODE_STAGES else 'unknown'
        return f'stage={stage} reason={failure_reason(error)}'


@contextmanager
def episode_attempt():
    """Scope stage tracking to one attempt; preserve the original exception and retry policy."""
    diagnostic = EpisodeDiagnostic()
    token = _episode_diagnostic.set(diagnostic)
    try:
        yield diagnostic
    finally:
        _episode_diagnostic.reset(token)


def set_episode_stage(stage):
    diagnostic = _episode_diagnostic.get()
    if diagnostic is not None:
        diagnostic.stage = stage if type(stage) is str and stage in EPISODE_STAGES else 'unknown'


@dataclass
class GenerationReport:
    attempted_articles: int = 0
    created_articles: int = 0
    created_audio_files: int = 0
    failed_articles: int = 0
    deferred_articles: int = 0
    skipped_articles: int = 0
    queued_articles: int = 0

    def emit(self):
        values = {field.name: getattr(self, field.name) for field in fields(self)}
        if any(type(value) is not int or value < 0 for value in values.values()):
            raise ValueError("Generation report counts must be nonnegative integers")
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with Path(output).open("a", encoding="utf-8") as target:
                target.write("".join(f"{name}={value}\n" for name, value in values.items()))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as target:
                target.write("## Episode generation\n\n| Result | Articles/files |\n| --- | --- |\n")
                for name, value in values.items():
                    target.write(f"| {name.replace('_', ' ').capitalize()} | {value} |\n")
                if self.failed_articles:
                    target.write("\nUnrecovered generation errors will fail the final health check after output is saved/published.\n")
