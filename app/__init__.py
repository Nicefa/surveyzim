from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from .config import Config
from flask_mail import Mail
from dotenv import load_dotenv
import os

# Only one instance of each extension
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "main.login"  # route name for login page
mail = Mail()  # Initialize once

# Load environment variables from .env
load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Mail configuration using environment variables
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USE_SSL'] = False
    app.config['MAIL_USERNAME'] = os.environ.get("SURVEYZIM_EMAIL")
    app.config['MAIL_PASSWORD'] = os.environ.get("SURVEYZIM_APP_PASSWORD")

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    Migrate(app, db)
    mail.init_app(app)

    # Import models here AFTER db.init_app to avoid circular imports
    from .models.user import User
    from .models.survey import Survey, Question

    # Register the user_loader inside create_app
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from .routes import bp
    app.register_blueprint(bp)

    # Jinja filter for word count
    def count_words_filter(s):
        if not s:
            return 0
        return len(s.split())
    app.jinja_env.filters['count_words'] = count_words_filter

    return app
