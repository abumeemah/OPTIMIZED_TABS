import os
import sys
import logging
import uuid
from datetime import datetime, timedelta
from flask import (
    Flask, jsonify, request, render_template, redirect, url_for, flash,
    make_response, session, abort, current_app
)
from flask_session import Session
from flask_cors import CORS
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from functools import wraps
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import OperationFailure
import certifi
from flask_login import LoginManager, login_required, current_user, UserMixin, logout_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from jinja2.exceptions import TemplateNotFound
import utils
from mailersend_email import init_email_config
from scheduler_setup import init_scheduler
from models import create_user, get_user_by_email, initialize_app_data
from credits.routes import credits_bp
from dashboard.routes import dashboard_bp
from users.routes import users_bp
from reports.routes import reports_bp
from settings.routes import settings_bp
from general.routes import general_bp
from admin.routes import admin_bp
from bill.bill import bill_bp
from budget.budget import budget_bp
from summaries.routes import summaries_bp
from shopping.shopping import shopping_bp

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger('ficore_app')

# Initialize Flask app
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app, resources={r"/api/*": {"origins": "*"}})
app.config.from_mapping(
    SECRET_KEY=os.getenv('SECRET_KEY'),
    SERVER_NAME=os.getenv('SERVER_NAME', '/'),
    MONGO_URI=os.getenv('MONGO_URI'),
    ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD'),
    SESSION_TYPE='mongodb',
    SESSION_PERMANENT=False,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('FLASK_ENV', 'development') == 'production',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_NAME='ficore_session',
    SUPPORTED_LANGUAGES=['en', 'ha']
)

# Validate critical configuration
for key in ['SECRET_KEY', 'MONGO_URI', 'ADMIN_PASSWORD']:
    if not app.config.get(key):
        logger.error(f'{key} environment variable is not set')
        raise ValueError(f'{key} must be set')

# Initialize MongoDB
logger.info('Initializing MongoDB client with URI: %s', app.config['MONGO_URI'])
client = MongoClient(
    app.config['MONGO_URI'],
    serverSelectionTimeoutMS=5000,
    tls=True,
    tlsCAFile=certifi.where(),
    maxPoolSize=50,
    minPoolSize=5
)
app.extensions = {'mongo': client}
try:
    client.admin.command('ping')
    logger.info('MongoDB connection successful')
except Exception as e:
    logger.error('MongoDB connection failed: %s', str(e))
    raise

# User class defined at module level
class User(UserMixin):
    def __init__(self, id, email, display_name=None, role='personal'):
        self.id = id
        self.email = email
        self.display_name = display_name or id
        self.role = role

    @property
    def is_active(self):
        user = app.extensions['mongo']['ficodb'].users.find_one({'_id': self.id})
        return user.get('is_active', True) if user else False

    def get_id(self):
        return str(self.id)
    
    def get_first_name(self):
        """Get the first name from display_name or email"""
        if self.display_name and self.display_name != self.id:
            # If display_name is set and not just the ID, use it
            return self.display_name.split()[0] if ' ' in self.display_name else self.display_name
        # Otherwise, extract from email
        return self.email.split('@')[0] if '@' in self.email else self.id


# App setup
def create_app():
    # Initialize extensions
    app.config.update(
        SESSION_MONGODB=app.extensions['mongo'],
        SESSION_MONGODB_DB='ficodb',
        SESSION_MONGODB_COLLECT='sessions'
    )
    logger.info('Configuring flask_session with MongoDB client')
    Session(app)
    CSRFProtect(app)
    login_manager = LoginManager(app)
    login_manager.login_view = 'users.login'

    # Session decorator - now requires authentication
    def ensure_session_id(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('users.login'))
            if 'sid' not in session:
                session['sid'] = str(uuid.uuid4())
                logger.info(f'New session for user {current_user.id}: {session["sid"]}')
            return f(*args, **kwargs)
        return decorated_function

    @login_manager.user_loader
    def load_user(user_id):
        user = app.extensions['mongo']['ficodb'].users.find_one({'_id': user_id})
        if not user:
            return None
        return User(
            id=user['_id'],
            email=user['email'],
            display_name=user.get('display_name', user['_id']),
            role=user.get('role', 'personal')
        )

    # Setup session
    logger.info('Creating TTL index for sessions collection')
    sessions_coll = app.extensions['mongo']['ficodb'].sessions
    desired_ttl = 1800  # 30 minutes

    # Check existing indexes
    existing_indexes = sessions_coll.list_indexes()
    for idx in existing_indexes:
        if idx.get('name') == 'created_at_1':
            if idx.get('expireAfterSeconds') != desired_ttl:
                sessions_coll.drop_index('created_at_1')
            break

    # Create the index (will succeed if dropped or matching)
    try:
        sessions_coll.create_index("created_at", expireAfterSeconds=desired_ttl)
    except OperationFailure as e:
        if 'IndexOptionsConflict' not in str(e):
            raise  # Re-raise if not the expected conflict

    # Register blueprints
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(credits_bp, url_prefix='/credits')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(bill_bp, url_prefix='/bills')
    app.register_blueprint(budget_bp, url_prefix='/budget')
    app.register_blueprint(summaries_bp, url_prefix='/summaries')
    app.register_blueprint(shopping_bp, url_prefix='/shopping')
    app.register_blueprint(general_bp, url_prefix='/general')
    
    # Initialize data
    with app.app_context():
        initialize_app_data(app)
        utils.initialize_tools_with_urls(app)
        
        # Create indexes
        db = app.extensions['mongo']['ficodb']
        for collection, indexes in [
            ('bills', [[('user_id', 1), ('due_date', 1)], [('session_id', 1), ('due_date', 1)], [('created_at', -1)], [('due_date', 1)], [('status', 1)]]),
            ('budgets', [[('user_id', 1), ('created_at', -1)], [('session_id', 1), ('created_at', -1)], [('created_at', -1)]]),
            ('bill_reminders', [[('user_id', 1), ('sent_at', -1)], [('notification_id', 1)]]),
            ('shopping_lists', [[('user_id', 1), ('created_at', -1)], [('session_id', 1), ('created_at', -1)]]),
            ('shopping_items', [[('user_id', 1), ('list_id', 1)], [('session_id', 1), ('list_id', 1)]]),
            ('ficore_credit_transactions', [[('user_id', 1), ('timestamp', DESCENDING)]])
        ]:
            for index in indexes:
                db[collection].create_index(index)
        
        # Setup admin user
        admin_email = os.getenv('ADMIN_EMAIL', 'ficoreaiafrica@gmail.com')
        admin_password = os.getenv('ADMIN_PASSWORD')
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        
        # Hash the password before checking and updating
        hashed_password = generate_password_hash(admin_password)

        if not get_user_by_email(db, admin_email):
            create_user(db, {
                '_id': admin_username.lower(),
                'username': admin_username.lower(),
                'email': admin_email.lower(),
                'password': hashed_password,
                'is_admin': True,
                'role': 'admin',
                'created_at': datetime.utcnow(),
                'lang': 'en',
                'setup_complete': True,
                'display_name': admin_username
            })
        else:
            db.users.update_one(
                {'_id': admin_username.lower()},
                {'$set': {'password': hashed_password}}
            )

    # Template filters and context processors

    # Add 't' as an alias for 'trans' for backwards compatibility in templates
    app.jinja_env.globals.update(
        trans=utils.trans_function,
        t=utils.trans_function,  # Ensure 't' is available in Jinja templates
        format_currency=utils.format_currency,
        format_date=utils.format_date,
        is_admin=utils.is_admin,
        FACEBOOK_URL=app.config.get('FACEBOOK_URL', 'https://facebook.com/ficoreafrica'),
        TWITTER_URL=app.config.get('TWITTER_URL', 'https://x.com/ficoreafrica'),
        LINKEDIN_URL=app.config.get('LINKEDIN_URL', 'https://linkedin.com/company/ficoreafrica')
    )

    @app.template_filter('format_number')
    def format_number(value):
        try:
            return f'{float(value):,.2f}' if isinstance(value, (int, float)) else str(value)
        except (ValueError, TypeError):
            return str(value)

    @app.template_filter('format_datetime')
    def format_datetime(value):
        format_str = '%B %d, %Y, %I:%M %p' if session.get('lang', 'en') == 'en' else '%d %B %Y, %I:%M %p'
        try:
            if isinstance(value, datetime):
                return value.strftime(format_str)
            elif isinstance(value, str):
                return datetime.strptime(value, '%Y-%m-%d').strftime(format_str)
            return str(value)
        except Exception:
            return str(value)

    @app.template_filter('format_date')
    def format_date(value):
        return utils.format_date(value)

    @app.template_filter('format_currency')
    def format_currency(value):
        return utils.format_currency(value)

    @app.context_processor
    def inject_globals():
        lang = session.get('lang', 'en')
        from flask_login import current_user
        
        # Get role-specific navigation and tools
        if current_user.is_authenticated:
            if current_user.role == 'personal':
                tools_for_template = utils.PERSONAL_TOOLS
                explore_features_for_template = utils.PERSONAL_EXPLORE_FEATURES
                bottom_nav_items = utils.PERSONAL_NAV
            elif current_user.role == 'admin':
                tools_for_template = utils.ADMIN_TOOLS
                explore_features_for_template = utils.ADMIN_EXPLORE_FEATURES
                bottom_nav_items = utils.ADMIN_NAV
            else:
                tools_for_template = []
                explore_features_for_template = []
                bottom_nav_items = []
        else:
            # For unauthenticated users, show limited features
            tools_for_template = []
            explore_features_for_template = utils.get_explore_features()
            bottom_nav_items = []
        
        return {
            'trans': utils.trans_function,
            't': utils.trans_function,  # Ensure 't' is available everywhere
            'current_lang': lang,
            'available_languages': [
                {'code': code, 'name': utils.trans_function(f'lang_{code}', lang=lang, default=code.capitalize())}
                for code in app.config['SUPPORTED_LANGUAGES']
            ],
            'tools_for_template': tools_for_template,
            'explore_features_for_template': explore_features_for_template,
            'bottom_nav_items': bottom_nav_items
        }

    # Routes
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.role == 'admin':
                return redirect(url_for('dashboard.index'))
            return redirect(url_for('general_bp.home'))
        return redirect(url_for('general_bp.landing'))

    @app.route('/change-language', methods=['POST'])
    def change_language():
        data = request.get_json()
        new_lang = data.get('language', 'en')
        if new_lang in app.config['SUPPORTED_LANGUAGES']:
            session['lang'] = new_lang
            if current_user.is_authenticated:
                app.extensions['mongo']['ficodb'].users.update_one(
                    {'_id': current_user.id},
                    {'$set': {'language': new_lang}}
                )
            return jsonify({'success': True, 'message': utils.trans_function('lang_change_success', lang=new_lang)})
        return jsonify({'success': False, 'message': utils.trans_function('lang_invalid')}), 400

    @app.route('/set-language/<lang>')
    def set_language(lang):
        """Set the session language."""
        if lang in app.config['SUPPORTED_LANGUAGES']:
            session['lang'] = lang
            if current_user.is_authenticated:
                app.extensions['mongo']['ficodb'].users.update_one(
                    {'_id': current_user.id},
                    {'$set': {'language': lang}}
                )
        return redirect(request.referrer or url_for('home'))

    @app.route('/health')
    def health():
        try:
            app.extensions['mongo'].admin.command('ping')
            return jsonify({'status': 'healthy'}), 200
        except Exception as e:
            return jsonify({'status': 'unhealthy', 'dependencies': str(e)}), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return render_template(
            'errors/403.html',
            error=utils.trans_function('csrf_error'),
            title=utils.trans_function('csrf_error', lang=session.get('lang', 'en'))
        ), 400

    @app.errorhandler(404)
    def page_not_found(e):
        # Ensure 't' is always in template context
        return render_template(
            'errors/404.html',
            error=str(e),
            title=utils.trans_function('not_found', lang=session.get('lang', 'en'))
        ), 404

    logger.info('MongoDB client initialized')
    return app

app = create_app()

if __name__ == '__main__':
    logger.info('Starting Flask application')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
