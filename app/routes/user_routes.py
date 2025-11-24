from flask import render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_user, logout_user, login_required, current_user
from . import bp  # blueprint variable
from .. import db
from ..models.user import User
from ..models.survey import Survey, Question, QuestionOption, SurveyResponse
from ..forms import RegisterForm, LoginForm, SurveyForm, QuestionForm, ForgotPasswordForm, ResetPasswordForm
from datetime import datetime, timedelta
import json
import csv
from io import StringIO
from ..utils import send_survey_published_emails, send_forgot_password_email, send_welcome_user_email, verify_password_reset_token
from sqlalchemy.orm import joinedload
from typing import Optional
import os
from werkzeug.utils import secure_filename
from flask import current_app

# --- NEW: WORD COUNT TIERS ---
# Defines the number of days a survey is active based on word count.
# Tiers are (words <= tier_key): days
DISTRIBUTION_TIERS = {
    500: 7,      # 0-500 words = 7 days
    1000: 14,     # 501-1000 words = 14 days
    2000: 30,     # 1001-2000 words = 30 days
    float('inf'): 60 # 2001+ words = 60 days
}

def get_distribution_days(word_count):
    """Calculates distribution days based on word count."""
    for tier, days in DISTRIBUTION_TIERS.items():
        if word_count <= tier:
            return days
    return 7 # Default fallback

def count_words(text):
    """Helper function to count words."""
    if not text or not text.strip(): return 0
    return len(text.strip().split())

def recalculate_survey_word_count(survey_id):
    """Finds a survey and updates its total word count."""
    survey = Survey.query.get(survey_id)
    if survey:
        survey.word_count = survey.get_total_word_count()
        db.session.commit()
# --- END NEW ---

# -----------------------------
# Home Page
# -----------------------------
@bp.route("/")
def index():
    return render_template("index.html")

# -----------------------------
# Register
# -----------------------------
@bp.route("/register", methods=["GET","POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = RegisterForm()
    if form.validate_on_submit():
        existing_user = User.query.filter(
            (User.email == form.email.data) | (User.username == form.username.data)
        ).first()

        if existing_user:
            flash("User with that email or username already exists.")
            return render_template("register.html", form=form)

        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Account created successfully!")

        # --- Send welcome email asynchronously ---#
        # send_welcome_user_email(user) # Commented out due to SMTP errors
        pass # Placeholder

        return redirect(url_for("main.dashboard"))

    return render_template("register.html", form=form)


# -----------------------------
# Login
# -----------------------------
@bp.route("/login", methods=["GET","POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    if request.method == "POST":
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data).first()
            if user and user.check_password(form.password.data):
                login_user(user)

                next_page = request.args.get("next")
                if not next_page or not next_page.startswith("/"):
                    next_page = url_for("main.dashboard")
                return redirect(next_page)
            else:
                flash("Invalid email or password.", "danger")
        else:
            print("Form validation errors:", form.errors)

    return render_template("login.html", form=form)

# -----------------------------
# Logout
# -----------------------------
@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for("main.index"))


# -----------------------------
# Dashboard
# -----------------------------
@bp.route("/dashboard")
@login_required
def dashboard():
    surveys = Survey.query.filter_by(user_id=current_user.id).order_by(Survey.created_at.desc()).all()
    total_responses = sum(survey.response_count or 0 for survey in surveys)
    
    # --- Survey Limit Check ---
    survey_count = len(surveys)
    SURVEY_LIMIT = 5
    at_limit = survey_count >= SURVEY_LIMIT
    # --- End Check ---
    
    return render_template(
        "dashboard.html", 
        surveys=surveys, 
        total_responses=total_responses,
        at_limit=at_limit,
        survey_count=survey_count,
        SURVEY_LIMIT=SURVEY_LIMIT
    )

# -----------------------------
# Create Survey
# -----------------------------
@bp.route("/create_survey", methods=["GET","POST"])
@login_required
def create_survey():
    # --- SURVEY LIMIT CHECK ---
    survey_count = Survey.query.filter_by(user_id=current_user.id).count()
    SURVEY_LIMIT = 5 
    if survey_count >= SURVEY_LIMIT:
        flash(f"You have reached the free limit of {SURVEY_LIMIT} surveys. Paid plans for more surveys are coming soon!", "info")
        return redirect(url_for('main.dashboard'))
    # --- END OF CHECK ---

    form = SurveyForm()

    if form.validate_on_submit():
        
        # --- MODIFIED: Only count title and description ---
        title_words = count_words(form.title.data)
        desc_words = count_words(form.description.data)
        total_word_count = title_words + desc_words
        # --- END ---
        
        survey = Survey(
            title=form.title.data,
            description=form.description.data,
            user_id=current_user.id,
            word_count=0 # Set initial word count
        )
        survey.generate_slug() 
        db.session.add(survey)
        db.session.commit()  # commit first to get survey.id

        if 'logo' in request.files:
            logo_file = request.files['logo']
            if logo_file and logo_file.filename != '':
                filename = secure_filename(logo_file.filename)
                unique_filename = f"{current_user.id}_{survey.id}_{int(datetime.utcnow().timestamp())}_{filename}"
                logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', unique_filename)
                
                os.makedirs(os.path.dirname(logo_path), exist_ok=True)
                logo_file.save(logo_path)
                survey.logo_filename = unique_filename
                db.session.commit()

        # --- MODIFIED: All question-adding logic is REMOVED from this route ---

        flash("Survey created successfully! You can now add questions.")
        # --- MODIFIED: Redirect to survey_view to start building ---
        return redirect(url_for("main.survey_view", survey_id=survey.id))

    # Form is rendered on GET request
    return render_template("survey_builder.html", form=form)


@bp.route("/survey/<int:survey_id>/upload_logo", methods=["POST"])
@login_required
def upload_survey_logo(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    
    if survey.user_id != current_user.id:
        flash("You don't have permission to edit this survey.")
        return redirect(url_for("main.dashboard"))
    
    if 'logo' not in request.files:
        flash('No file selected.')
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    logo_file = request.files['logo']
    
    if logo_file.filename == '':
        flash('No file selected.')
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    if logo_file:
        if survey.logo_filename:
            old_logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', survey.logo_filename)
            if os.path.exists(old_logo_path):
                os.remove(old_logo_path)
        
        filename = secure_filename(logo_file.filename)
        unique_filename = f"{current_user.id}_{survey.id}_{int(datetime.utcnow().timestamp())}_{filename}"
        logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', unique_filename)
        
        os.makedirs(os.path.dirname(logo_path), exist_ok=True)
        logo_file.save(logo_path)
        
        survey.logo_filename = unique_filename
        db.session.commit()
        
        flash('Logo uploaded successfully!')
    
    return redirect(url_for("main.survey_view", survey_id=survey.id))

@bp.route("/survey/<int:survey_id>/remove_logo", methods=["POST"])
@login_required
def remove_survey_logo(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    
    if survey.user_id != current_user.id:
        flash("You don't have permission to edit this survey.")
        return redirect(url_for("main.dashboard"))
    
    if survey.logo_filename:
        logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', survey.logo_filename)
        if os.path.exists(logo_path):
            os.remove(logo_path)
        
        survey.logo_filename = None
        db.session.commit()
        flash('Logo removed successfully!')
    
    return redirect(url_for("main.survey_view", survey_id=survey.id))

# -----------------------------
# Survey View (Add/Manage Questions)
# -----------------------------
@bp.route("/survey/<int:survey_id>", methods=["GET", "POST"])
@login_required
def survey_view(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    if survey.user_id != current_user.id:
        flash("You don't have permission to access this survey.")
        return redirect(url_for("main.dashboard"))

    form = QuestionForm()

    if request.method == "POST":
        question_texts = request.form.getlist("question_text[]")
        question_types = request.form.getlist("question_type[]")
        question_required_list = request.form.getlist("question_required[]")
        
        # NEW: Get linear scale data using consistent naming
        linear_scale_lows = request.form.getlist("linear_scale_low[]")
        linear_scale_highs = request.form.getlist("linear_scale_high[]")
        linear_scale_low_labels = request.form.getlist("linear_scale_low_label[]")
        linear_scale_high_labels = request.form.getlist("linear_scale_high_label[]")

        for i, q_text in enumerate(question_texts):
            if not q_text or not q_text.strip():
                continue

            q_type = question_types[i]
            q_word_count = count_words(q_text)
            is_required = question_required_list[i] == 'true' if i < len(question_required_list) else False

            question = Question(
                text=q_text.strip(),
                qtype=q_type,
                survey_id=survey.id,
                word_count=q_word_count,
                required=is_required
            )

            # FIXED: Handle linear scale with consistent indexing
            if q_type == "linear_scale":
                # Use the same index for all linear scale fields
                low_val = linear_scale_lows[i] if i < len(linear_scale_lows) else 1
                high_val = linear_scale_highs[i] if i < len(linear_scale_highs) else 5
                low_label = linear_scale_low_labels[i] if i < len(linear_scale_low_labels) else ""
                high_label = linear_scale_high_labels[i] if i < len(linear_scale_high_labels) else ""
                
                question.linear_scale_low = int(low_val)
                question.linear_scale_high = int(high_val)
                question.linear_scale_low_label = low_label
                question.linear_scale_high_label = high_label

            db.session.add(question)
            db.session.flush()
            
            if q_type in ["multiple_choice", "checkbox", "dropdown"]:
                option_names = request.form.getlist(f"options[{i}][]")
                print(f"DEBUG: Found {len(option_names)} options for question {i}: {option_names}")
                
                for opt_text in option_names:
                    if opt_text.strip():
                        option = QuestionOption(
                            text=opt_text.strip(),
                            question_id=question.id
                        )
                        db.session.add(option)
        
        db.session.commit()
        recalculate_survey_word_count(survey.id)
        flash("Questions added successfully!")
        return redirect(url_for("main.survey_view", survey_id=survey.id))

    # --- GET Request Logic ---
    questions = Question.query.options(joinedload(Question.options))\
               .filter_by(survey_id=survey.id)\
               .order_by(Question.id).all()
    
    # --- NEW WORD COUNT & TIER LOGIC ---
    total_word_count = survey.get_total_word_count()
    distribution_days = get_distribution_days(total_word_count)
    # --- END NEW ---
    
      # Calculate expiration date for display
    expiration_date = None
    if survey.published and survey.published_at and survey.distribution_days:
        expiration_date = survey.published_at + timedelta(days=survey.distribution_days)

    # Check if distribution is over
    distribution_over = False
    if survey.published and survey.published_at and survey.distribution_days:
        end_date = survey.published_at + timedelta(days=survey.distribution_days)
        distribution_over = datetime.utcnow() > end_date

    return render_template(
        "survey_view.html",
        survey=survey,
        form=form,
        questions=questions,
        distribution_over=distribution_over,
        total_word_count=total_word_count,
        distribution_days=distribution_days,
        expiration_date=expiration_date,
        count_words=count_words,
        timedelta=timedelta 
    )

@bp.route("/debug/questions/<int:survey_id>")
@login_required
def debug_questions(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    if survey.user_id != current_user.id:
        return jsonify({"error": "Access denied"}), 403
    
    questions = Question.query.options(joinedload(Question.options)).filter_by(survey_id=survey.id).all()
    
    debug_info = {
        'survey_id': survey.id,
        'survey_title': survey.title,
        'questions_count': len(questions),
        'questions': []
    }
    
    for q in questions:
        question_info = {
            'question_id': q.id,
            'text': q.text,
            'type': q.qtype,
            'options_count': len(q.options),
            'options': [{'id': opt.id, 'text': opt.text} for opt in q.options]
        }
        debug_info['questions'].append(question_info)
    
    return jsonify(debug_info)

# -----------------------------
# Update Question
# -----------------------------
@bp.route("/question/<int:question_id>/update", methods=["POST"])
@login_required
def update_question(question_id):
    question = Question.query.get_or_404(question_id)
    survey = question.survey
    
    if survey.user_id != current_user.id:
        flash("You don't have permission to edit this question.")
        return redirect(url_for("main.dashboard"))
    
    if survey.published:
        flash("Cannot edit questions after survey is published.")
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    try:
        question_text = request.form.get('question_text', '').strip()
        question_type = request.form.get('question_type', 'short')
        question_required = request.form.get('question_required') == 'true'
        
        if not question_text:
            flash("Question text cannot be empty.")
            return redirect(url_for("main.survey_view", survey_id=survey.id))
        
        question.word_count = count_words(question_text)
        question.text = question_text
        question.qtype = question_type
        question.required = question_required
        
        if question_type == "linear_scale":
            question.linear_scale_low = int(request.form.get('linear_scale_low', 1))
            question.linear_scale_high = int(request.form.get('linear_scale_high', 5))
            question.linear_scale_low_label = request.form.get('linear_scale_low_label', '')
            question.linear_scale_high_label = request.form.get('linear_scale_high_label', '')
        else:
            question.linear_scale_low = 1
            question.linear_scale_high = 5
            question.linear_scale_low_label = ''
            question.linear_scale_high_label = ''
        
        if question_type in ["multiple_choice", "checkbox", "dropdown"]:
            option_texts = request.form.getlist('options[]')
            valid_options = [opt.strip() for opt in option_texts if opt.strip()]
            
            if not valid_options:
                flash("Multiple choice, checkbox, and dropdown questions must have at least one option.")
                return redirect(url_for("main.survey_view", survey_id=survey.id))
            
            QuestionOption.query.filter_by(question_id=question.id).delete()
            
            for opt_text in valid_options:
                option = QuestionOption(
                    text=opt_text,
                    question_id=question.id
                )
                db.session.add(option)
        else:
            QuestionOption.query.filter_by(question_id=question.id).delete()
        
        db.session.commit()
        
        recalculate_survey_word_count(survey.id)
        
        flash("Question updated successfully!")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating question: {str(e)}")
        print(f"Error updating question: {str(e)}")
    
    return redirect(url_for("main.survey_view", survey_id=survey.id))

# -----------------------------
# Get Question Data (AJAX)
# -----------------------------
@bp.route("/question/<int:question_id>/json")
@login_required
def get_question_json(question_id):
    question = Question.query.get_or_404(question_id)
    
    if question.survey.user_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    question_data = {
        'id': question.id,
        'text': question.text,
        'qtype': question.qtype,
        'required': question.required,
        'word_count': question.word_count,
        'options': [{'id': opt.id, 'text': opt.text} for opt in question.options],
        'linear_scale_low': question.linear_scale_low,
        'linear_scale_high': question.linear_scale_high,
        'linear_scale_low_label': question.linear_scale_low_label,
        'linear_scale_high_label': question.linear_scale_high_label,
    }
    
    return jsonify(question_data)
# -----------------------------
# Delete Question
# -----------------------------
@bp.route("/question/<int:question_id>/delete", methods=["POST"])
@login_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    survey_id = question.survey_id
    survey = Survey.query.get(survey_id)
    
    if question.survey.user_id != current_user.id:
        flash("You don't have permission to delete this question.")
        return redirect(url_for("main.dashboard"))
    
    if survey.published:
        flash("Cannot delete questions from a published survey.")
        return redirect(url_for("main.survey_view", survey_id=survey_id))

    db.session.delete(question)
    db.session.commit()
    
    recalculate_survey_word_count(survey_id)
    
    flash("Question deleted successfully!")
    return redirect(url_for("main.survey_view", survey_id=survey_id))

# -----------------------------
# Delete Survey (Commented out)
# -----------------------------
# @bp.route("/survey/<int:survey_id>/delete", methods=["POST"])
# @login_required
# def delete_survey(survey_id):
# ... (rest of the function is fine) ...

# -----------------------------
# Preview Survey
# -----------------------------
@bp.route('/preview_survey/<int:survey_id>')
@login_required
def preview_survey(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    
    if survey.user_id != current_user.id:
        flash("You do not have permission to preview this survey.")
        return redirect(url_for('main.dashboard'))
        
    questions = Question.query.options(joinedload(Question.options))\
               .filter_by(survey_id=survey.id)\
               .order_by(Question.id).all()
    
    preview = True
    
    for q in questions:
        if q.qtype == 'linear_scale':
            print(f"Preview - Question: {q.text}")
            print(f"Preview - Linear Scale: {q.linear_scale_low} to {q.linear_scale_high} (Low: '{q.linear_scale_low_label}', High: '{q.linear_scale_high_label}')")
        else:
            print(f"Preview - Question: {q.text}")
            print(f"Preview - Options: {[o.text for o in q.options]}")
    
    return render_template('take_survey.html', survey=survey, questions=questions, preview=preview)
# -----------------------------
# Publish Survey
# -----------------------------
@bp.route("/survey/<int:survey_id>/publish", methods=["POST"])
@login_required
def publish_survey(survey_id):
    
    survey = Survey.query.get_or_404(survey_id)
    
    if not survey.slug:
        survey.generate_slug()
    
    survey_url = url_for("main.take_survey", slug=survey.slug, _external=True)
    
    if survey.user_id != current_user.id:
        flash("You don't have permission to publish this survey.")
        return redirect(url_for("main.dashboard"))
    
    if len(survey.questions) == 0:
        flash("Survey must have at least one question before publishing.")
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    # --- NEW: CALCULATE AND SET TIERS ---
    final_word_count = survey.get_total_word_count()
    distribution_days = get_distribution_days(final_word_count)
    
    survey.word_count = final_word_count
    survey.distribution_days = distribution_days
    # --- END NEW ---
    
    survey.published = True
    survey.published_at = datetime.utcnow()
    survey.survey_url = survey_url
    db.session.commit()
    
    # Send emails asynchronously
    # send_survey_published_emails(survey, current_user.email) # Commented out due to SMTP errors
    pass # Placeholder
    
    flash(f"Survey published! Based on its word count, it will be active for {distribution_days} days. Share this link: {survey_url}")
    return redirect(url_for("main.survey_view", survey_id=survey.id))

# -----------------------------
# Take Survey (For Respondents)
# -----------------------------
@bp.route("/survey/<string:slug>/take")
def take_survey(slug):
    survey = Survey.query.filter_by(slug=slug).first_or_404()

    if not survey.published:
        flash("This survey is not available.")
        return redirect(url_for("main.index"))
        
    # --- NEW: CHECK EXPIRATION ---
    if survey.published_at and survey.distribution_days:
        end_date = survey.published_at + timedelta(days=survey.distribution_days)
        if datetime.utcnow() > end_date:
            flash("This survey is no longer active and is not accepting responses.")
            return redirect(url_for("main.index"))
    # --- END NEW ---

    questions = Question.query.options(joinedload(Question.options))\
               .filter_by(survey_id=survey.id)\
               .order_by(Question.id).all()
    
    print(f"Survey: {survey.title}")
    print(f"Questions count: {len(questions)}")
    for i, q in enumerate(questions):
        print(f"Question {i+1}: {q.text}, Type: {q.qtype}")
        print(f"Options count: {len(q.options)}")
        for opt in q.options:
            print(f"  - Option: {opt.text}")

    return render_template("take_survey.html", survey=survey, questions=questions)

# -----------------------------
# Submit Survey Response
# -----------------------------
@bp.route("/survey/<int:survey_id>/submit", methods=["POST"])
def submit_survey_response(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    
    if not survey.published:
        flash("This survey is not available.")
        return redirect(url_for("main.index"))
        
    # --- NEW: CHECK EXPIRATION ---
    if survey.published_at and survey.distribution_days:
        expiration_date = survey.published_at + timedelta(days=survey.distribution_days)
        if datetime.utcnow() > expiration_date:
            flash("This survey is no longer active and is not accepting responses.")
            return redirect(url_for("main.index"))
    # --- END NEW ---
    
    responses = {}
    for question in survey.questions:
        response_value = None # Default
        if question.qtype in ["multiple_choice", "dropdown", "linear_scale"]:
            response_value = request.form.get(f"question_{question.id}")
        elif question.qtype == "checkbox":
            response_value = request.form.getlist(f"question_{question.id}[]")
        else:  # short, paragraph
            response_value = request.form.get(f"question_{question.id}")
            
        responses[question.id] = {
            "question_text": question.text,
            "question_type": question.qtype,
            "response": response_value
        }
    
    try:
        survey_response = SurveyResponse(
            survey_id=survey.id,
            respondent_ip=request.remote_addr,
            respondent_info=request.headers.get('User-Agent', 'Unknown')
        )
        survey_response.set_responses(responses)
        
        db.session.add(survey_response)
        
        survey.response_count = SurveyResponse.query.filter_by(survey_id=survey.id).count()
        
        db.session.commit()
        
        flash("Thank you for completing the survey!")
        return redirect(url_for("main.thank_you"))
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while submitting your response. Please try again.")
        return redirect(url_for("main.take_survey", slug=survey.slug))

@bp.route("/contact")
def contact():
    return render_template("contact.html")

@bp.route("/policy")
def policy():
    return render_template("policy.html")

@bp.route("/about")
def about():
    return render_template("about.html")

@bp.route("/features")
def features():
    return render_template("features.html")
# -----------------------------
# Thank You Page
# -----------------------------
@bp.route("/thank_you")
def thank_you():
    return render_template("thank_you.html")

# -----------------------------
# Export Survey Responses
# -----------------------------
@bp.route("/survey/<int:survey_id>/export")
@login_required
def export_survey_responses(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    
    if survey.user_id != current_user.id:
        flash("You don't have permission to export responses from this survey.")
        return redirect(url_for("main.dashboard"))
    
    responses = SurveyResponse.query.filter_by(survey_id=survey.id).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    headers = ['Response ID', 'Date', 'IP Address']
    for question in survey.questions:
        headers.append(question.text)
    
    writer.writerow(headers)
    
    for response in responses:
        row = [
            response.id,
            response.created_at.strftime('%Y-%m-%d %H:%M'),
            response.respondent_ip
        ]
        
        response_data = response.get_responses()
        for question in survey.questions:
            answer = response_data.get(str(question.id), {})
            response_val = answer.get('response', '')
            if isinstance(response_val, list):
                row.append(', '.join(response_val))
            else:
                row.append(response_val)
        
        writer.writerow(row)
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=survey_{survey.id}_responses.csv",
            "Content-type": "text/csv"
        }
    )

@bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            # send_forgot_password_email(user.email) # Commented out
            pass
        flash("If an account with that email exists, a password reset link has been sent.", "info")
        return redirect(url_for('main.login'))
    return render_template('forgot_password.html', form=form)


@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token: str):
    email: Optional[str] = verify_password_reset_token(token)
    if not email:
        flash("The password reset link is invalid or has expired.", "danger")
        return redirect(url_for('main.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(form.password.data)
            db.session.commit()
            flash("Your password has been updated. Please log in.", "success")
            return redirect(url_for('main.login'))
    return render_template("reset_password.html", form=form)

# All payment routes REMOVED