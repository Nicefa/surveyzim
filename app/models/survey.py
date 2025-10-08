from datetime import datetime
import json
from slugify import slugify
from .. import db  # import the same db instance from app/__init__.py

class Survey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_with_package = db.Column(db.String(20))  # Store the package used during creation
    created_with_word_limit = db.Column(db.Integer)   # Store the word limit used during creation
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    word_count = db.Column(db.Integer, default=0)  # Total words in survey
    published = db.Column(db.Boolean, default=False)  # Whether the survey is published
    published_at = db.Column(db.DateTime)
    survey_url = db.Column(db.String(500))  
    response_count = db.Column(db.Integer, default=0)
    distribution_days = db.Column(db.Integer, default=0)  # How many days the survey is distributed
    max_responses = db.Column(db.Integer, default=0)      # Max allowed responses
    logo_filename = db.Column(db.String(255))

    questions = db.relationship("Question", backref="survey", lazy=True, cascade="all, delete-orphan")
    responses = db.relationship("SurveyResponse", backref="survey_responses", lazy=True)
    
    def generate_slug(self):
        """Generate a unique slug based on the survey title"""
        base_slug = slugify(self.title)
        slug = base_slug
        counter = 1
        while Survey.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1
        self.slug = slug

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    qtype = db.Column(db.String(50), nullable=False)  # short, paragraph, multiple_choice, checkbox, dropdown, linear_scale
    survey_id = db.Column(db.Integer, db.ForeignKey("survey.id"))
    word_count = db.Column(db.Integer, default=0)  # Word count of the question
    required = db.Column(db.Boolean, default=False)
    
    # Linear scale specific fields
    linear_scale_low = db.Column(db.Integer, default=1)
    linear_scale_high = db.Column(db.Integer, default=5)
    linear_scale_low_label = db.Column(db.String(200), default='')
    linear_scale_high_label = db.Column(db.String(200), default='')
    
    options = db.relationship('QuestionOption', backref='question', lazy='joined', cascade='all, delete-orphan')

class QuestionOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(200), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"))

class SurveyResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    respondent_ip = db.Column(db.String(50))
    respondent_info = db.Column(db.Text)  # Could store browser, location, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responses = db.Column(db.Text)  # Store responses as JSON string
    
    # Relationship to survey
    survey = db.relationship('Survey', backref=db.backref('survey_responses', lazy=True))
    
    def set_responses(self, responses_dict):
        """Convert responses dictionary to JSON string for storage"""
        self.responses = json.dumps(responses_dict)
    
    def get_responses(self):
        """Convert JSON string back to dictionary"""
        return json.loads(self.responses) if self.responses else {}    
    
    