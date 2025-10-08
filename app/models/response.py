from . import db
from datetime import datetime
import json

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