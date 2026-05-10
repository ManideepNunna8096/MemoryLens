from http import HTTPStatus

from flask import jsonify
from werkzeug.exceptions import HTTPException

from utils.logger import get_logger


error_logger = get_logger('ERROR')


def _error_response(message, status_code, code=None):
    payload = {
        'error': message,
        'status': status_code,
    }
    if code:
        payload['code'] = code
    return jsonify(payload), status_code


def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        return _error_response(error.description, error.code, error.name.lower().replace(' ', '_'))

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error):
        error_logger.error(f'Unhandled exception: {error}', exc_info=True)
        return _error_response(HTTPStatus.INTERNAL_SERVER_ERROR.phrase, HTTPStatus.INTERNAL_SERVER_ERROR)


def register_jwt_handlers(jwt):
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        token_type = jwt_payload.get('type', 'access')
        return _error_response(f'{token_type.capitalize()} token expired', 401, 'token_expired')

    @jwt.invalid_token_loader
    def invalid_token_callback(message):
        return _error_response(message, 401, 'invalid_token')

    @jwt.unauthorized_loader
    def missing_token_callback(message):
        return _error_response(message, 401, 'missing_token')

    @jwt.needs_fresh_token_loader
    def fresh_token_callback(jwt_header, jwt_payload):
        return _error_response('Fresh access token required', 401, 'fresh_token_required')

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return _error_response('Token has been revoked', 401, 'token_revoked')
