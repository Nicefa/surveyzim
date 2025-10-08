from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .. import db  # import the same db instance from app/__init__.py

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(512))
    
    # Payment & subscription fields
    payment_status = db.Column(db.String(20), default='unpaid')  # student, basic, extended, enterprise
    word_limit = db.Column(db.Integer, default=0)  # set after payment
    plan_name = db.Column(db.String(50), nullable=False, default='Free')

    # New fields for EcoCash integration
    payment_reference = db.Column(db.String(100), nullable=True)  # transaction ref from EcoCash
    pending_package = db.Column(db.String(50), nullable=True)     # package selected before payment confirms

    surveys = db.relationship("Survey", backref="owner", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
