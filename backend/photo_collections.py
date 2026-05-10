from models.photo import Photo


def normalize_collection(value):
    return str(value or 'active').strip().lower()


def apply_photo_collection_filters(query, collection='active'):
    collection = normalize_collection(collection)

    if collection == 'favorites':
        return query.filter(Photo.is_favorite.is_(True), Photo.trashed_at.is_(None))
    if collection == 'archived':
        return query.filter(Photo.is_archived.is_(True), Photo.trashed_at.is_(None))
    if collection == 'trash':
        return query.filter(Photo.trashed_at.is_not(None))
    if collection == 'all':
        return query

    return query.filter(Photo.trashed_at.is_(None))


def photo_collection_query(user_id, collection='active'):
    base_query = Photo.query.filter(Photo.user_id == user_id)
    return apply_photo_collection_filters(base_query, collection)
