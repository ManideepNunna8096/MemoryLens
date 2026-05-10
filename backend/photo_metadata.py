from datetime import datetime

from PIL import Image, ExifTags


DATETIME_TAGS = ('DateTimeOriginal', 'DateTimeDigitized', 'DateTime')


def _parse_exif_datetime(raw_value):
    if not raw_value:
        return None

    for fmt in ('%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(str(raw_value), fmt)
        except ValueError:
            continue

    return None

def extract_photo_metadata(image_path):
    metadata = {'captured_at': None}

    try:
        with Image.open(image_path) as image:
            exif = image.getexif()
            if not exif:
                return metadata

            named_exif = {
                ExifTags.TAGS.get(tag_id, tag_id): value
                for tag_id, value in exif.items()
            }
    except Exception:
        return metadata

    for tag_name in DATETIME_TAGS:
        captured_at = _parse_exif_datetime(named_exif.get(tag_name))
        if captured_at:
            metadata['captured_at'] = captured_at
            break

    return metadata
