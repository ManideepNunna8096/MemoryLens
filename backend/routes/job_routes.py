from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from models.job import BackgroundJob


job_bp = Blueprint('jobs', __name__)


@job_bp.route('/<job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    user_id = int(get_jwt_identity())
    job = BackgroundJob.query.filter_by(id=job_id, user_id=user_id).first()

    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify(job.to_dict()), 200
