import logging
import time
import uuid

from flask import g, request

from utils.logger import configure_pipeline_logging


def configure_logging(app):
    handler = configure_pipeline_logging(app.config['LOG_LEVEL'])

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(app.config['LOG_LEVEL'])
    app.logger.propagate = False

    # Suppress noisy Flask/Werkzeug request spam in the terminal.
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    @app.before_request
    def start_request_logging():
        g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        g.started_at = time.perf_counter()

    @app.after_request
    def attach_request_headers(response):
        duration_ms = round((time.perf_counter() - g.get('started_at', time.perf_counter())) * 1000, 2)
        response.headers['X-Request-ID'] = g.get('request_id', '')
        response.headers['X-Response-Time-MS'] = str(duration_ms)
        return response
