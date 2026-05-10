from pathlib import Path

from flask import Flask
from flask_cors import CORS

from app_logging import configure_logging
from config.settings import Config
from error_handlers import register_error_handlers, register_jwt_handlers
from extensions import jwt, limiter, migrate
from models import db
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from routes.duplicates_routes import duplicates_bp
from routes.event_routes import event_bp
from routes.folder_routes import folder_bp
from routes.job_routes import job_bp
from routes.photo_routes import photo_bp
from routes.search_routes import search_bp
from routes.share_routes import share_bp
from routes.timeline_routes import timeline_bp
from utils.logger import get_logger
from vector_search import pgvector_runtime_status
from backup_cli import backup_cli
from vector_cli import vectors_cli

startup_logger = get_logger('STARTUP')
db_logger = get_logger('DB')
vector_logger = get_logger('VECTOR')


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    database_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if not database_uri:
        raise RuntimeError('DATABASE_URL must be set. MemoryLens now requires PostgreSQL.')
    if not str(database_uri).startswith('postgresql://'):
        raise RuntimeError('MemoryLens now supports PostgreSQL only. Set DATABASE_URL to a PostgreSQL URL.')

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)

    configure_logging(app)
    db_logger.info('PostgreSQL fully active')

    CORS(
        app,
        resources={
            r'/*': {
                'origins': app.config['CORS_ORIGINS'],
            }
        },
    )

    jwt.init_app(app)
    limiter.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        vector_status = pgvector_runtime_status()
        if vector_status.get('pgvector_enabled'):
            vector_logger.info('pgvector enabled')
        else:
            vector_logger.info(
                f"pgvector pending ({vector_status.get('reason', 'run flask db upgrade')})"
            )

    register_jwt_handlers(jwt)
    register_error_handlers(app)

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(duplicates_bp, url_prefix='/duplicates')
    app.register_blueprint(photo_bp, url_prefix='/photos')
    app.register_blueprint(folder_bp, url_prefix='/folders')
    app.register_blueprint(search_bp, url_prefix='/search')
    app.register_blueprint(timeline_bp, url_prefix='/timeline')
    app.register_blueprint(event_bp, url_prefix='/events')
    app.register_blueprint(job_bp, url_prefix='/jobs')
    app.register_blueprint(share_bp, url_prefix='/share')
    app.cli.add_command(vectors_cli)
    app.cli.add_command(backup_cli)

    return app


if __name__ == '__main__':
    app = create_app()
    startup_logger.info('MemoryLens backend starting...')
    app.run(debug=app.config['DEBUG'], host=app.config['HOST'], port=app.config['PORT'])
