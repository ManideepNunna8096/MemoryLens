import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ml_services import get_text_embedding_fn
from vector_search import score_ready_photos


search_bp = Blueprint('search', __name__)

STOPWORDS = {
    'a', 'an', 'and', 'at', 'for', 'from', 'in', 'inside', 'of', 'on',
    'photo', 'photos', 'picture', 'pictures', 'show', 'showing', 'the',
    'to', 'with'
}


def get_clip():
    return get_text_embedding_fn()


def _normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower()).strip()


def _tokenize(text: str) -> set:
    words = re.findall(r'[a-z0-9]+', text.lower())
    return {word for word in words if word not in STOPWORDS and len(word) > 1}


def _scene_boost(query: str, scene: str) -> float:
    query_norm = _normalize_text(query)
    scene_norm = _normalize_text(scene)

    if not scene_norm:
        return 0.0

    if scene_norm in query_norm or query_norm in scene_norm:
        return 0.18

    query_tokens = _tokenize(query_norm)
    scene_tokens = _tokenize(scene_norm)
    if not query_tokens or not scene_tokens:
        return 0.0

    overlap = len(query_tokens & scene_tokens) / len(scene_tokens)
    return min(0.16, overlap * 0.14)


def _relevance_percent(score: float, floor: float, ceiling: float) -> int:
    if ceiling <= floor:
        return 100
    scaled = (score - floor) / (ceiling - floor)
    scaled = max(0.0, min(1.0, scaled))
    return int(round(55 + scaled * 45))


@search_bp.route('', methods=['GET'])
@jwt_required()
def search_photos():
    user_id = int(get_jwt_identity())
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'error': 'Query is required'}), 400

    get_text_embedding = get_clip()
    text_vec = get_text_embedding(query)

    clip_scored, _backend = score_ready_photos(user_id, text_vec, limit=200)
    if not clip_scored:
        return jsonify([]), 200

    scored = []
    for item in clip_scored:
        photo = item['photo']
        clip_score = item['clip_score']
        scene_score = _scene_boost(query, photo.scene or '')
        final_score = clip_score + scene_score
        scored.append(
            {
                'photo': photo,
                'clip_score': clip_score,
                'scene_score': scene_score,
                'final_score': final_score,
            }
        )

    if not scored:
        return jsonify([]), 200

    scored.sort(key=lambda item: item['final_score'], reverse=True)
    top_final = scored[0]['final_score']
    top_clip = scored[0]['clip_score']
    min_final_score = max(0.30, top_final - 0.10)
    min_clip_score = max(0.22, top_clip - 0.12)

    results = []
    for item in scored[:20]:
        if item['final_score'] < min_final_score:
            continue
        if item['clip_score'] < min_clip_score and item['scene_score'] < 0.12:
            continue

        photo_data = item['photo'].to_dict()
        photo_data['score'] = round(item['final_score'], 4)
        photo_data['clip_score'] = round(item['clip_score'], 4)
        photo_data['relevance'] = _relevance_percent(item['final_score'], min_final_score, top_final)
        results.append(photo_data)

    return jsonify(results), 200
