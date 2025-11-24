from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from flask_wtf.file import FileField, FileAllowed

# -----------------------------
# User Authentication Forms
# -----------------------------
class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo('password')]
    )
    submit = SubmitField("Register")

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField("Login")

class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send Reset Link")   

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired()])
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match')]
    )
    submit = SubmitField('Reset Password')

# -----------------------------
# Survey Forms
# -----------------------------
class SurveyForm(FlaskForm):
    title = StringField("Survey Title", validators=[DataRequired()])
    description = TextAreaField("Description")
    logo = FileField('Survey Logo', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')
    ])
    submit = SubmitField("Create Survey")

class QuestionForm(FlaskForm):
    text = StringField("Question", validators=[DataRequired()])
    qtype = SelectField("Type", choices=[("short","Short Answer"),("paragraph","Paragraph")])
    submit = SubmitField("Add Question")

