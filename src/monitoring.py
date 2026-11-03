"""Private-content-free generation diagnostics and workflow health counts."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
import os
from pathlib import Path
import subprocess
import re
import sys
import uuid


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


SUMMARY_REASONS = frozenset({'none', 'authentication_failed', 'permission_denied', 'model_unavailable',
    'request_rejected', 'rate_limited', 'service_unavailable', 'provider_error', 'response_blocked',
    'truncated_response', 'empty_response', 'timeout', 'connection_error', 'missing_file', 'io_error',
    'subprocess_error', 'invalid_value', 'runtime_error', 'unexpected_error', 'budget_exceeded'})


@dataclass
class SummaryDiagnostic:
    identity: str = field(default_factory=lambda: uuid.uuid4().hex)
    reason: str = 'none'
    model_slot: int = 0
    attempt: int = 0
    http_status: int | None = None

    def fields(self):
        reason = self.reason if type(self.reason) is str and self.reason in SUMMARY_REASONS else 'unexpected_error'
        identity = self.identity if type(self.identity) is str and re.fullmatch(r'[0-9a-f]{32}', self.identity) else 'unknown'
        slot = self.model_slot if type(self.model_slot) is int and 0 <= self.model_slot <= 2 else 0
        attempt = self.attempt if type(self.attempt) is int and 0 <= self.attempt <= 3 else 0
        status = f' http_status={self.http_status}' if type(self.http_status) is int and 100 <= self.http_status <= 599 else ''
        return f'reason={reason} summary_id={identity} model_slot={slot} attempt={attempt}{status}'

    def log(self, event):
        event = event if type(event) is str and event in {'attempt', 'retry', 'exhausted', 'completed', 'failed'} else 'failed'
        print(f'summary_request event={event} {self.fields()}', file=sys.stderr, flush=True)


def summary_diagnostic():
    diagnostic = SummaryDiagnostic()
    if episode := _episode_diagnostic.get():
        episode.summary = diagnostic
    return diagnostic


@dataclass
class EpisodeDiagnostic:
    stage: str = 'unknown'
    summary: SummaryDiagnostic | None = None

    def fields(self, error):
        stage = self.stage if type(self.stage) is str and self.stage in EPISODE_STAGES else 'unknown'
        if stage == 'summary' and type(self.summary) is SummaryDiagnostic:
            return f'stage={stage} {self.summary.fields()}'
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
