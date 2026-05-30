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
    web_base: str = typer.Option(
        "file://", "--web-base",
        help=(
            "Base URL for cite links in the rewritten markdown. Default "
            "`file://` emits absolute on-disk paths. Pass e.g. "
            "`http://localhost:8123` to pair with `groundling serve` when "
            "your terminal doesn't make file:// links clickable."
        ),
    ),
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
        web_base=web_base,
    )
    typer.echo(result.markdown)
    parts = [f"{k}={v}" for k, v in result.counters.items()]
    typer.echo(" ".join(parts), err=True)
    if result.counters["validated"] == 0:
        raise typer.Exit(code=5)


@app.command()
def serve(
    state_dir: Path = typer.Option(
        Path("qa-runs"), "--state-dir",
        help="Directory to serve. Should be the parent of one or more "
             "render run dirs (the default `--state-dir` for `render`).",
    ),
    port: int = typer.Option(8123, "--port"),
    host: str = typer.Option("127.0.0.1", "--host"),
):
    """Serve a state dir over HTTP so cite URLs work in terminals that
    don't make file:// links clickable. Pair with
    `groundling render --web-base http://localhost:8123`."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    resolved = state_dir.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(
        SimpleHTTPRequestHandler, directory=str(resolved),
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    typer.echo(f"serving {resolved} on http://{host}:{port}", err=True)
    typer.echo(
        f"cite URLs: http://{host}:{port}/<run_id>/cites/N.html", err=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        typer.echo("shutting down", err=True)
        httpd.shutdown()


@app.command()
def init():
    """Drop or refresh AGENTS.md in the current directory.

    Creates AGENTS.md with groundling's workflow instructions if absent.
    If AGENTS.md exists and already has our marked section, updates it
    in place. If AGENTS.md exists without our markers, appends our
    section at the end — preserving the user's content.
    """
    from groundling.init_cmd import run_init

    result = run_init(Path.cwd())
    typer.echo(f"{result.action}: {result.path}")


@app.command()
def instructions():
    """Print the bundled AGENTS.md template to stdout — no write."""
    from groundling.init_cmd import load_template

    typer.echo(load_template())
