from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import limiter
from models import db
from models.user import User
from security import is_valid_email, validate_password_strength


auth_bp = Blueprint('auth', __name__)


def _build_auth_response(user, status_code):
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    return (
        jsonify(
            {
                'token': access_token,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'user': user.to_dict(),
            }
        ),
        status_code,
    )


@auth_bp.route('/register', methods=['POST'])
@limiter.limit(lambda: current_app.config['AUTH_RATE_LIMIT'])
def register():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not name or not email or not password:
        return jsonify({'error': 'All fields are required'}), 400

    if not is_valid_email(email):
        return jsonify({'error': 'Please enter a valid email address'}), 400

    is_strong, password_error = validate_password_strength(password)
    if not is_strong:
        return jsonify({'error': password_error}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(
        name=name,
        email=email,
        password=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()

    return _build_auth_response(user, 201)


@auth_bp.route('/login', methods=['POST'])
@limiter.limit(lambda: current_app.config['AUTH_RATE_LIMIT'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid email or password'}), 401

    return _build_auth_response(user, 200)


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
@limiter.limit(lambda: current_app.config['AUTH_RATE_LIMIT'])
def refresh():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    return _build_auth_response(user, 200)
