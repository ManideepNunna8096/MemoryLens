import hashlib

from PIL import Image, ImageOps


DHASH_SIZE = 8
SIMILAR_DHASH_THRESHOLD = 4
_RESAMPLE = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS')


def compute_sha256(filepath):
    digest = hashlib.sha256()
    with open(filepath, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_dhash(filepath, hash_size=DHASH_SIZE):
    with Image.open(filepath) as image:
        normalized = ImageOps.exif_transpose(image).convert('L').resize((hash_size + 1, hash_size), _RESAMPLE)
        pixels = list(normalized.tobytes())

    value = 0
    width = hash_size + 1
    for row in range(hash_size):
        row_offset = row * width
        for col in range(hash_size):
            left_pixel = pixels[row_offset + col]
            right_pixel = pixels[row_offset + col + 1]
            value = (value << 1) | int(left_pixel > right_pixel)

    return f'{value:0{(hash_size * hash_size) // 4}x}'


def compute_duplicate_signatures(filepath):
    return compute_sha256(filepath), compute_dhash(filepath)


def dhash_distance(hash_a, hash_b):
    if not hash_a or not hash_b:
        return None
    return (int(str(hash_a), 16) ^ int(str(hash_b), 16)).bit_count()


def dhash_confidence(distance):
    if distance is None:
        return 0
    return max(50, min(100, round(100 - (distance * 10))))
