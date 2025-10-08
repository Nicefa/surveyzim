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
import requests
import uuid

# Word limits for each package
WORD_LIMITS = {
    'student': 800,
    'basic': 1500,
    'extended': 3000,
    'enterprise': 5000
}

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
        send_welcome_user_email(user)

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
                # Only redirect to a relative URL for safety
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
    surveys = Survey.query.filter_by(user_id=current_user.id).all()
    # Handle None values by converting them to 0
    total_responses = sum(survey.response_count or 0 for survey in surveys)
    return render_template("dashboard.html", surveys=surveys, total_responses=total_responses)
# -----------------------------
# Create Survey
# -----------------------------
@bp.route("/create_survey", methods=["GET","POST"])
@login_required
def create_survey():
    form = SurveyForm()

    # 1️⃣ Detect plan from query parameters (when coming from pricing page)
    selected_package = request.args.get("package")
    package_word_limit = request.args.get("word_limit", type=int)

    # Fallback: if not passed, use user's current plan
    if not package_word_limit:
        package_word_limit = current_user.word_limit if current_user.payment_status != 'unpaid' else 999999
    if not selected_package:
        selected_package = current_user.payment_status if current_user.payment_status != 'unpaid' else None

    if form.validate_on_submit():
        # Calculate word count for title and description
        # Only count question words initially
        total_words = 0  # start at 0, title/description excluded

        
        # Check if user has exceeded their word limit
        if total_words > package_word_limit and current_user.payment_status != 'unpaid':
            flash(f"Your survey exceeds your word limit of {package_word_limit} words. Please reduce content or upgrade your plan.")
            return render_template(
                "survey_builder.html",
                form=form,
                selected_package=selected_package,
                package_word_limit=package_word_limit
            )
        
        # 1️⃣ Create the survey
        survey = Survey(
            title=form.title.data,
            description=form.description.data,
            user_id=current_user.id,
            word_count=total_words,
            created_with_package=selected_package,  
            created_with_word_limit=package_word_limit  
        )
        survey.generate_slug() 
        db.session.add(survey)
        db.session.commit()  # commit first to get survey.id

        # --- ADD LOGO UPLOAD FUNCTIONALITY HERE ---
        if 'logo' in request.files:
            logo_file = request.files['logo']
            if logo_file and logo_file.filename != '':
                # Save the logo file
                filename = secure_filename(logo_file.filename)
                unique_filename = f"{current_user.id}_{survey.id}_{int(datetime.utcnow().timestamp())}_{filename}"
                logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', unique_filename)
                

                # Update survey with logo filename
                survey.logo_filename = unique_filename
                db.session.commit()  # Commit the logo filename

        # 2️⃣ Handle dynamic questions from the frontend
        question_texts = request.form.getlist("question_text[]")
        question_types = request.form.getlist("question_type[]")

        # Get linear scale data
        linear_scale_lows = request.form.getlist("linear_scale_low[]")
        linear_scale_highs = request.form.getlist("linear_scale_high[]")
        linear_scale_low_labels = request.form.getlist("linear_scale_low_label[]")
        linear_scale_high_labels = request.form.getlist("linear_scale_high_label[]")

        for i, q_text in enumerate(question_texts):
            q_type = question_types[i]
            
            # Calculate word count for this question
            question_words = len(q_text.split()) if q_text else 0
            total_words += question_words
            
            # Check if adding this question would exceed the limit
            if total_words > package_word_limit and current_user.payment_status != 'unpaid':
                flash(f"Adding this question would exceed your word limit of {package_word_limit} words. Please reduce content or upgrade your plan.")
                db.session.delete(survey)
                db.session.commit()
                return render_template(
                    "survey_builder.html",
                    form=form,
                    selected_package=selected_package,
                    package_word_limit=package_word_limit
                )
            
            question = Question(
                text=q_text,
                qtype=q_type,
                survey_id=survey.id,
                word_count=question_words
            )

             # Handle linear scale specific fields
            if q_type == "linear_scale":
                question.linear_scale_low = int(linear_scale_lows[i]) if i < len(linear_scale_lows) and linear_scale_lows[i] else 1
                question.linear_scale_high = int(linear_scale_highs[i]) if i < len(linear_scale_highs) and linear_scale_highs[i] else 5
                question.linear_scale_low_label = linear_scale_low_labels[i] if i < len(linear_scale_low_labels) else ''
                question.linear_scale_high_label = linear_scale_high_labels[i] if i < len(linear_scale_high_labels) else ''
            
            db.session.add(question)
            db.session.flush()  # Get question ID for options

            # Handle options for multiple choice, checkbox, dropdown
            if q_type in ["multiple_choice", "checkbox", "dropdown"]:
                option_names = request.form.getlist(f"question_option_{i}[]")
                print(f"DEBUG: Found {len(option_names)} options for question {i}: {option_names}")
                for opt_text in option_names:
                    if opt_text.strip():
                        option = QuestionOption(
                            text=opt_text.strip(),
                            question_id=question.id
                        )
                        db.session.add(option)
        db.session.commit()

        flash("Survey created successfully! You can now manage your questions.")
        return redirect(url_for("main.survey_view", survey_id=survey.id))

    return render_template(
        "survey_builder.html",
        form=form,
        selected_package=selected_package,
        package_word_limit=package_word_limit
    )

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
        # Delete old logo if exists
        if survey.logo_filename:
            old_logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', survey.logo_filename)
            if os.path.exists(old_logo_path):
                os.remove(old_logo_path)
        
        # Save new logo
        filename = secure_filename(logo_file.filename)
        unique_filename = f"{current_user.id}_{survey.id}_{int(datetime.utcnow().timestamp())}_{filename}"
        logo_path = os.path.join(current_app.root_path, 'static', 'survey_logos', unique_filename)
        
        os.makedirs(os.path.dirname(logo_path), exist_ok=True)
        logo_file.save(logo_path)
        
        # Update survey with new logo
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
    
    package_word_limit = survey.created_with_word_limit or current_user.word_limit
    selected_package = survey.created_with_package or current_user.payment_status
    # Ensure current user owns the survey
    if survey.user_id != current_user.id:
        flash("You don't have permission to access this survey.")
        return redirect(url_for("main.dashboard"))

    form = QuestionForm()

    # Handle new questions submitted via POST
    if request.method == "POST":
        question_texts = request.form.getlist("question_text[]")
        question_types = request.form.getlist("question_type[]")

        total_words = survey.word_count or 0

        for i, q_text in enumerate(question_texts):
            q_type = question_types[i]

            # Calculate word count for this question
            question_words = len(q_text.split()) if q_text else 0
            new_total_words = total_words + question_words

            # Check if adding this question would exceed the limit
            if new_total_words > current_user.word_limit and current_user.payment_status != 'unpaid':
                flash(f"Adding this question would exceed your word limit of {current_user.word_limit} words. Please reduce content or upgrade your plan.")
                return redirect(url_for("main.survey_view", survey_id=survey.id))

            question = Question(
                text=q_text.strip(),
                qtype=q_type,
                survey_id=survey.id,
                word_count=question_words
            )
            db.session.add(question)
            db.session.flush()  # This ensures we get the question.id for options
            
            total_words = new_total_words  # update running total

            # FIXED: Handle options with consistent naming
            if q_type in ["multiple_choice", "checkbox", "dropdown"]:
                # Use consistent option naming
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

        # Update survey total word count after all questions added
        survey.word_count = total_words
        db.session.commit()

        flash("Questions added successfully!")
        return redirect(url_for("main.survey_view", survey_id=survey.id))  # redirect after POST

    # Get all questions for GET rendering
    questions = Question.query.options(joinedload(Question.options))\
               .filter_by(survey_id=survey.id)\
               .order_by(Question.id).all()
    total_word_count = 0
    for question in questions:
        if question.text:
            total_word_count += len(question.text.split())

    # Get package info from survey or fallback to user's plan
    if survey.created_with_package and survey.created_with_word_limit:
        selected_package = survey.created_with_package
        package_word_limit = survey.created_with_word_limit
        plan_name_map = {
            'student': 'Student',
            'basic': 'Basic',
            'extended': 'Extended',
            'enterprise': 'Enterprise'
        }
        plan_name = plan_name_map.get(selected_package, selected_package.capitalize())
    else:
        # Fallback to user's current plan
        selected_package = current_user.payment_status if current_user.payment_status != 'unpaid' else None
        package_word_limit = current_user.word_limit if current_user.payment_status != 'unpaid' else 999999
        plan_name_map = {
            'unpaid': 'Free',
            'student': 'Student',
            'basic': 'Basic',
            'extended': 'Extended',
            'enterprise': 'Enterprise'
        }
        plan_key = current_user.payment_status.lower()
        plan_name = plan_name_map.get(plan_key, 'Free')

    word_limit = package_word_limit
    progress_width = min(int((100 * total_word_count) / word_limit), 100) if word_limit > 0 else 0
    is_over_limit = total_word_count > word_limit

    # Distribution code
    distribution_days_map = {
        'student': 10,
        'basic': 14,
        'extended': 30,
        'enterprise': 60
    }
    distribution_days = distribution_days_map.get(current_user.payment_status, 0)
    distribution_over = False
    if survey.published_at and distribution_days > 0:
        end_date = survey.published_at + timedelta(days=distribution_days)
        distribution_over = datetime.utcnow() > end_date

    return render_template(
        "survey_view.html",
        survey=survey,
        form=form,
        questions=questions,
        total_word_count=total_word_count,
        word_limit=word_limit,
        plan_name=plan_name,
        progress_width=progress_width,
        is_over_limit=is_over_limit,
        distribution_over=distribution_over
    )

@bp.route("/debug/questions/<int:survey_id>")
@login_required
def debug_questions(survey_id):
    """Enhanced debug route to check questions and options"""
    survey = Survey.query.get_or_404(survey_id)
    
    # Check if user owns the survey
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
    
    # Ensure current user owns the question
    if survey.user_id != current_user.id:
        flash("You don't have permission to edit this question.")
        return redirect(url_for("main.dashboard"))
    
    # Check if survey is published (prevent editing)
    if survey.published:
        flash("Cannot edit questions after survey is published.")
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    try:
        # Get form data
        question_text = request.form.get('question_text', '').strip()
        question_type = request.form.get('question_type', 'short')
        question_required = request.form.get('question_required') == 'true'
        
        if not question_text:
            flash("Question text cannot be empty.")
            return redirect(url_for("main.survey_view", survey_id=survey.id))
        
        # Calculate new word count
        old_word_count = question.word_count or 0
        new_word_count = len(question_text.split()) if question_text else 0
        
        # Update question word count
        question.word_count = new_word_count
        
        # Update survey total word count
        survey.word_count = (survey.word_count or 0) - old_word_count + new_word_count
        
        # Update other question fields
        question.text = question_text
        question.qtype = question_type
        question.required = question_required
        
        # Handle linear scale fields
        if question_type == "linear_scale":
            question.linear_scale_low = int(request.form.get('linear_scale_low', 1))
            question.linear_scale_high = int(request.form.get('linear_scale_high', 5))
            question.linear_scale_low_label = request.form.get('linear_scale_low_label', '')
            question.linear_scale_high_label = request.form.get('linear_scale_high_label', '')
        else:
            # Clear linear scale fields for non-linear scale questions
            question.linear_scale_low = None
            question.linear_scale_high = None
            question.linear_scale_low_label = None
            question.linear_scale_high_label = None
        
        # Handle options for multiple choice types
        if question_type in ["multiple_choice", "checkbox", "dropdown"]:
            option_texts = request.form.getlist('options[]')
            
            # Validate options
            valid_options = [opt.strip() for opt in option_texts if opt.strip()]
            if not valid_options:
                flash("Multiple choice, checkbox, and dropdown questions must have at least one option.")
                return redirect(url_for("main.survey_view", survey_id=survey.id))
            
            # Clear existing options
            QuestionOption.query.filter_by(question_id=question.id).delete()
            
            # Add new options
            for opt_text in valid_options:
                option = QuestionOption(
                    text=opt_text,
                    question_id=question.id
                )
                db.session.add(option)
        else:
            # Remove options for non-option question types
            QuestionOption.query.filter_by(question_id=question.id).delete()
        
        db.session.commit()
        flash("Question updated successfully!")
        
    except Exception as e:
        db.session.rollback()
        flash("Error updating question. Please try again.")
        print(f"Error updating question: {str(e)}")
    
    return redirect(url_for("main.survey_view", survey_id=survey.id))

# -----------------------------
# Get Question Data (AJAX)
# -----------------------------
@bp.route("/question/<int:question_id>/json")
@login_required
def get_question_json(question_id):
    """AJAX endpoint to get question data for editing"""
    question = Question.query.get_or_404(question_id)
    
    # Ensure current user owns the question
    if question.survey.user_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    question_data = {
        'id': question.id,
        'text': question.text,
        'qtype': question.qtype,
        'required': question.required,
        'word_count': question.word_count,
        'options': [{'id': opt.id, 'text': opt.text} for opt in question.options]
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

    # Update survey word count before deleting the question
    survey.word_count -= question.word_count
    db.session.delete(question)
    db.session.commit()
    
    # Recalculate total word count for the survey
    total_word_count = sum(len(q.text.split()) for q in survey.questions if q.text)

    
    survey.word_count = total_word_count
    db.session.commit()
    
    flash("Question deleted successfully!")
    return redirect(url_for("main.survey_view", survey_id=survey_id))

# -----------------------------
# Delete Survey
# -----------------------------
@bp.route("/survey/<int:survey_id>/delete", methods=["POST"])
@login_required
def delete_survey(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    if survey.user_id != current_user.id:
        flash("You don't have permission to delete this survey.")
        return redirect(url_for("main.dashboard"))

    Question.query.filter_by(survey_id=survey_id).delete()
    db.session.delete(survey)
    db.session.commit()
    flash("Survey deleted successfully!")
    return redirect(url_for("main.dashboard"))
# -----------------------------
# Preview Survey
# -----------------------------
@bp.route('/preview_survey/<int:survey_id>')
def preview_survey(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    questions = Question.query.options(joinedload(Question.options))\
               .filter_by(survey_id=survey.id)\
               .order_by(Question.id).all()
    
    preview = True
    
    # Debug output
    for q in questions:
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
        db.session.commit()
    
    survey_url = url_for("main.take_survey", slug=survey.slug, _external=True)
    
    # Check if user owns the survey
    if survey.user_id != current_user.id:
        flash("You don't have permission to publish this survey.")
        return redirect(url_for("main.dashboard"))
    
    # Check if user has paid
    if current_user.payment_status == 'unpaid':
        flash("You need to purchase a plan to publish surveys.")
        return redirect(url_for("main.payment_select"))
    
    # Check if survey has at least one question
    if len(survey.questions) == 0:
        flash("Survey must have at least one question before publishing.")
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    # Check if survey exceeds word limit
    if survey.word_count > current_user.word_limit:
        flash("Survey exceeds your word limit. Please upgrade your plan or reduce content.")
        return redirect(url_for("main.survey_view", survey_id=survey.id))
    
    # Publish the survey
    survey.published = True
    survey.published_at = datetime.utcnow()
    survey.survey_url = survey_url  # Store the URL
    db.session.commit()
    
    # Send emails asynchronously
    send_survey_published_emails(survey, current_user.email)
    
    flash(f"Survey published successfully! Share this link: {survey_url}")
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

    # ✅ FIXED: Use the correct relationship and eager loading
    questions = Question.query.options(joinedload(Question.options))\
               .filter_by(survey_id=survey.id)\
               .order_by(Question.id).all()
    
    # Debug: Check if options are being loaded
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
    
    # Check if survey is published
    if not survey.published:
        flash("This survey is not available.")
        return redirect(url_for("main.index"))
    
    # Process the responses
    responses = {}
    for question in survey.questions:
        if question.qtype in ["multiple_choice", "dropdown", "linear_scale"]:
            response_value = request.form.get(f"question_{question.id}")
            responses[question.id] = {
                "question_text": question.text,
                "question_type": question.qtype,
                "response": response_value
            }
        elif question.qtype == "checkbox":
            response_values = request.form.getlist(f"question_{question.id}")
            responses[question.id] = {
                "question_text": question.text,
                "question_type": question.qtype,
                "response": response_values
            }
        else:  # short, paragraph
            response_value = request.form.get(f"question_{question.id}")
            responses[question.id] = {
                "question_text": question.text,
                "question_type": question.qtype,
                "response": response_value
            }
    
    # Save the response to database
    try:
        survey_response = SurveyResponse(
            survey_id=survey.id,
            respondent_ip=request.remote_addr,
            respondent_info=request.headers.get('User-Agent', 'Unknown')  # Store browser info
        )
        survey_response.set_responses(responses)
        
        db.session.add(survey_response)
        
        # Update response count
        survey.response_count = SurveyResponse.query.filter_by(survey_id=survey.id).count()
        
        db.session.commit()
        
        flash("Thank you for completing the survey!")
        return redirect(url_for("main.thank_you"))
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while submitting your response. Please try again.")
        return redirect(url_for("main.take_survey", survey_id=survey.id))

# -----------------------------
# Payment Selection
# -----------------------------
@bp.route("/payment_select")
@login_required
def payment_select():
    return render_template("payment_select.html")

# -----------------------------
# Process Payment
# -----------------------------
@bp.route("/process_payment/<package>", methods=["POST"])
@login_required
def process_payment(package):
    if package not in WORD_LIMITS:
        flash("Invalid package selected.")
        return redirect(url_for("main.payment_select"))

    # 1️⃣ Collect EcoCash number from frontend form
    phone = request.form.get("phone")
    if not phone:
        flash("Please provide your EcoCash number.")
        return redirect(url_for("main.payment", package=package))

    # 2️⃣ Generate unique reference
    reference = str(uuid.uuid4())

    # 3️⃣ Prepare EcoCash API request
    payload = {
        "customerEcocashPhoneNumber": phone,
        "amount": 10.0,  # set real amount depending on package
        "description": f"Payment for {package} plan",
        "currency": "USD",
        "callbackUrl": url_for("main.ecocash_callback", _external=True),
        "reference": reference
    }

    headers = {
        "Authorization": f"Bearer {current_app.config['ECOCASH_API_KEY']}",
        "Content-Type": "application/json"
    }

    # 4️⃣ Send request to EcoCash API
    try:
        resp = requests.post(
            current_app.config["ECOCASH_BASE_URL"] + "/payments",
            json=payload,
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") in ["SUCCESS", "PENDING"]:
            # Temporarily store reference on user until callback confirms
            current_user.payment_reference = reference
            current_user.pending_package = package
            db.session.commit()

            flash("Payment request sent to your EcoCash number. Please approve on your phone.")
            return redirect(url_for("main.dashboard"))
        else:
            flash(f"Payment initiation failed: {data.get('error', 'Unknown error')}", "danger")
            return redirect(url_for("main.payment", package=package))

    except Exception as e:
        flash(f"Error initiating payment: {str(e)}", "danger")
        return redirect(url_for("main.payment", package=package))

# -----------------------------
# Payment page
# -----------------------------
@bp.route("/payment/<package>")
@login_required
def payment(package):
    # Define package details
    packages = {
        "student": {
            "name": "Student Plan", 
            "price": "$30", 
            "word_limit": "800 words",
            "features": ["1 survey", "Up to 200 responses", "10-day distribution", "CSV export"]
        },
        "basic": {
            "name": "Basic Plan", 
            "price": "$100", 
            "word_limit": "1,500 words",
            "features": ["1 survey", "Up to 1,000 responses", "14-day distribution", "Light demographic targeting"]
        },
        "extended": {
            "name": "Extended Plan", 
            "price": "$250", 
            "word_limit": "3,000 words",
            "features": ["1 survey", "Up to 5,000 responses", "30-day distribution", "Full demographic targeting"]
        },
        "enterprise": {
            "name": "Enterprise Plan", 
            "price": "Starting at $600", 
            "word_limit": "5,000+ words",
            "features": ["Custom surveys", "10,000+ responses", "60-day distribution", "Advanced targeting", "Full support"]
        }
    }

    plan = packages.get(package)
    if not plan:
        flash("Invalid package selected.", "danger")
        return redirect(url_for("main.index"))

    return render_template("payment.html", plan=plan, package=package)

@bp.route("/contact")
def contact():
    return render_template("contact.html")

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
    
    # Check if user owns the survey
    if survey.user_id != current_user.id:
        flash("You don't have permission to export responses from this survey.")
        return redirect(url_for("main.dashboard"))
    
    responses = SurveyResponse.query.filter_by(survey_id=survey.id).all()
    
    # Create CSV content
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    headers = ['Response ID', 'Date', 'IP Address']
    for question in survey.questions:
        headers.append(question.text)
    
    writer.writerow(headers)
    
    # Write data
    for response in responses:
        row = [
            response.id,
            response.created_at.strftime('%Y-%m-%d %H:%M'),
            response.respondent_ip
        ]
        
        response_data = response.get_responses()
        for question in survey.questions:
            answer = response_data.get(str(question.id), {})
            if isinstance(answer.get('response'), list):
                row.append(', '.join(answer.get('response', [])))
            else:
                row.append(answer.get('response', ''))
        
        writer.writerow(row)
    
    # Prepare response
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
            send_forgot_password_email(user.email)
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

@bp.route("/payment/callback", methods=["POST"])
def ecocash_callback():
    data = request.get_json(silent=True) or request.form.to_dict()
    print("📩 Callback received:", data)

    reference = data.get("reference")
    status = data.get("status")

    # Lookup user with this reference
    user = User.query.filter_by(payment_reference=reference).first()

    if not user:
        return "User not found", 404

    if status and status.upper() == "SUCCESS":
        package = getattr(user, "pending_package", None)
        if package in WORD_LIMITS:
            user.payment_status = package
            user.word_limit = WORD_LIMITS[package]
            user.plan_name = package.capitalize()
            user.payment_reference = None
            user.pending_package = None
            db.session.commit()
            print(f"✅ Payment confirmed for {user.username}, plan {package}")
    else:
        print(f"⚠️ Payment failed or pending for {reference}: {status}")

    return "OK", 200
