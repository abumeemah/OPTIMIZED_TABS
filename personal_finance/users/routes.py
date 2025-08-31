import os
import logging
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, session, make_response
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, SubmitField, BooleanField, validators
from flask_login import login_required, current_user, login_user, logout_user
from pymongo import errors
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mailman import EmailMessage
import re
import random
from itsdangerous import URLSafeTimedSerializer
import utils
from utils import logger
from translations import trans
from models import create_user

users_bp = Blueprint('users', __name__, template_folder='templates/users')

USERNAME_REGEX = re.compile(r'^[a-zA-Z0-9_]{3,50}$')
PASSWORD_REGEX = re.compile(r'.{6,}')
PHONE_REGEX = re.compile(r'^\+?\d{10,15}$')

# Custom validator for the login identifier
def validate_identifier(form, field):
    identifier = field.data.strip()
    if '@' not in identifier:
        if not USERNAME_REGEX.match(identifier):
            raise validators.ValidationError(trans('general_username_format', default='Username must be alphanumeric with underscores'))

class LoginForm(FlaskForm):
    username = StringField(
        trans('general_login_identifier', default='Username or Email'),
        [
            validators.DataRequired(message=trans('general_identifier_required', default='Username or Email is required')),
            validators.Length(min=3, max=50, message=trans('general_identifier_length', default='Identifier must be between 3 and 50 characters')),
            validate_identifier
        ],
        render_kw={'class': 'form-control'}
    )
    password = PasswordField(trans('general_password', default='Password'), [
        validators.DataRequired(message=trans('general_password_required', default='Password is required')),
        validators.Length(min=6, message=trans('general_password_length', default='Password must be at least 6 characters'))
    ], render_kw={'class': 'form-control'})
    remember = BooleanField(trans('general_remember_me', default='Remember me'), render_kw={'class': 'form-check-input'})
    submit = SubmitField(trans('general_login', default='Sign In'), render_kw={'class': 'btn btn-primary w-100'})

class TwoFactorForm(FlaskForm):
    otp = StringField(trans('general_otp', default='One-Time Password'), [
        validators.DataRequired(message=trans('general_otp_required', default='OTP is required')),
        validators.Length(min=6, max=6, message=trans('general_otp_length', default='OTP must be 6 digits')),
        validators.Regexp(r'^\d{6}$', message=trans('general_otp_digits', default='OTP must be 6 digits'))
    ], render_kw={'class': 'form-control'})
    submit = SubmitField(trans('general_verify_otp', default='Verify OTP'), render_kw={'class': 'btn btn-primary w-100'})

class SignupForm(FlaskForm):
    username = StringField(
        trans('general_username', default='Username'),
        [
            validators.DataRequired(message=trans('general_username_required', default='Username is required')),
            validators.Length(min=3, max=50, message=trans('general_username_length', default='Username must be between 3 and 50 characters')),
            validators.Regexp(USERNAME_REGEX, message=trans('general_username_format', default='Username must be alphanumeric with underscores'))
        ],
        render_kw={'class': 'form-control'}
    )
    email = StringField(
        trans('general_email', default='Email'),
        [
            validators.DataRequired(message=trans('general_email_required', default='Email is required')),
            validators.Email(message=trans('general_email_invalid', default='Invalid email address')),
            validators.Length(max=254),
            lambda form, field: utils.is_valid_email(field.data.strip().lower()) or validators.ValidationError(trans('general_email_domain_invalid', default='Invalid email domain'))
        ],
        render_kw={'class': 'form-control'}
    )
    password = PasswordField(
        trans('general_password', default='Password'),
        [
            validators.DataRequired(message=trans('general_password_required', default='Password is required')),
            validators.Length(min=6, message=trans('general_password_length', default='Password must be at least 6 characters')),
            validators.Regexp(PASSWORD_REGEX, message=trans('general_password_format', default='Password must be at least 6 characters'))
        ],
        render_kw={'class': 'form-control'}
    )
    submit = SubmitField(
        trans('general_signup', default='Sign Up'),
        render_kw={'class': 'btn btn-primary w-100'}
    )

class ForgotPasswordForm(FlaskForm):
    email = StringField(trans('general_email', default='Email'), [
        validators.DataRequired(message=trans('general_email_required', default='Email is required')),
        validators.Email(message=trans('general_email_invalid', default='Invalid email address'))
    ], render_kw={'class': 'form-control'})
    submit = SubmitField(trans('general_send_reset_link', default='Send Reset Link'), render_kw={'class': 'btn btn-primary w-100'})

class ResetPasswordForm(FlaskForm):
    password = PasswordField(trans('general_password', default='Password'), [
        validators.DataRequired(message=trans('general_password_required', default='Password is required')),
        validators.Length(min=6, message=trans('general_password_length', default='Password must be at least 6 characters')),
        validators.Regexp(PASSWORD_REGEX, message=trans('general_password_format', default='Password must be at least 6 characters'))
    ], render_kw={'class': 'form-control'})
    confirm_password = PasswordField(trans('general_confirm_password', default='Confirm Password'), [
        validators.DataRequired(message=trans('general_confirm_password_required', default='Confirm password is required')),
        validators.EqualTo('password', message=trans('general_passwords_must_match', default='Passwords must match'))
    ], render_kw={'class': 'form-control'})
    submit = SubmitField(trans('general_reset_password', default='Reset Password'), render_kw={'class': 'btn btn-primary w-100'})

class PersonalSetupForm(FlaskForm):
    first_name = StringField(trans('general_first_name', default='First Name'),
                            validators=[validators.DataRequired(message=trans('general_first_name_required', default='First name is required')),
                                        validators.Length(min=1, max=255, message=trans('general_first_name_length', default='First name must be between 1 and 255 characters'))],
                            render_kw={'class': 'form-control'})
    last_name = StringField(trans('general_last_name', default='Last Name'),
                           validators=[validators.DataRequired(message=trans('general_last_name_required', default='Last name is required')),
                                       validators.Length(min=1, max=255, message=trans('general_last_name_length', default='Last name must be between 1 and 255 characters'))],
                           render_kw={'class': 'form-control'})
    phone_number = StringField(trans('general_phone_number', default='Phone Number'),
                              validators=[
                                  validators.DataRequired(message=trans('general_phone_number_required', default='Phone number is required')),
                                  validators.Regexp(PHONE_REGEX, message=trans('general_phone_number_format', default='Phone number must be 10-15 digits'))
                              ],
                              render_kw={'class': 'form-control'})
    address = TextAreaField(trans('general_address', default='Address'),
                           validators=[validators.DataRequired(message=trans('general_address_required', default='Address is required')),
                                       validators.Length(max=500, message=trans('general_address_length', default='Address must be at most 500 characters'))],
                           render_kw={'class': 'form-control'})
    language = SelectField(trans('general_language', default='Language'),
                          choices=[
                              ('en', trans('general_english', default='English')),
                              ('ha', trans('general_hausa', default='Hausa'))
                          ],
                          validators=[validators.DataRequired(message=trans('general_language_required', default='Language is required'))],
                          render_kw={'class': 'form-select'})
    terms = BooleanField(trans('general_terms', default='I accept the Terms and Conditions'),
                        validators=[validators.DataRequired(message=trans('general_terms_required', default='You must accept the terms'))],
                        render_kw={'class': 'form-check-input'})
    submit = SubmitField(trans('general_save_and_continue', default='Save and Continue'), render_kw={'class': 'btn btn-primary w-100'})
    back = SubmitField(trans('general_back', default='Back'), render_kw={'class': 'btn btn-secondary w-100 mt-2'})

def log_audit_action(action, details=None):
    try:
        db = utils.get_mongo_db()
        audit_details = {
            'admin_id': str(current_user.id) if current_user.is_authenticated else 'system',
            'action': action,
            'details': details or {},
            'timestamp': datetime.utcnow(),
            'session_id': session.get('session_id', 'no-session-id')
        }
        db.audit_logs.insert_one(audit_details)
        logger.debug(f"Audit log created: {audit_details}")
    except errors.PyMongoError as e:
        logger.error(f"MongoDB error logging audit action '{action}': {str(e)}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error logging audit action '{action}': {str(e)}", exc_info=True)

def get_setup_wizard_route(role):
    """Get the appropriate setup wizard route based on user role."""
    try:
        if role == 'personal':
            return 'users.personal_setup_wizard'
        logger.warning(f"Unknown role '{role}' for setup wizard, defaulting to personal setup")
        return 'users.personal_setup_wizard'
    except Exception as e:
        logger.error(f"Error determining setup wizard route for role '{role}': {str(e)}", exc_info=True)
        return 'users.personal_setup_wizard'

def get_post_login_redirect(user_role):
    """Determine where to redirect user after login based on their role."""
    try:
        if user_role == 'personal':
            return url_for('general_bp.home')
        logger.warning(f"Unknown role '{user_role}' for login redirect, defaulting to home")
        return url_for('general_bp.home')
    except Exception as e:
        logger.error(f"Error determining login redirect for role '{user_role}': {str(e)}", exc_info=True)
        return url_for('home')

def get_explore_tools_redirect(user_role):
    """Determine where to redirect user when they click 'Explore Your Tools' based on their role."""
    try:
        if user_role == 'personal':
            return url_for('dashboard.index')
        logger.warning(f"Unknown role '{user_role}' for explore tools redirect, defaulting to general_bp.home")
        return url_for('home')
    except Exception as e:
        logger.error(f"Error determining explore tools redirect for role '{user_role}': {str(e)}", exc_info=True)
        return url_for('home')

@users_bp.route('/login', methods=['GET', 'POST'])
@utils.limiter.limit("50/hour")
def login():
    if current_user.is_authenticated:
        try:
            logger.info(f"Authenticated user {current_user.id} redirected from login, session_id: {session.get('session_id')}")
            return redirect(get_post_login_redirect(current_user.role))
        except Exception as e:
            logger.error(f"Error redirecting authenticated user: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            return redirect(url_for('users.login')), 500

    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        logger.debug(f"Created new session_id: {session['session_id']}")

    form = LoginForm()
    if request.method == 'POST':
        logger.debug(f"Received POST request for login, form data: {request.form}, session_id: {session.get('session_id')}")
        if form.validate_on_submit():
            try:
                identifier = form.username.data.strip().lower()
                password = form.password.data
                logger.info(f"Login attempt for identifier: {identifier}, session_id: {session['session_id']}")
                
                db = utils.get_mongo_db()
                if '@' in identifier:
                    user = db.users.find_one({'email': {'$regex': f'^{re.escape(identifier)}$', '$options': 'i'}})
                else:
                    user = db.users.find_one({'_id': {'$regex': f'^{re.escape(identifier)}$', '$options': 'i'}})
                
                if not user:
                    logger.warning(f"Login attempt failed: Identifier {identifier} not found")
                    flash(trans('general_identifier_not_found', default='Username or Email not found. Please check your signup details.'), 'danger')
                    log_audit_action('login_failed', {'identifier': identifier, 'reason': 'identifier_not_found'})
                    return render_template('users/login.html', form=form, title=trans('general_login', lang=session.get('lang', 'en'))), 401

                username = user['_id']
                if not check_password_hash(user['password_hash'], password):
                    logger.warning(f"Login attempt failed for username: {username} (invalid password)")
                    flash(trans('general_invalid_password', default='Incorrect password'), 'danger')
                    log_audit_action('login_failed', {'user_id': username, 'reason': 'invalid_password'})
                    return render_template('users/login.html', form=form, title=trans('general_login', lang=session.get('lang', 'en'))), 401

                logger.info(f"User found: {username}, proceeding with login")
                if os.environ.get('ENABLE_2FA', 'false').lower() == 'true':
                    otp = ''.join(str(random.randint(0, 9)) for _ in range(6))
                    try:
                        db.users.update_one(
                            {'_id': username},
                            {'$set': {'otp': otp, 'otp_expiry': datetime.utcnow() + timedelta(minutes=5)}}
                        )
                        mail = utils.get_mail(current_app)
                        lang = user.get('language', session.get('lang', 'en'))
                        translation_key = 'general_otp_body_ha' if lang == 'ha' else 'general_otp_body'
                        msg = EmailMessage(
                            subject=trans('general_otp_subject', default='Your One-Time Password', lang=lang),
                            body=trans(translation_key, default='Your OTP is {otp}. It expires in 5 minutes.', lang=lang, otp=otp),
                            to=[user['email']]
                        )
                        msg.send()
                        session['pending_user_id'] = username
                        logger.info(f"OTP sent to {user['email']} for username: {username}")
                        log_audit_action('otp_sent', {'user_id': username, 'email': user['email']})
                        return redirect(url_for('users.verify_2fa'))
                    except Exception as e:
                        logger.warning(f"Email delivery or formatting failed for OTP for {username}: {str(e)}", exc_info=True)
                        from app import User
                        user_obj = User(user['_id'], user['email'], user.get('display_name'), user.get('role', 'personal'))
                        login_user(user_obj, remember=form.remember.data)
                        session['lang'] = user.get('language', 'en')

                        log_audit_action('login_without_2fa', {'user_id': username, 'reason': 'email_failure_test_mode'})
                        logger.info(f"User {username} logged in without 2FA due to email failure (test mode). Session: {dict(session)}")
                        if not user.get('setup_complete', False):
                            setup_route = get_setup_wizard_route(user.get('role', 'personal'))
                            return redirect(url_for(setup_route))
                        return redirect(get_post_login_redirect(user.get('role', 'personal')))
                from app import User
                user_obj = User(user['_id'], user['email'], user.get('display_name'), user.get('role', 'personal'))
                login_result = login_user(user_obj, remember=form.remember.data)
                logger.debug(f"login_user result for {username}: {login_result}")
                if not login_result:
                    logger.error(f"login_user failed for {username} without raising an exception")
                    flash(trans('general_login_failed', default='Login failed. Please try again.'), 'danger')
                    log_audit_action('login_failed', {'user_id': username, 'reason': 'login_user_failed'})
                    return render_template('users/login.html', form=form, title=trans('general_login', lang=session.get('lang', 'en'))), 401
                
                session['lang'] = user.get('language', 'en')
                
                log_audit_action('login', {'user_id': username})
                logger.info(f"User {username} logged in successfully. Session: {dict(session)}")
                if not user.get('setup_complete', False):
                    setup_route = get_setup_wizard_route(user.get('role', 'personal'))
                    return redirect(url_for(setup_route))
                return redirect(get_post_login_redirect(user.get('role', 'personal')))
            except errors.PyMongoError as e:
                logger.error(f"MongoDB error during login for {identifier}: {str(e)}", exc_info=True)
                flash(trans('general_database_error', default='An error occurred while accessing the database. Please try again later.'), 'danger')
                log_audit_action('login_failed', {'identifier': identifier, 'reason': 'mongodb_error', 'error': str(e)})
                return render_template('users/login.html', form=form, title=trans('general_login', lang=session.get('lang', 'en'))), 500
            except Exception as e:
                logger.error(f"Unexpected error during login for {identifier}: {str(e)}", exc_info=True)
                flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
                log_audit_action('login_failed', {'identifier': identifier, 'reason': 'unexpected_error', 'error': str(e)})
                return render_template('users/login.html', form=form, title=trans('general_login', lang=session.get('lang', 'en'))), 500
        else:
            logger.debug(f"Form validation failed: {form.errors}, session_id: {session.get('session_id')}")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"{field}: {error}", 'danger')
    else:
        logger.debug(f"Rendering login page for GET request, session_id: {session.get('session_id')}")
    return render_template('users/login.html', form=form, title=trans('general_login', lang=session.get('lang', 'en')))

@users_bp.route('/verify_2fa', methods=['GET', 'POST'])
@utils.limiter.limit("50/hour")
def verify_2fa():
    if current_user.is_authenticated:
        try:
            logger.info(f"Authenticated user {current_user.id} redirected from 2FA, session_id: {session.get('session_id')}")
            return redirect(get_post_login_redirect(current_user.role))
        except Exception as e:
            logger.error(f"Error redirecting authenticated user in 2FA: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            return redirect(url_for('users.login')), 500

    if 'pending_user_id' not in session:
        flash(trans('general_invalid_2fa_session', default='Invalid 2FA session. Please log in again'), 'danger')
        logger.warning(f"Invalid 2FA session: No pending_user_id, session_id: {session.get('session_id')}")
        log_audit_action('2fa_failed', {'reason': 'no_pending_user_id'})
        return redirect(url_for('users.login'))

    form = TwoFactorForm()
    if form.validate_on_submit():
        username = session['pending_user_id']
        logger.info(f"2FA verification attempt for username: {username}, session_id: {session.get('session_id')}")
        try:
            db = utils.get_mongo_db()
            user = db.users.find_one({'_id': username})
            if not user:
                flash(trans('general_user_not_found', default='User not found'), 'danger')
                logger.warning(f"2FA attempt for non-existent username: {username}")
                log_audit_action('2fa_failed', {'user_id': username, 'reason': 'user_not_found'})
                session.pop('pending_user_id', None)
                return redirect(url_for('users.login'))
            if user.get('otp') == form.otp.data and user.get('otp_expiry') > datetime.utcnow():
                from app import User
                user_obj = User(user['_id'], user['email'], user.get('display_name'), user.get('role', 'personal'))
                login_user(user_obj, remember=True)
                
                session['lang'] = user.get('language', 'en')
                db.users.update_one(
                    {'_id': username},
                    {'$unset': {'otp': '', 'otp_expiry': ''}}
                )
                log_audit_action('verify_2fa', {'user_id': username})
                logger.info(f"User {username} verified 2FA successfully. Session: {dict(session)}")
                session.pop('pending_user_id', None)
                if not user.get('setup_complete', False):
                    setup_route = get_setup_wizard_route(user.get('role', 'personal'))
                    return redirect(url_for(setup_route))
                return redirect(get_post_login_redirect(user.get('role', 'personal')))
            flash(trans('general_invalid_otp', default='Invalid or expired OTP'), 'danger')
            logger.warning(f"Failed 2FA attempt for username: {username}")
            log_audit_action('2fa_failed', {'user_id': username, 'reason': 'invalid_otp'})
            return render_template('users/verify_2fa.html', form=form, title=trans('general_verify_otp', lang=session.get('lang', 'en')))
        except errors.PyMongoError as e:
            logger.error(f"MongoDB error during 2FA verification for {username}: {str(e)}", exc_info=True)
            flash(trans('general_database_error', default='An error occurred while accessing the database. Please try again later.'), 'danger')
            log_audit_action('2fa_failed', {'user_id': username, 'reason': 'mongodb_error', 'error': str(e)})
            return render_template('users/verify_2fa.html', form=form, title=trans('general_verify_otp', lang=session.get('lang', 'en'))), 500
        except Exception as e:
            logger.error(f"Unexpected error during 2FA verification for {username}: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            log_audit_action('2fa_failed', {'user_id': username, 'reason': 'unexpected_error', 'error': str(e)})
            return render_template('users/verify_2fa.html', form=form, title=trans('general_verify_otp', lang=session.get('lang', 'en'))), 500
    else:
        logger.debug(f"2FA form validation failed: {form.errors}, session_id: {session.get('session_id')}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", 'danger')
    return render_template('users/verify_2fa.html', form=form, title=trans('general_verify_otp', lang=session.get('lang', 'en')))

@users_bp.route('/signup', methods=['GET', 'POST'])
@utils.limiter.limit("50/hour")
def signup():
    if current_user.is_authenticated:
        try:
            logger.info(f"Authenticated user {current_user.id} redirected from signup, session_id: {session.get('session_id')}")
            return redirect(get_post_login_redirect(current_user.role))
        except Exception as e:
            logger.error(f"Error redirecting authenticated user in signup: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            return redirect(url_for('users.login')), 500

    form = SignupForm()
    if form.validate_on_submit():
        username = form.username.data.strip().lower()
        email = form.email.data.strip().lower()
        password = form.password.data
        logger.debug(f"Signup attempt: username={username}, email={email}, session_id: {session.get('session_id')}")
        logger.info(f"Signup attempt: username={username}, email={email}")
        try:
            db = utils.get_mongo_db()

            if db.users.find_one({'_id': username}):
                flash(trans('general_username_exists', default='Username already exists'), 'danger')
                logger.warning(f"Signup failed: Username {username} already exists")
                log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'username_exists'})
                return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en')))

            if db.users.find_one({'email': email}):
                flash(trans('general_email_exists', default='Email already exists'), 'danger')
                logger.warning(f"Signup failed: Email {email} already exists")
                log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'email_exists'})
                return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en')))

            # Validate inputs before creating user
            if not USERNAME_REGEX.match(username):
                flash(trans('general_username_format', default='Username must be alphanumeric with underscores'), 'danger')
                logger.warning(f"Signup failed: Invalid username format for {username}")
                log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'invalid_username_format'})
                return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en')))

            if not utils.is_valid_email(email):
                flash(trans('general_email_domain_invalid', default='Invalid email domain'), 'danger')
                logger.warning(f"Signup failed: Invalid email domain for {email}")
                log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'invalid_email_domain'})
                return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en')))

            if not PASSWORD_REGEX.match(password):
                flash(trans('general_password_format', default='Password must be at least 6 characters'), 'danger')
                logger.warning(f"Signup failed: Invalid password format for {username}")
                log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'invalid_password_format'})
                return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en')))

            user_data = {
                '_id': username,
                'email': email,
                'password': password,  # create_user will hash this
                'role': 'personal',
                'ficore_credit_balance': 10,  # Integer as per MongoDB schema
                'language': 'en',
                'dark_mode': False,
                'is_admin': False,
                'setup_complete': False,
                'display_name': username,
                'created_at': datetime.utcnow()
            }

            user_obj = create_user(db, user_data)

            # Ensure session_id is set for the transaction
            if 'session_id' not in session:
                session['session_id'] = str(uuid.uuid4())
                logger.debug(f"Created new session_id for signup: {session['session_id']}")

            # Insert transaction with all required fields as per schema
            transaction_data = {
                'user_id': username,
                'action': 'signup_bonus',
                'amount': 10,
                'timestamp': datetime.utcnow(),
                'session_id': session['session_id'],
                'status': 'completed',
                'type': 'credit',
                'description': 'Signup bonus'
            }
            logger.debug(f"Inserting ficore_credit_transaction: {transaction_data}")
            db.ficore_credit_transactions.insert_one(transaction_data)

            log_audit_action('signup', {'user_id': username, 'email': email, 'role': 'personal'})
            logger.info(f"New user created: {username}, email: {email}, role: personal")

            from app import User
            user_obj = User(username, email, username, 'personal')
            login_user(user_obj, remember=True)
            session['lang'] = 'en'
            
            logger.info(f"User {username} logged in after signup. Session: {dict(session)}")
            setup_route = get_setup_wizard_route('personal')
            return redirect(url_for(setup_route))
        except errors.WriteError as e:
            logger.error(f"WriteError during signup for {username}: {str(e)}", exc_info=True)
            flash(trans('general_database_validation_error', default='Invalid data provided for signup. Please try again.'), 'danger')
            log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'write_error', 'error': str(e)})
            return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en'))), 400
        except errors.PyMongoError as e:
            logger.error(f"MongoDB error during signup for {username}: {str(e)}", exc_info=True)
            flash(trans('general_database_error', default='An error occurred while accessing the database. Please try again later.'), 'danger')
            log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'mongodb_error', 'error': str(e)})
            return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en'))), 500
        except Exception as e:
            logger.error(f"Unexpected error during signup for {username}: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            log_audit_action('signup_failed', {'username': username, 'email': email, 'reason': 'unexpected_error', 'error': str(e)})
            return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en'))), 500
    else:
        logger.debug(f"Signup form validation failed: {form.errors}, session_id: {session.get('session_id')}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", 'danger')
    return render_template('users/signup.html', form=form, title=trans('general_signup', lang=session.get('lang', 'en')))

@users_bp.route('/forgot_password', methods=['GET', 'POST'])
@utils.limiter.limit("50/hour")
def forgot_password():
    if current_user.is_authenticated:
        try:
            logger.info(f"Authenticated user {current_user.id} redirected from forgot_password, session_id: {session.get('session_id')}")
            return redirect(get_post_login_redirect(current_user.role))
        except Exception as e:
            logger.error(f"Error redirecting authenticated user in forgot_password: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            return redirect(url_for('users.login')), 500

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        logger.info(f"Forgot password request for email: {email}, session_id: {session.get('session_id')}")
        try:
            if not utils.is_valid_email(email):
                flash(trans('general_email_invalid', default='Invalid email address'), 'danger')
                logger.warning(f"Invalid email format for forgot password: {email}")
                log_audit_action('forgot_password_failed', {'email': email, 'reason': 'invalid_email_format'})
                return render_template('users/forgot_password.html', form=form, title=trans('general_send_reset_link', lang=session.get('lang', 'en')))

            db = utils.get_mongo_db()
            user = db.users.find_one({'email': email})
            if not user:
                flash(trans('general_email_not_found', default='No user found with this email'), 'danger')
                logger.warning(f"No user found with email: {email}")
                log_audit_action('forgot_password_failed', {'email': email, 'reason': 'email_not_found'})
                return render_template('users/forgot_password.html', form=form, title=trans('general_send_reset_link', lang=session.get('lang', 'en')))

            reset_token = URLSafeTimedSerializer(current_app.config['SECRET_KEY']).dumps(email, salt='reset-salt')
            expiry = datetime.utcnow() + timedelta(minutes=15)
            db.users.update_one(
                {'_id': user['_id']},
                {'$set': {'reset_token': reset_token, 'reset_token_expiry': expiry}}
            )
            mail = utils.get_mail(current_app)
            reset_url = url_for('users.reset_password', token=reset_token, _external=True)
            msg = EmailMessage(
                subject=trans('general_reset_password_subject', default='Reset Your Password'),
                body=trans('general_reset_password_body', default=f'Click the link to reset your password: {reset_url}\nLink expires in 15 minutes.'),
                to=[email]
            )
            msg.send()
            log_audit_action('forgot_password', {'email': email, 'user_id': user['_id']})
            logger.info(f"Password reset email sent to {email} for user {user['_id']}")
            flash(trans('general_reset_email_sent', default='Password reset email sent'), 'success')
            return render_template('users/forgot_password.html', form=form, title=trans('general_send_reset_link', lang=session.get('lang', 'en')))
        except errors.PyMongoError as e:
            logger.error(f"MongoDB error during forgot password for {email}: {str(e)}", exc_info=True)
            flash(trans('general_database_error', default='An error occurred while accessing the database. Please try again later.'), 'danger')
            log_audit_action('forgot_password_failed', {'email': email, 'reason': 'mongodb_error', 'error': str(e)})
            return render_template('users/forgot_password.html', form=form, title=trans('general_send_reset_link', lang=session.get('lang', 'en'))), 500
        except Exception as e:
            logger.error(f"Unexpected error during forgot password for {email}: {str(e)}", exc_info=True)
            flash(trans('general_email_send_error', default='An error occurred while sending the reset email'), 'danger')
            log_audit_action('forgot_password_failed', {'email': email, 'reason': 'unexpected_error', 'error': str(e)})
            return render_template('users/forgot_password.html', form=form, title=trans('general_send_reset_link', lang=session.get('lang', 'en'))), 500
    else:
        logger.debug(f"Forgot password form validation failed: {form.errors}, session_id: {session.get('session_id')}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", 'danger')
    return render_template('users/forgot_password.html', form=form, title=trans('general_send_reset_link', lang=session.get('lang', 'en')))

@users_bp.route('/reset_password', methods=['GET', 'POST'])
@utils.limiter.limit("50/hour")
def reset_password():
    if current_user.is_authenticated:
        try:
            logger.info(f"Authenticated user {current_user.id} redirected from reset_password, session_id: {session.get('session_id')}")
            return redirect(get_post_login_redirect(current_user.role))
        except Exception as e:
            logger.error(f"Error redirecting authenticated user in reset_password: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            return redirect(url_for('users.login')), 500

    token = request.args.get('token')
    try:
        email = URLSafeTimedSerializer(current_app.config['SECRET_KEY']).loads(token, salt='reset-salt', max_age=900)
        logger.info(f"Password reset attempt for email: {email}, session_id: {session.get('session_id')}")
    except Exception as e:
        flash(trans('general_invalid_or_expired_token', default='Invalid or expired token'), 'danger')
        logger.warning(f"Invalid or expired reset token: {str(e)}", exc_info=True)
        log_audit_action('reset_password_failed', {'reason': 'invalid_token', 'error': str(e)})
        return redirect(url_for('users.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            password = form.password.data
            if not PASSWORD_REGEX.match(password):
                flash(trans('general_password_format', default='Password must be at least 6 characters'), 'danger')
                logger.warning(f"Invalid password format during reset for email: {email}")
                log_audit_action('reset_password_failed', {'email': email, 'reason': 'invalid_password_format'})
                return render_template('users/reset_password.html', form=form, token=token, title=trans('general_reset_password', lang=session.get('lang', 'en')))

            db = utils.get_mongo_db()
            user = db.users.find_one({'email': email})
            if not user:
                flash(trans('general_invalid_email', default='No user found with this email'), 'danger')
                logger.warning(f"No user found with email: {email}")
                log_audit_action('reset_password_failed', {'email': email, 'reason': 'email_not_found'})
                return render_template('users/reset_password.html', form=form, token=token, title=trans('general_reset_password', lang=session.get('lang', 'en')))

            db.users.update_one(
                {'_id': user['_id']},
                {'$set': {'password_hash': generate_password_hash(password)},
                 '$unset': {'reset_token': '', 'reset_token_expiry': ''}}
            )
            log_audit_action('reset_password', {'user_id': user['_id'], 'email': email})
            logger.info(f"Password reset successfully for user: {user['_id']}, email: {email}")
            flash(trans('general_reset_success', default='Password reset successfully'), 'success')
            return redirect(url_for('users.login'))
        except errors.PyMongoError as e:
            logger.error(f"MongoDB error during password reset for {email}: {str(e)}", exc_info=True)
            flash(trans('general_database_error', default='An error occurred while accessing the database. Please try again later.'), 'danger')
            log_audit_action('reset_password_failed', {'email': email, 'reason': 'mongodb_error', 'error': str(e)})
            return render_template('users/reset_password.html', form=form, token=token, title=trans('general_reset_password', lang=session.get('lang', 'en'))), 500
        except Exception as e:
            logger.error(f"Unexpected error during password reset for {email}: {str(e)}", exc_info=True)
            flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
            log_audit_action('reset_password_failed', {'email': email, 'reason': 'unexpected_error', 'error': str(e)})
            return render_template('users/reset_password.html', form=form, token=token, title=trans('general_reset_password', lang=session.get('lang', 'en'))), 500
    else:
        logger.debug(f"Reset password form validation failed: {form.errors}, session_id: {session.get('session_id')}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", 'danger')
    return render_template('users/reset_password.html', form=form, token=token, title=trans('general_reset_password', lang=session.get('lang', 'en')))

@users_bp.route('/personal_setup_wizard', methods=['GET', 'POST'])
@login_required
@utils.limiter.limit("50/hour")
def personal_setup_wizard():
    try:
        db = utils.get_mongo_db()
        user_id = request.args.get('user_id', current_user.id) if utils.is_admin() and request.args.get('user_id') else current_user.id
        user = db.users.find_one({'_id': user_id})
        if not user:
            flash(trans('general_user_not_found', default='User not found'), 'danger')
            logger.warning(f"Personal setup wizard failed: User {user_id} not found, session_id: {session.get('session_id')}")
            log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'user_not_found'})
            return redirect(url_for('users.logout'))

        if user.get('setup_complete', False):
            logger.info(f"User {user_id} already completed setup, redirecting, session_id: {session.get('session_id')}")
            return redirect(get_post_login_redirect(user.get('role', 'personal')))

        form = PersonalSetupForm()
        if form.validate_on_submit():
            if form.back.data:
                flash(trans('general_setup_canceled', default='Personal setup canceled'), 'info')
                logger.info(f"Personal setup canceled for user: {user_id}, session_id: {session.get('session_id')}")
                log_audit_action('personal_setup_canceled', {'user_id': user_id, 'updated_by': current_user.id})
                return redirect(url_for('settings.profile', user_id=user_id) if utils.is_admin() else url_for('settings.profile'))

            first_name = form.first_name.data.strip()
            last_name = form.last_name.data.strip()
            phone_number = form.phone_number.data.strip()
            address = form.address.data.strip()
            language = form.language.data

            # Additional validation
            if not first_name or len(first_name) > 255:
                flash(trans('general_first_name_length', default='First name must be between 1 and 255 characters'), 'danger')
                logger.warning(f"Invalid first name length for user: {user_id}")
                log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'invalid_first_name_length'})
                return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en')))

            if not last_name or len(last_name) > 255:
                flash(trans('general_last_name_length', default='Last name must be between 1 and 255 characters'), 'danger')
                logger.warning(f"Invalid last name length for user: {user_id}")
                log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'invalid_last_name_length'})
                return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en')))

            if not PHONE_REGEX.match(phone_number):
                flash(trans('general_phone_number_format', default='Phone number must be 10-15 digits'), 'danger')
                logger.warning(f"Invalid phone number format for user: {user_id}")
                log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'invalid_phone_number_format'})
                return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en')))

            if len(address) > 500:
                flash(trans('general_address_length', default='Address must be at most 500 characters'), 'danger')
                logger.warning(f"Invalid address length for user: {user_id}")
                log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'invalid_address_length'})
                return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en')))

            if language not in ['en', 'ha']:
                flash(trans('general_language_invalid', default='Invalid language selection'), 'danger')
                logger.warning(f"Invalid language selection for user: {user_id}")
                log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'invalid_language'})
                return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en')))

            db.users.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'personal_details': {
                            'first_name': first_name,
                            'last_name': last_name,
                            'phone_number': phone_number,
                            'address': address
                        },
                        'language': language,
                        'setup_complete': True
                    }
                }
            )
            log_audit_action('complete_personal_setup_wizard', {'user_id': user_id, 'updated_by': current_user.id})
            logger.info(f"Personal setup completed for user: {user_id} by {current_user.id}, session_id: {session.get('session_id')}")
            flash(trans('general_personal_setup_success', default='Personal setup completed'), 'success')
            return redirect(url_for('settings.profile', user_id=user_id) if utils.is_admin() else get_post_login_redirect(user.get('role', 'personal')))
        else:
            logger.debug(f"Personal setup form validation failed: {form.errors}, session_id: {session.get('session_id')}")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"{field}: {error}", 'danger')
        return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en')))
    except errors.PyMongoError as e:
        logger.error(f"MongoDB error during personal setup for {user_id}: {str(e)}", exc_info=True)
        flash(trans('general_database_error', default='An error occurred while accessing the database. Please try again later.'), 'danger')
        log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'mongodb_error', 'error': str(e)})
        return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en'))), 500
    except Exception as e:
        logger.error(f"Unexpected error during personal setup for {user_id}: {str(e)}", exc_info=True)
        flash(trans('general_error', default='An error occurred. Please try again.'), 'danger')
        log_audit_action('personal_setup_failed', {'user_id': user_id, 'reason': 'unexpected_error', 'error': str(e)})
        return render_template('users/personal_setup.html', form=form, title=trans('general_personal_setup', lang=session.get('lang', 'en'))), 500

@users_bp.route('/logout')
@login_required
@utils.limiter.limit("100/hour")
def logout():
    user_id = current_user.id
    lang = session.get('lang', 'en')
    sid = session.get('session_id', 'no-session-id')
    logger.info(f"Before logout - User: {user_id}, Session: {dict(session)}, Authenticated: {current_user.is_authenticated}")
    try:
        logout_user()
        if current_app.config.get('SESSION_TYPE') == 'mongodb':
            try:
                db = utils.get_mongo_db()
                db.sessions.delete_one({'_id': sid})
                logger.info(f"Deleted MongoDB session for user {user_id}, SID: {sid}")
            except errors.PyMongoError as e:
                logger.error(f"Failed to delete MongoDB session for SID {sid}: {str(e)}", exc_info=True)
                log_audit_action('logout_failed', {'user_id': user_id, 'session_id': sid, 'reason': 'mongodb_error', 'error': str(e)})
        session.clear()
        session['lang'] = lang
        log_audit_action('logout', {'user_id': user_id, 'session_id': sid})
        logger.info(f"User {user_id} logged out successfully. After logout - Session: {dict(session)}, Authenticated: {current_user.is_authenticated}")
        response = make_response(redirect(url_for('general_bp.landing')))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.set_cookie(current_app.config['SESSION_COOKIE_NAME'], '', expires=0, httponly=True, secure=current_app.config.get('SESSION_COOKIE_SECURE', True))
        response.set_cookie('remember_token', '', expires=0, httponly=True, secure=True)
        flash(trans('general_logged_out', default='Logged out successfully'), 'success')
        return response
    except Exception as e:
        logger.error(f"Error during logout for user {user_id}: {str(e)}", exc_info=True)
        flash(trans('general_error', default='An error occurred during logout'), 'danger')
        log_audit_action('logout_failed', {'user_id': user_id, 'session_id': sid, 'reason': 'unexpected_error', 'error': str(e)})
        response = make_response(redirect(url_for('general_bp.landing')))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.set_cookie(current_app.config['SESSION_COOKIE_NAME'], '', expires=0, httponly=True, secure=current_app.config.get('SESSION_COOKIE_SECURE', True))
        response.set_cookie('remember_token', '', expires=0, httponly=True, secure=True)
        return response
