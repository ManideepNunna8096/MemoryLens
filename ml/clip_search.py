import clip
import numpy as np
import torch
from PIL import Image
from time import perf_counter

from utils.logger import get_logger


_clip_model = None
_clip_preprocess = None
_device = 'cpu'

startup_logger = get_logger('STARTUP')
done_logger = get_logger('DONE')
error_logger = get_logger('ERROR')


def _load_clip():
    global _clip_model, _clip_preprocess

    if _clip_model is not None:
        return

    started_at = perf_counter()
    startup_logger.info('Loading CLIP model...')
    try:
        _clip_model, _clip_preprocess = clip.load('ViT-B/32', device=_device)
        _clip_model.eval()
        done_logger.info(f'CLIP loaded in {perf_counter() - started_at:.2f}s')
    except Exception as error:
        error_logger.error(f'Failed to load CLIP model: {error}', exc_info=True)
        raise


def get_clip_embedding(image_path: str) -> np.ndarray:
    _load_clip()
    image = Image.open(image_path).convert('RGB')
    tensor = _clip_preprocess(image).unsqueeze(0).to(_device)

    with torch.no_grad():
        features = _clip_model.encode_image(tensor)
        features /= features.norm(dim=-1, keepdim=True)

    return features.cpu().numpy()[0]


def get_text_embedding(text: str) -> np.ndarray:
    _load_clip()
    prompts = [
        text,
        f'a photo of {text}',
        f'an image of {text}',
        f'a picture showing {text}',
    ]
    tokens = clip.tokenize(prompts).to(_device)

    with torch.no_grad():
        features = _clip_model.encode_text(tokens)
        features /= features.norm(dim=-1, keepdim=True)
        features = features.mean(dim=0, keepdim=True)
        features /= features.norm(dim=-1, keepdim=True)

    return features.cpu().numpy()[0]
