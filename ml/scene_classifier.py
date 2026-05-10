import os
import urllib.request
from time import perf_counter

import torch
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image

from utils.logger import get_logger


ML_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(ML_DIR, 'resnet18_places365.pth.tar')
LABELS_PATH = os.path.join(ML_DIR, 'categories_places365.txt')

MODEL_URL = 'http://places2.csail.mit.edu/models_places365/resnet18_places365.pth.tar'
LABELS_URL = 'https://raw.githubusercontent.com/csailvision/places365/master/categories_places365.txt'

startup_logger = get_logger('STARTUP')
done_logger = get_logger('DONE')
error_logger = get_logger('ERROR')


def _download_if_missing(path, url, label):
    if os.path.exists(path):
        return

    started_at = perf_counter()
    startup_logger.info(f'Downloading {label}...')
    try:
        urllib.request.urlretrieve(url, path)
        done_logger.info(f'{label} downloaded in {perf_counter() - started_at:.2f}s')
    except Exception as error:
        error_logger.error(f'Failed downloading {label}: {error}', exc_info=True)
        raise


TRANSFORM = transforms.Compose(
    [
        transforms.Resize((256, 256)),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ]
)


_model = None
_labels = None


def _load_model():
    global _model, _labels

    if _model is not None:
        return

    started_at = perf_counter()
    startup_logger.info('Loading ResNet18 Places365 model...')
    try:
        _download_if_missing(MODEL_PATH, MODEL_URL, 'ResNet18 Places365 weights')
        _download_if_missing(LABELS_PATH, LABELS_URL, 'Places365 category labels')

        with open(LABELS_PATH, encoding='utf-8') as handle:
            _labels = [line.strip().split(' ')[0][3:] for line in handle.readlines()]

        _model = models.resnet18(num_classes=365)
        checkpoint = torch.load(MODEL_PATH, map_location=torch.device('cpu'))

        state_dict = checkpoint.get('state_dict', checkpoint)
        cleaned = {key.replace('module.', ''): value for key, value in state_dict.items()}
        _model.load_state_dict(cleaned)
        _model.eval()
        done_logger.info(f'ResNet18 Places365 loaded in {perf_counter() - started_at:.2f}s')
    except Exception as error:
        error_logger.error(f'Failed to load ResNet18 Places365 model: {error}', exc_info=True)
        raise


def classify_scene(image_path: str) -> str:
    _load_model()

    image = Image.open(image_path).convert('RGB')
    tensor = TRANSFORM(image).unsqueeze(0)

    with torch.no_grad():
        logits = _model(tensor)
        probabilities = torch.softmax(logits, dim=1)
        top_index = int(torch.argmax(probabilities))

    label = _labels[top_index]
    cleaned = ' '.join(label.replace('_', ' ').replace('/', ' ').split())
    return cleaned.title()
