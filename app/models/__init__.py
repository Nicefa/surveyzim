from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "main.login"

# Import models here so SQLAlchemy knows about them
from . import user, survey, response
