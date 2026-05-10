import os
from collections import Counter, defaultdict

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize


PLACES365_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'categories_places365.txt',
)
PCA_COMPONENTS = 40
TIME_GAP_HOURS = 72
MIN_CLUSTER_SIZE = 3


def _normalize_scene(scene: str) -> str:
    return ' '.join(
        str(scene or 'unknown')
        .strip()
        .lower()
        .replace('_', ' ')
        .replace('/', ' ')
        .split()
    )


def _title_case(scene: str) -> str:
    return ' '.join(word.capitalize() for word in _normalize_scene(scene).split())


def _load_places365_scenes() -> tuple:
    scenes = []
    try:
        with open(PLACES365_PATH, encoding='utf-8') as handle:
            for raw_line in handle:
                token = raw_line.strip().split(' ')[0]
                if not token:
                    continue
                scene = token.split('/', 2)[-1]
                scenes.append(_normalize_scene(scene))
    except OSError:
        return tuple()
    return tuple(dict.fromkeys(scenes))


CATEGORY_META = {
    'Home': {'label': 'Home Moments', 'priority': 100},
    'Vacation & Outdoors': {'label': 'Vacation & Outdoors', 'priority': 90},
    'Campus & Learning': {'label': 'Campus & Learning', 'priority': 85},
    'Food & Dining': {'label': 'Food & Dining', 'priority': 75},
    'Work & Public Life': {'label': 'Work & Public Life', 'priority': 70},
    'Travel & Transit': {'label': 'Travel & Transit', 'priority': 68},
    'Leisure & Social': {'label': 'Leisure & Social', 'priority': 64},
    'Shopping & Errands': {'label': 'Shopping & Errands', 'priority': 58},
    'Sports & Fitness': {'label': 'Sports & Fitness', 'priority': 54},
    'Health & Wellness': {'label': 'Health & Wellness', 'priority': 50},
    'Sacred & Heritage': {'label': 'Sacred & Heritage', 'priority': 46},
    'Everyday Places': {'label': 'Everyday Places', 'priority': 10},
}


SCENE_CATEGORY_OVERRIDES = {
    'attic': 'Home',
    'basement': 'Home',
    'bathroom': 'Home',
    'bedchamber': 'Home',
    'bedroom': 'Home',
    'berth': 'Home',
    'alcove': 'Home',
    'apartment building outdoor': 'Home',
    'bow window indoor': 'Home',
    'chalet': 'Home',
    'childs room': 'Home',
    'closet': 'Home',
    'cottage': 'Home',
    'dining room': 'Home',
    'dorm room': 'Home',
    'dressing room': 'Home',
    'garage indoor': 'Home',
    'garage outdoor': 'Home',
    'home office': 'Home',
    'home theater': 'Home',
    'house': 'Home',
    'jacuzzi indoor': 'Home',
    'kitchen': 'Home',
    'laundromat': 'Home',
    'living room': 'Home',
    'nursery': 'Home',
    'pantry': 'Home',
    'playroom': 'Home',
    'porch': 'Home',
    'shower': 'Home',
    'utility room': 'Home',
    'wet bar': 'Home',
    'yard': 'Home',
    'badlands': 'Vacation & Outdoors',
    'aquarium': 'Vacation & Outdoors',
    'bamboo forest': 'Vacation & Outdoors',
    'beach': 'Vacation & Outdoors',
    'beach house': 'Vacation & Outdoors',
    'botanical garden': 'Vacation & Outdoors',
    'butte': 'Vacation & Outdoors',
    'camping': 'Vacation & Outdoors',
    'campsite': 'Vacation & Outdoors',
    'canyon': 'Vacation & Outdoors',
    'cliff': 'Vacation & Outdoors',
    'cabin outdoor': 'Vacation & Outdoors',
    'canal natural': 'Vacation & Outdoors',
    'coast': 'Vacation & Outdoors',
    'corral': 'Vacation & Outdoors',
    'crevasse': 'Vacation & Outdoors',
    'corn field': 'Vacation & Outdoors',
    'creek': 'Vacation & Outdoors',
    'dam': 'Vacation & Outdoors',
    'desert sand': 'Vacation & Outdoors',
    'desert vegetation': 'Vacation & Outdoors',
    'farm': 'Vacation & Outdoors',
    'field cultivated': 'Vacation & Outdoors',
    'field wild': 'Vacation & Outdoors',
    'forest broadleaf': 'Vacation & Outdoors',
    'forest path': 'Vacation & Outdoors',
    'forest road': 'Vacation & Outdoors',
    'formal garden': 'Vacation & Outdoors',
    'fountain': 'Vacation & Outdoors',
    'fishpond': 'Vacation & Outdoors',
    'glacier': 'Vacation & Outdoors',
    'gazebo exterior': 'Vacation & Outdoors',
    'grotto': 'Vacation & Outdoors',
    'harbor': 'Vacation & Outdoors',
    'hayfield': 'Vacation & Outdoors',
    'hot spring': 'Vacation & Outdoors',
    'ice floe': 'Vacation & Outdoors',
    'ice shelf': 'Vacation & Outdoors',
    'iceberg': 'Vacation & Outdoors',
    'islet': 'Vacation & Outdoors',
    'japanese garden': 'Vacation & Outdoors',
    'lagoon': 'Vacation & Outdoors',
    'lake natural': 'Vacation & Outdoors',
    'lawn': 'Vacation & Outdoors',
    'lighthouse': 'Vacation & Outdoors',
    'marsh': 'Vacation & Outdoors',
    'mountain': 'Vacation & Outdoors',
    'mountain path': 'Vacation & Outdoors',
    'mountain snowy': 'Vacation & Outdoors',
    'oast house': 'Vacation & Outdoors',
    'ocean': 'Vacation & Outdoors',
    'orchard': 'Vacation & Outdoors',
    'park': 'Vacation & Outdoors',
    'pasture': 'Vacation & Outdoors',
    'picnic area': 'Vacation & Outdoors',
    'pond': 'Vacation & Outdoors',
    'rainforest': 'Vacation & Outdoors',
    'rice paddy': 'Vacation & Outdoors',
    'river': 'Vacation & Outdoors',
    'rock arch': 'Vacation & Outdoors',
    'roof garden': 'Vacation & Outdoors',
    'sky': 'Vacation & Outdoors',
    'stable': 'Vacation & Outdoors',
    'swamp': 'Vacation & Outdoors',
    'topiary garden': 'Vacation & Outdoors',
    'tundra': 'Vacation & Outdoors',
    'valley': 'Vacation & Outdoors',
    'vegetable garden': 'Vacation & Outdoors',
    'vineyard': 'Vacation & Outdoors',
    'volcano': 'Vacation & Outdoors',
    'waterfall': 'Vacation & Outdoors',
    'wave': 'Vacation & Outdoors',
    'water tower': 'Vacation & Outdoors',
    'wind farm': 'Vacation & Outdoors',
    'windmill': 'Vacation & Outdoors',
    'classroom': 'Campus & Learning',
    'lecture room': 'Campus & Learning',
    'library indoor': 'Campus & Learning',
    'library outdoor': 'Campus & Learning',
    'campus': 'Campus & Learning',
    'kindergarden classroom': 'Campus & Learning',
    'schoolhouse': 'Campus & Learning',
    'chemistry lab': 'Campus & Learning',
    'biology laboratory': 'Campus & Learning',
    'computer room': 'Campus & Learning',
    'archive': 'Campus & Learning',
    'art school': 'Campus & Learning',
    'art studio': 'Campus & Learning',
    'natural history museum': 'Campus & Learning',
    'science museum': 'Campus & Learning',
    'restaurant': 'Food & Dining',
    'restaurant kitchen': 'Food & Dining',
    'restaurant patio': 'Food & Dining',
    'coffee shop': 'Food & Dining',
    'bar': 'Food & Dining',
    'food court': 'Food & Dining',
    'bakery shop': 'Food & Dining',
    'cafeteria': 'Food & Dining',
    'dining hall': 'Food & Dining',
    'pizzeria': 'Food & Dining',
    'sushi bar': 'Food & Dining',
    'fastfood restaurant': 'Food & Dining',
    'delicatessen': 'Food & Dining',
    'diner outdoor': 'Food & Dining',
    'beer garden': 'Food & Dining',
    'beer hall': 'Food & Dining',
    'ice cream parlor': 'Food & Dining',
    'office': 'Work & Public Life',
    'bank vault': 'Work & Public Life',
    'conference room': 'Work & Public Life',
    'conference center': 'Work & Public Life',
    'office cubicles': 'Work & Public Life',
    'office building': 'Work & Public Life',
    'server room': 'Work & Public Life',
    'assembly line': 'Work & Public Life',
    'auto factory': 'Work & Public Life',
    'clean room': 'Work & Public Life',
    'construction site': 'Work & Public Life',
    'courthouse': 'Work & Public Life',
    'embassy': 'Work & Public Life',
    'engine room': 'Work & Public Life',
    'fire station': 'Work & Public Life',
    'industrial area': 'Work & Public Life',
    'legislative chamber': 'Work & Public Life',
    'loading dock': 'Work & Public Life',
    'repair shop': 'Work & Public Life',
    'airport terminal': 'Travel & Transit',
    'alley': 'Travel & Transit',
    'airfield': 'Travel & Transit',
    'airplane cabin': 'Travel & Transit',
    'aqueduct': 'Travel & Transit',
    'boardwalk': 'Travel & Transit',
    'boat deck': 'Travel & Transit',
    'boathouse': 'Travel & Transit',
    'bridge': 'Travel & Transit',
    'bus interior': 'Travel & Transit',
    'bus station indoor': 'Travel & Transit',
    'car interior': 'Travel & Transit',
    'cockpit': 'Travel & Transit',
    'crosswalk': 'Travel & Transit',
    'desert road': 'Travel & Transit',
    'downtown': 'Travel & Transit',
    'field road': 'Travel & Transit',
    'gas station': 'Travel & Transit',
    'hangar indoor': 'Travel & Transit',
    'hangar outdoor': 'Travel & Transit',
    'heliport': 'Travel & Transit',
    'highway': 'Travel & Transit',
    'hotel outdoor': 'Travel & Transit',
    'hotel room': 'Travel & Transit',
    'inn outdoor': 'Travel & Transit',
    'landing deck': 'Travel & Transit',
    'motel': 'Travel & Transit',
    'pier': 'Travel & Transit',
    'promenade': 'Travel & Transit',
    'railroad track': 'Travel & Transit',
    'residential neighborhood': 'Travel & Transit',
    'rope bridge': 'Travel & Transit',
    'runway': 'Travel & Transit',
    'street': 'Travel & Transit',
    'train interior': 'Travel & Transit',
    'train station platform': 'Travel & Transit',
    'viaduct': 'Travel & Transit',
    'village': 'Travel & Transit',
    'youth hostel': 'Travel & Transit',
    'amusement arcade': 'Leisure & Social',
    'arcade': 'Leisure & Social',
    'arena performance': 'Leisure & Social',
    'amusement park': 'Leisure & Social',
    'ball pit': 'Leisure & Social',
    'ballroom': 'Leisure & Social',
    'banquet hall': 'Leisure & Social',
    'bowling alley': 'Leisure & Social',
    'carrousel': 'Leisure & Social',
    'casino': 'Leisure & Social',
    'discotheque': 'Leisure & Social',
    'movie theater indoor': 'Leisure & Social',
    'music studio': 'Leisure & Social',
    'orchestra pit': 'Leisure & Social',
    'playground': 'Leisure & Social',
    'reception': 'Leisure & Social',
    'stage indoor': 'Leisure & Social',
    'stage outdoor': 'Leisure & Social',
    'television room': 'Leisure & Social',
    'television studio': 'Leisure & Social',
    'water park': 'Leisure & Social',
    'auto showroom': 'Shopping & Errands',
    'beauty salon': 'Shopping & Errands',
    'bookstore': 'Shopping & Errands',
    'clothing store': 'Shopping & Errands',
    'department store': 'Shopping & Errands',
    'drugstore': 'Shopping & Errands',
    'fabric store': 'Shopping & Errands',
    'flea market indoor': 'Shopping & Errands',
    'florist shop indoor': 'Shopping & Errands',
    'general store indoor': 'Shopping & Errands',
    'general store outdoor': 'Shopping & Errands',
    'gift shop': 'Shopping & Errands',
    'hardware store': 'Shopping & Errands',
    'jewelry shop': 'Shopping & Errands',
    'market indoor': 'Shopping & Errands',
    'market outdoor': 'Shopping & Errands',
    'bazaar indoor': 'Shopping & Errands',
    'bazaar outdoor': 'Shopping & Errands',
    'pet shop': 'Shopping & Errands',
    'pharmacy': 'Shopping & Errands',
    'shoe shop': 'Shopping & Errands',
    'shopfront': 'Shopping & Errands',
    'toy shop': 'Shopping & Errands',
    'athletic field outdoor': 'Sports & Fitness',
    'arena hockey': 'Sports & Fitness',
    'arena rodeo': 'Sports & Fitness',
    'baseball field': 'Sports & Fitness',
    'basketball court indoor': 'Sports & Fitness',
    'boxing ring': 'Sports & Fitness',
    'football field': 'Sports & Fitness',
    'golf course': 'Sports & Fitness',
    'gymnasium indoor': 'Sports & Fitness',
    'ice skating rink indoor': 'Sports & Fitness',
    'ice skating rink outdoor': 'Sports & Fitness',
    'martial arts gym': 'Sports & Fitness',
    'ski resort': 'Sports & Fitness',
    'ski slope': 'Sports & Fitness',
    'soccer field': 'Sports & Fitness',
    'stadium baseball': 'Sports & Fitness',
    'stadium football': 'Sports & Fitness',
    'stadium soccer': 'Sports & Fitness',
    'swimming pool indoor': 'Sports & Fitness',
    'swimming pool outdoor': 'Sports & Fitness',
    'bullring': 'Sports & Fitness',
    'volleyball court outdoor': 'Sports & Fitness',
    'hospital': 'Health & Wellness',
    'hospital room': 'Health & Wellness',
    'nursing home': 'Health & Wellness',
    'operating room': 'Health & Wellness',
    'veterinarians office': 'Health & Wellness',
    'art gallery': 'Sacred & Heritage',
    'artists loft': 'Sacred & Heritage',
    'amphitheater': 'Sacred & Heritage',
    'arch': 'Sacred & Heritage',
    'archaeological excavation': 'Sacred & Heritage',
    'excavation': 'Sacred & Heritage',
    'burial chamber': 'Sacred & Heritage',
    'castle': 'Sacred & Heritage',
    'catacomb': 'Sacred & Heritage',
    'cemetery': 'Sacred & Heritage',
    'church indoor': 'Sacred & Heritage',
    'church outdoor': 'Sacred & Heritage',
    'kasbah': 'Sacred & Heritage',
    'mausoleum': 'Sacred & Heritage',
    'medina': 'Sacred & Heritage',
    'museum indoor': 'Sacred & Heritage',
    'museum outdoor': 'Sacred & Heritage',
    'mosque outdoor': 'Sacred & Heritage',
    'pagoda': 'Sacred & Heritage',
    'palace': 'Sacred & Heritage',
    'ruin': 'Sacred & Heritage',
    'synagogue outdoor': 'Sacred & Heritage',
    'temple asia': 'Sacred & Heritage',
    'throne room': 'Sacred & Heritage',
    'tower': 'Sacred & Heritage',
}


CATEGORY_KEYWORDS = {
    'Home': (
        'home', 'bed', 'bath', 'kitchen', 'living room', 'dining room',
        'garage', 'attic', 'basement', 'closet', 'pantry', 'nursery',
        'playroom', 'yard', 'porch', 'house', 'cottage', 'chalet',
    ),
    'Vacation & Outdoors': (
        'beach', 'coast', 'mountain', 'forest', 'waterfall', 'park',
        'glacier', 'lagoon', 'lake', 'river', 'garden', 'campsite',
        'picnic', 'valley', 'cliff', 'desert', 'swamp', 'marsh',
        'harbor', 'lighthouse', 'farm', 'barn', 'orchard', 'vineyard',
        'field', 'water tower', 'grotto', 'volcano', 'islet', 'wave',
    ),
    'Campus & Learning': (
        'classroom', 'lecture', 'library', 'campus', 'school', 'lab',
        'laboratory', 'computer room', 'archive', 'museum', 'studio',
        'auditorium',
    ),
    'Food & Dining': (
        'restaurant', 'coffee', 'cafeteria', 'dining', 'bakery', 'bar',
        'food court', 'pizzeria', 'sushi', 'diner', 'pub', 'ice cream',
    ),
    'Work & Public Life': (
        'office', 'conference', 'factory', 'industrial', 'assembly line',
        'construction', 'repair', 'courthouse', 'embassy', 'legislative',
        'server room', 'loading dock', 'army base', 'fire station',
    ),
    'Travel & Transit': (
        'airport', 'airplane', 'airfield', 'runway', 'highway',
        'train station', 'train interior', 'bus station', 'bus interior',
        'car interior', 'cockpit', 'hotel', 'motel', 'hostel', 'street',
        'downtown', 'bridge', 'pier', 'promenade', 'boardwalk', 'railroad',
        'village',
    ),
    'Leisure & Social': (
        'movie theater', 'amusement', 'ballroom', 'bowling', 'discotheque',
        'stage', 'music studio', 'casino', 'playground', 'banquet',
        'reception', 'television', 'water park',
    ),
    'Shopping & Errands': (
        'store', 'shop', 'market', 'mall', 'showroom', 'drugstore',
        'pharmacy', 'beauty salon',
    ),
    'Sports & Fitness': (
        'stadium', 'field', 'court', 'gym', 'golf', 'ski', 'pool',
        'boxing', 'rink', 'soccer', 'football', 'basketball', 'baseball',
        'volleyball', 'athletic',
    ),
    'Health & Wellness': (
        'hospital', 'nursing home', 'operating room', 'veterinarians office',
    ),
    'Sacred & Heritage': (
        'temple', 'church', 'mosque', 'synagogue', 'pagoda', 'cemetery',
        'mausoleum', 'catacomb', 'burial chamber', 'castle', 'palace',
        'ruin', 'art gallery', 'amphitheater', 'kasbah', 'medina',
    ),
}


DISPLAY_SCENE_OVERRIDES = {
    'airport terminal': 'Airport',
    'bathroom': 'Bathroom',
    'beach': 'Beach',
    'bedroom': 'Bedroom',
    'campus': 'Campus',
    'classroom': 'Classroom',
    'coast': 'Coast',
    'conference room': 'Conference Room',
    'desert sand': 'Desert',
    'desert vegetation': 'Desert',
    'forest broadleaf': 'Forest',
    'forest path': 'Forest',
    'forest road': 'Forest',
    'formal garden': 'Garden',
    'glacier': 'Glacier',
    'hospital': 'Hospital',
    'kitchen': 'Kitchen',
    'kindergarden classroom': 'Classroom',
    'lecture room': 'Lecture Room',
    'library indoor': 'Library',
    'library outdoor': 'Library',
    'living room': 'Living Room',
    'movie theater indoor': 'Movie Theater',
    'mountain path': 'Mountain',
    'mountain snowy': 'Mountain',
    'natural history museum': 'Museum',
    'office': 'Office',
    'park': 'Park',
    'runway': 'Runway',
    'swimming pool indoor': 'Swimming Pool',
    'swimming pool outdoor': 'Swimming Pool',
    'temple asia': 'Temple',
    'waterfall': 'Waterfall',
}


DISPLAY_DROP_WORDS = {
    'indoor', 'outdoor', 'public', 'natural', 'urban', 'snowy', 'asia',
    'wild', 'cultivated', 'vegetation', 'sand', 'deep',
}


def _infer_category_from_keywords(scene: str) -> str:
    scores = defaultdict(float)

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in scene:
                scores[category] += 1.0 + (len(keyword.split()) * 0.1)

    if not scores:
        return 'Everyday Places'

    def _score(item):
        category, value = item
        priority = CATEGORY_META[category]['priority']
        return value, priority

    return max(scores.items(), key=_score)[0]


def _build_scene_category_map() -> dict:
    mapping = {scene: _infer_category_from_keywords(scene) for scene in _load_places365_scenes()}
    mapping.update(SCENE_CATEGORY_OVERRIDES)
    return mapping


SCENE_CATEGORY_MAP = _build_scene_category_map()


def _categorize_scene(scene: str) -> str:
    key = _normalize_scene(scene)
    if key in SCENE_CATEGORY_MAP:
        return SCENE_CATEGORY_MAP[key]

    for known_scene, category in SCENE_CATEGORY_MAP.items():
        if key in known_scene or known_scene in key:
            return category

    return _infer_category_from_keywords(key)


def _scene_family(scene: str) -> str:
    key = _normalize_scene(scene)
    if key in DISPLAY_SCENE_OVERRIDES:
        return DISPLAY_SCENE_OVERRIDES[key]

    tokens = [token for token in key.split() if token not in DISPLAY_DROP_WORDS]
    if not tokens:
        return _title_case(key)
    return ' '.join(token.capitalize() for token in tokens)


def _reduce_with_pca(vectors: np.ndarray) -> np.ndarray:
    n_samples, n_features = vectors.shape
    n_components = min(PCA_COMPONENTS, n_samples - 1, n_features)

    if n_components < 2:
        return normalize(vectors, norm='l2')

    pca = PCA(n_components=n_components, random_state=42)
    reduced = pca.fit_transform(vectors)
    return normalize(reduced, norm='l2')


def _time_gap_hours(previous_photo, current_photo) -> float:
    try:
        previous_time = getattr(previous_photo, 'captured_at', None) or previous_photo.uploaded_at
        current_time = getattr(current_photo, 'captured_at', None) or current_photo.uploaded_at
        delta = current_time - previous_time
        return float(delta.total_seconds()) / 3600.0
    except Exception:
        return 0.0


def _split_by_time(items: list) -> list:
    if len(items) < 2:
        return [items]

    segments = []
    current_segment = [items[0]]

    for index, (previous_item, current_item) in enumerate(zip(items, items[1:]), start=1):
        previous_photo = previous_item[0]
        current_photo = current_item[0]
        gap_hours = _time_gap_hours(previous_photo, current_photo)
        remaining_items = len(items) - index

        if (
            gap_hours >= TIME_GAP_HOURS
            and len(current_segment) >= MIN_CLUSTER_SIZE
            and remaining_items >= MIN_CLUSTER_SIZE
        ):
            segments.append(current_segment)
            current_segment = [current_item]
        else:
            current_segment.append(current_item)

    if current_segment:
        segments.append(current_segment)

    return segments


def _clip_subcluster(items: list) -> list:
    if len(items) < 8:
        return [items]

    vectors = np.vstack([vector for _, vector in items])
    reduced = _reduce_with_pca(vectors)

    max_k = min(3, len(items) // 4)
    if max_k < 2:
        return [items]

    best_labels = None
    best_score = -1.0

    for k in range(2, max_k + 1):
        model = KMeans(n_clusters=k, random_state=42, n_init=15)
        labels = model.fit_predict(reduced)
        counts = np.bincount(labels)

        if counts.min() < MIN_CLUSTER_SIZE:
            continue

        try:
            score = float(silhouette_score(reduced, labels, metric='cosine'))
        except Exception:
            continue

        if score > best_score:
            best_score = score
            best_labels = labels

    if best_labels is None or best_score < 0.32:
        return [items]

    grouped = defaultdict(list)
    for item, label in zip(items, best_labels):
        grouped[int(label)].append(item)

    ordered_groups = sorted(
        grouped.values(),
        key=lambda group: (group[0][0].uploaded_at, group[0][0].id),
    )
    return ordered_groups


def _build_album_label(category: str, index: int, total: int) -> str:
    base_label = CATEGORY_META.get(category, {'label': category})['label']
    if total > 1:
        return f'{base_label} {index + 1}'
    return base_label


def _finalize_album(category: str, items: list, index: int, total: int) -> dict:
    photos = [photo for photo, _ in items]
    scene_counts = Counter(_scene_family(photo.scene) for photo in photos)
    dominant_scene = scene_counts.most_common(1)[0][0] if scene_counts else category

    return {
        'photos': photos,
        'label': _build_album_label(category, index, total),
        'dominant_scene': dominant_scene,
    }


def group_photos_into_events(photos: list) -> list:
    valid_rows = []

    for photo in photos:
        vector = None
        try:
            vector = photo.get_clip_embedding()
        except Exception:
            vector = None

        if vector is None:
            continue

        vector = np.asarray(vector, dtype=np.float32)
        if vector.ndim != 1 or vector.size == 0:
            continue

        valid_rows.append((photo, normalize(vector.reshape(1, -1), norm='l2')[0]))

    if not valid_rows:
        return []

    valid_rows.sort(key=lambda item: (item[0].uploaded_at, item[0].id))

    category_buckets = defaultdict(list)
    for photo, vector in valid_rows:
        category = _categorize_scene(photo.scene)
        category_buckets[category].append((photo, vector))

    ordered_categories = sorted(
        category_buckets.items(),
        key=lambda item: (-len(item[1]), -CATEGORY_META.get(item[0], {'priority': 0})['priority'], item[0]),
    )

    results = []
    for category, items in ordered_categories:
        time_segments = _split_by_time(items)
        grouped_segments = []

        for segment in time_segments:
            grouped_segments.extend(_clip_subcluster(segment))

        for index, segment in enumerate(grouped_segments):
            results.append(
                _finalize_album(
                    category=category,
                    items=segment,
                    index=index,
                    total=len(grouped_segments),
                )
            )

    results.sort(
        key=lambda item: (
            -len(item['photos']),
            -CATEGORY_META.get(_categorize_scene(item['dominant_scene']), {'priority': 0})['priority'],
            item['label'],
        )
    )
    return results
