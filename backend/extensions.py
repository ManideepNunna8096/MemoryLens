from flask_jwt_extended import JWTManager

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:  # pragma: no cover - fallback for environments missing flask-limiter
    def get_remote_address():
        return '127.0.0.1'

    class Limiter:  # minimal no-op fallback
        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, app):
            return app

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

try:
    from flask_migrate import Migrate
except ImportError:  # pragma: no cover - fallback for environments missing flask-migrate
    class Migrate:  # minimal no-op fallback
        def init_app(self, app, db):
            return app


jwt = JWTManager()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
