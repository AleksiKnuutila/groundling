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


@app.command()
def prep(
    corpus: Path = typer.Option(
        ..., "--corpus", exists=True, file_okay=False, dir_okay=True,
    ),
    out: Path = typer.Option(None, "--out"),
    no_tables: bool = typer.Option(
        False, "--no-tables",
        help="Skip page.find_tables() — for debugging or prose-only corpora.",
    ),
):
    """Build a prep dir from a corpus of PDFs (for agent-driven mode)."""
    from groundling.prep import run_prep
    try:
        prep_dir = run_prep(
            corpus, out_dir=out, detect_tables=not no_tables,
        )
    except ZeroCorpusError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)
    typer.echo(str(prep_dir))


@app.command()
def render(
    prep_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, dir_okay=True,
    ),
    answer: str = typer.Option(
        ..., "--answer",
        help="Path to answer markdown file, or `-` for stdin.",
    ),
    state_dir: Path = typer.Option(None, "--state-dir"),
):
    """Validate agent markers, generate cite HTML, rewrite markdown."""
    import sys
    from groundling.render_cmd import run_render
    if answer == "-":
        answer_md = sys.stdin.read()
    else:
        answer_md = Path(answer).read_text(encoding="utf-8")
    result = run_render(
        prep_dir=prep_dir, answer_md=answer_md, state_dir=state_dir,
    )
    typer.echo(result.markdown)
    parts = [f"{k}={v}" for k, v in result.counters.items()]
    typer.echo(" ".join(parts), err=True)
    if result.counters["validated"] == 0:
        raise typer.Exit(code=5)
