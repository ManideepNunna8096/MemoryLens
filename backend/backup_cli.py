from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import click
import sqlalchemy as sa
from flask.cli import AppGroup

from models import db
from models.photo import Photo
from utils.logger import get_logger
from vector_search import pgvector_runtime_status


backup_logger = get_logger('BACKUP')
backup_cli = AppGroup('backup', help='Create PostgreSQL backups and export photo files.')


def _backend_dir():
    return Path(__file__).resolve().parent


def _default_backup_dir():
    return _backend_dir() / 'backups'


def _timestamp():
    return datetime.now(UTC).strftime('%Y%m%d_%H%M%S')


def _database_label(database_url):
    parsed = urlparse(database_url)
    return {
        'scheme': parsed.scheme,
        'host': parsed.hostname,
        'port': parsed.port,
        'database': parsed.path.lstrip('/'),
    }


def _find_pg_dump():
    candidates = []
    which = shutil.which('pg_dump')
    if which:
        candidates.append(Path(which))

    for root_env in ('ProgramFiles', 'ProgramFiles(x86)'):
        root = os.environ.get(root_env)
        if not root:
            continue
        pg_root = Path(root) / 'PostgreSQL'
        if not pg_root.exists():
            continue
        for candidate in sorted(pg_root.glob('*/bin/pg_dump.exe'), reverse=True):
            candidates.append(candidate)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _gather_photo_exports():
    from flask import current_app

    upload_root = Path(current_app.config['UPLOAD_FOLDER'])
    photos = Photo.query.order_by(Photo.id.asc()).all()
    filenames = []
    missing = []
    for photo in photos:
        if photo.filename:
            filenames.append(photo.filename)
            if not (upload_root / photo.filename).exists():
                missing.append(photo.filename)
    return upload_root, filenames, missing


def create_backup_package(output_dir=None, include_uploads=True, label=None):
    from flask import current_app

    database_url = current_app.config.get('SQLALCHEMY_DATABASE_URI')
    if not database_url:
        raise RuntimeError('DATABASE_URL must be set before creating a backup.')

    pg_dump = _find_pg_dump()
    if not pg_dump:
        raise RuntimeError('pg_dump was not found. Install PostgreSQL client tools or add pg_dump to PATH.')

    backup_dir = Path(output_dir) if output_dir else _default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = _timestamp()
    safe_label = f'_{label.strip().replace(" ", "_")}' if label and label.strip() else ''
    dump_path = backup_dir / f'memorylens{safe_label}_{stamp}.dump'
    uploads_zip_path = backup_dir / f'memorylens{safe_label}_{stamp}_uploads.zip'
    manifest_path = backup_dir / f'memorylens{safe_label}_{stamp}_manifest.json'

    stats = {
        'database': _database_label(database_url),
        'created_at': datetime.now(UTC).isoformat(),
        'dump_path': str(dump_path),
        'uploads_zip_path': None,
        'manifest_path': str(manifest_path),
        'counts': {
            'users': db.session.execute(sa.text('SELECT COUNT(*) FROM users')).scalar_one(),
            'events': db.session.execute(sa.text('SELECT COUNT(*) FROM events')).scalar_one(),
            'photos': db.session.execute(sa.text('SELECT COUNT(*) FROM photos')).scalar_one(),
            'jobs': db.session.execute(sa.text('SELECT COUNT(*) FROM jobs')).scalar_one(),
        },
        'pgvector': pgvector_runtime_status(),
        'uploads': {
            'included': bool(include_uploads),
            'file_count': 0,
            'missing_count': 0,
            'missing_files': [],
        },
    }

    env = os.environ.copy()
    command = [
        str(pg_dump),
        '--dbname',
        database_url,
        '--format=custom',
        '--file',
        str(dump_path),
        '--no-owner',
        '--no-acl',
    ]
    backup_logger.info('Running pg_dump backup to %s', dump_path)
    subprocess.run(command, check=True, env=env)

    if include_uploads:
        upload_root, filenames, missing_files = _gather_photo_exports()
        stats['uploads']['file_count'] = len(filenames)
        stats['uploads']['missing_count'] = len(missing_files)
        stats['uploads']['missing_files'] = missing_files
        with zipfile.ZipFile(uploads_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in filenames:
                file_path = upload_root / filename
                if file_path.exists():
                    archive.write(file_path, arcname=filename)
        stats['uploads_zip_path'] = str(uploads_zip_path)

    manifest_path.write_text(json.dumps(stats, indent=2), encoding='utf-8')
    backup_logger.info('Backup manifest written to %s', manifest_path)

    return stats


@backup_cli.command('create')
@click.option('--output-dir', default=None, help='Directory where backup files should be written.')
@click.option('--label', default=None, help='Optional label added to the backup filename.')
@click.option('--include-uploads/--no-uploads', default=True, show_default=True)
def backup_create_command(output_dir, label, include_uploads):
    """Create a PostgreSQL backup plus an optional uploads archive."""
    stats = create_backup_package(
        output_dir=output_dir,
        include_uploads=include_uploads,
        label=label,
    )

    click.echo(json.dumps(stats, indent=2))
