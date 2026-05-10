import logging
from datetime import datetime


class PipelineFormatter(logging.Formatter):
    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        tag = getattr(record, 'tag', None) or 'APP'
        message = record.getMessage()
        rendered = f'[{timestamp}] [{record.levelname}] [{tag}] {message}'

        if record.exc_info:
            rendered = f'{rendered}\n{self.formatException(record.exc_info)}'

        return rendered


_HANDLER = None


def _shared_handler():
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = logging.StreamHandler()
        _HANDLER.setFormatter(PipelineFormatter())
    return _HANDLER


def configure_pipeline_logging(level='INFO'):
    logger = logging.getLogger('memorylens')
    logger.handlers.clear()
    logger.addHandler(_shared_handler())
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    return _shared_handler()


def get_logger(tag='APP'):
    logger = logging.getLogger('memorylens')
    if not logger.handlers:
        configure_pipeline_logging()
    return logging.LoggerAdapter(logger, {'tag': tag})
