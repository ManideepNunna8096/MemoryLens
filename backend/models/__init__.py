from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

from models.user import User
from models.photo import Photo
from models.event import Event
from models.job import BackgroundJob
