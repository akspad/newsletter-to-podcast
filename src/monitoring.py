"""Count-only generation reports for the workflow's post-publication health check."""
from dataclasses import dataclass, fields
import os
from pathlib import Path


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
