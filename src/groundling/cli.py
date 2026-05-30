"""Typer entry point: groundling ask "..." --corpus DIR [--web-search]"""
from __future__ import annotations

from pathlib import Path

import typer

from groundling.errors import (
    NoTextError,
    ZeroCitationsError,
    ZeroCorpusError,
)


app = typer.Typer(help="Grounded Q&A over a folder of PDFs.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Force Typer to treat `ask` as a true subcommand even when it's
    the only command registered."""


@app.command()
def ask(
    question: str = typer.Argument(..., help="The question to ask."),
    corpus: Path = typer.Option(
        ..., "--corpus", exists=True, file_okay=False, dir_okay=True,
        help="Directory of PDFs to ground the answer in.",
    ),
    model: str = typer.Option("claude-sonnet-4-6", "--model"),
    state_dir: Path = typer.Option(None, "--state-dir"),
    cache_dir: Path = typer.Option(None, "--cache-dir"),
    web_search: bool = typer.Option(
        False, "--web-search",
        help="Enable Anthropic server-side web_search tool.",
    ),
):
    """Answer a free-form question over a folder of PDFs with citations."""
    from groundling.orchestration import run_ask
    try:
        result = run_ask(
            corpus_dir=corpus,
            question=question,
            model=model,
            state_dir=state_dir,
            cache_dir=cache_dir,
            web_search=web_search,
        )
    except ZeroCorpusError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)
    except NoTextError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=3)
    except ZeroCitationsError as exc:
        typer.echo(exc.answer_md)
        typer.echo("(no citations returned)", err=True)
        raise typer.Exit(code=5)
    typer.echo(result.answer_md)
