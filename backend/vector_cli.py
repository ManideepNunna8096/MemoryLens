import json

import click
from flask.cli import AppGroup

from vector_search import backfill_missing_pgvector_embeddings, pgvector_runtime_status


vectors_cli = AppGroup('vectors', help='Inspect and backfill pgvector embeddings.')


@vectors_cli.command('status')
def vector_status_command():
    """Show whether pgvector is available for the current app config."""
    summary = pgvector_runtime_status()
    click.echo(json.dumps(summary, indent=2))


@vectors_cli.command('backfill')
@click.option('--batch-size', default=100, show_default=True, type=click.IntRange(min=1, max=5000))
@click.option('--limit', default=None, type=click.IntRange(1), help='Optionally stop after this many candidate photos.')
def vector_backfill_command(batch_size, limit):
    """Backfill clip_vector_pg from existing stored CLIP embeddings."""
    summary = backfill_missing_pgvector_embeddings(batch_size=batch_size, limit=limit)

    if not summary.get('pgvector_enabled'):
        click.echo('Skipping pgvector backfill.')
        if summary.get('reason'):
            click.echo(summary['reason'])
        return

    click.echo(
        'Backfill complete: '
        f"{summary['updated']} updated, "
        f"{summary['skipped']} skipped, "
        f"{summary['failed']} failed, "
        f"{summary['remaining']} remaining."
    )
