# utils.py
import os
import threading
from flask_mail import Message
from flask import current_app, url_for
from . import mail
from itsdangerous import URLSafeTimedSerializer
from typing import Optional

def send_async_email(app, msg):
    """Send email in a separate thread."""
    with app.app_context():
        mail.send(msg)

def send_survey_published_emails(survey, user_email):
    """
    Sends survey published emails:
    - Admin: includes survey link
    - User: notification only, no link
    Both emails include the logo inline.
    """
    app = current_app._get_current_object()
    sender_email = os.environ.get("SURVEYZIM_EMAIL")
    admin_email = sender_email  # admin is the same as sender

    # Plan mapping
    distribution_days_map = {
        'student': 10,
        'basic': 14,
        'extended': 30,
        'enterprise': 60
    }
    max_responses_map = {
        'student': 50,
        'basic': 100,
        'extended': 500,
        'enterprise': 1000
    }

    # 🔹 Use survey creation record instead of current owner payment_status
    plan_key = survey.created_with_package.lower() if survey.created_with_package else 'student'
    plan_name = plan_key.capitalize()
    word_limit = survey.created_with_word_limit or 500
    distribution_days = distribution_days_map.get(plan_key, 0)
    max_responses = max_responses_map.get(plan_key, 0)

    owner = survey.owner  # optional, for username in user email

    # Path to logo
    logo_path = os.path.join(current_app.root_path, 'static', 'images', 'logo.jpg')
    with open(logo_path, 'rb') as f:
        logo_data = f.read()

    # --- Admin Email ---
    admin_subject = f"New Survey Published: {survey.title}"
    admin_body = f"""
    <p>Hello Analytics Team,</p>
    <p>The survey <strong>{survey.title}</strong> has been published by {user_email}.</p>
    <p><strong>Survey Details:</strong></p>
    <ul>
        <li>Selected Plan: {plan_name}</li>
        <li>Maximum Words Allowed: {word_limit}</li>
        <li>Distribution Days: {distribution_days}</li>
        <li>Maximum Responses: {max_responses}</li>
    </ul>
    <p>Survey link: <a href="{survey.survey_url}">{survey.survey_url}</a></p>
    <img src="cid:logo_image">
    """
    admin_msg = Message(subject=admin_subject, recipients=[admin_email], html=admin_body, sender=sender_email)
    admin_msg.attach(filename='logo.jpg', content_type='image/jpeg', data=logo_data, disposition='inline', headers={'Content-ID': '<logo_image>'})

    # --- User Email ---
    user_subject = f"Your Survey '{survey.title}' is Live on SurveyZim!"
    user_body = f"""
    <p>Hello {owner.username if owner else 'Valued User'},</p>
    <p>Great news! Your survey <strong>{survey.title}</strong> has just gone live on SurveyZim.</p>
    <p><strong>Plan Details:</strong> {plan_name} plan – valid for {distribution_days} days of distribution and up to {max_responses} responses.</p>
    <p>You can expect your survey responses in CSV format to be available shortly after the survey period ends.</p>
    <p>Remember to visit your SurveyZim dashboard to download your CSV and track responses in real-time.</p>
    <p>Thank you for trusting SurveyZim to reach your audience effectively!</p>
    <img src="cid:logo_image">
    """
    user_msg = Message(subject=user_subject, recipients=[user_email], html=user_body, sender=sender_email)
    user_msg.attach(filename='logo.jpg', content_type='image/jpeg', data=logo_data, disposition='inline', headers={'Content-ID': '<logo_image>'})

    # --- Send asynchronously ---
    threading.Thread(target=send_async_email, args=(app, admin_msg)).start()
    threading.Thread(target=send_async_email, args=(app, user_msg)).start()

def send_welcome_user_email(user):
    """
    Sends a welcome email to a newly registered user with a brief marketing tone,
    mentioning services, packages, and ethical considerations.
    """
    app = current_app._get_current_object()
    sender_email = os.environ.get("SURVEYZIM_EMAIL")
    
    # Path to logo
    logo_path = os.path.join(current_app.root_path, 'static', 'images', 'logo.jpg')
    with open(logo_path, 'rb') as f:
        logo_data = f.read()
    
    subject = "Welcome to SurveyZim – Your Survey Platform!"
    
    html_body = f"""
    <p>Hi {user.username},</p>
    <p>Welcome to <strong>SurveyZim</strong>! 🎉 We're thrilled to have you on board.</p>
    
    <p>SurveyZim helps you <strong>create, distribute, and analyze surveys</strong> effortlessly. 
    Here's what we offer:</p>
    <ul>
        <li>Custom surveys with multiple question types for varied data types</li>
        <li>Instant response analytics</li>
        <li>Secure and ethical data collection</li>
        <li>Easy sharing and distribution via email or links</li>
    </ul>
    
    <p><strong>Our Packages:</strong></p>
    <ul>
        <li><strong>Student:</strong> Small surveys, limited responses, For students (dissertations, academic research)</li>
        <li><strong>Basic Plan:</strong> Full analytics, larger response limits, For small orgs, NGOs, solo researchers</li>
        <li><strong>Extended Plan:</strong> More responses, longer distribution, For medium to large organizations</li> 
        <li><strong>Enterprise:</strong> For corporates, research firms, development partners</li>  
    </ul>
    
    <p>We adhere to strict <strong>ethical guidelines</strong> to ensure your survey responses are safe, secure, and responsibly handled.</p>
    
    <p>Get started by visiting your <a href="{url_for('main.dashboard', _external=True)}">SurveyZim Dashboard</a>.</p>
    
    <p>Cheers,<br><strong>The SurveyZim Team</strong></p>
    <img src="cid:logo_image">
    """
    
    msg = Message(subject=subject, recipients=[user.email], html=html_body, sender=sender_email)
    msg.attach(filename='logo.jpg', content_type='image/jpeg', data=logo_data,
               disposition='inline', headers={'Content-ID': '<logo_image>'})
    
    threading.Thread(target=send_async_email, args=(app, msg)).start()

# --- Token generation and verification ---
def generate_password_reset_token(email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='password-reset-salt')

def verify_password_reset_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=expiration)
    except Exception:
        return None
    return email

def send_forgot_password_email(user_email):
    """Send forgot password email with secure reset link."""
    app = current_app._get_current_object()
    sender_email = current_app.config.get('MAIL_USERNAME')

    # Generate token
    token = generate_password_reset_token(user_email)
    reset_link = url_for('main.reset_password', token=token, _external=True)

    subject = "SurveyZim - Reset Your Password"
    html_body = f"""
    <p>Hello,</p>
    <p>You requested a password reset for your SurveyZim account.</p>
    <p>Click the link below to set a new password (valid for 1 hour):</p>
    <p><a href="{reset_link}">{reset_link}</a></p>
    <p>If you did not request this, please ignore this email.</p>
    <p>Thank you,<br>SurveyZim Team</p>
    """

    msg = Message(subject=subject, recipients=[user_email], html=html_body, sender=sender_email)
    threading.Thread(target=send_async_email, args=(app, msg)).start()
