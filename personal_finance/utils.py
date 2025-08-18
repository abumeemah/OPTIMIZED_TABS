import re
import logging
import uuid
import os
import certifi
from datetime import datetime
from flask import session, has_request_context, current_app, url_for, request
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from werkzeug.routing import BuildError
from translations import trans
import time
from wtforms import ValidationError

# Flask extensions
from flask_login import LoginManager
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

# Initialize extensions
login_manager = LoginManager()
flask_session = Session()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=['200 per day', '50 per hour'], storage_uri='memory://')

# Set up logging with session support
root_logger = logging.getLogger('ficore_app')
root_logger.setLevel(logging.DEBUG)

class SessionFormatter(logging.Formatter):
    def format(self, record):
        record.session_id = getattr(record, 'session_id', 'no_session_id')
        record.ip_address = getattr(record, 'ip_address', 'unknown')
        record.user_role = getattr(record, 'user_role', 'anonymous')
        return super().format(record)

class SessionAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        kwargs['extra'] = kwargs.get('extra', {})
        session_id = 'no-session-id'
        ip_address = 'unknown'
        user_role = 'anonymous'
        try:
            if has_request_context():
                session_id = session.get('sid', 'no-session-id')
                ip_address = request.remote_addr
                user_role = current_user.role if current_user.is_authenticated else 'anonymous'
            else:
                session_id = f'non-request-{str(uuid.uuid4())[:8]}'
        except Exception as e:
            session_id = f'session-error-{str(uuid.uuid4())[:8]}'
            kwargs['extra']['session_error'] = str(e)
        kwargs['extra']['session_id'] = session_id
        kwargs['extra']['ip_address'] = ip_address
        kwargs['extra']['user_role'] = user_role
        return msg, kwargs

logger = SessionAdapter(root_logger, {})

# Tool/navigation lists with endpoints
_PERSONAL_TOOLS = [
    {
        "endpoint": "budget.main",
        "label": "Budget",
        "label_key": "budget_budget_planner",
        "description_key": "budget_budget_desc",
        "tooltip_key": "budget_tooltip",
        "icon": "bi-wallet"
    },
    {
        "endpoint": "bill.main",
        "label": "Bills",
        "label_key": "bill_bill_planner",
        "description_key": "bill_bill_desc",
        "tooltip_key": "bill_tooltip",
        "icon": "bi-receipt"
    },
    {
        "endpoint": "shopping.main",
        "label": "Shopping",
        "label_key": "shopping_management",
        "description_key": "shopping_management_desc",
        "tooltip_key": "shopping_tooltip",
        "icon": "bi-cart"
    },
]

_PERSONAL_NAV = [
    {
        "endpoint": "general_bp.home",
        "label": "Home",
        "label_key": "general_home",
        "description_key": "general_home_desc",
        "tooltip_key": "general_home_tooltip",
        "icon": "bi-house"
    },
    {
        "endpoint": "budget.main",
        "label": "Budget",
        "label_key": "budget_budget_planner",
        "description_key": "budget_budget_desc",
        "tooltip_key": "budget_tooltip",
        "icon": "bi-wallet"
    },
    {
        "endpoint": "bill.main",
        "label": "Bills",
        "label_key": "bill_bill_planner",
        "description_key": "bill_bill_desc",
        "tooltip_key": "bill_tooltip",
        "icon": "bi-receipt"
    },
    {
        "endpoint": "shopping.main",
        "label": "Shopping",
        "label_key": "shopping_management",
        "description_key": "shopping_management_desc",
        "tooltip_key": "shopping_tooltip",
        "icon": "bi-cart"
    },
    {
        "endpoint": "settings.profile",
        "label": "Profile",
        "label_key": "profile_settings",
        "description_key": "profile_settings_desc",
        "tooltip_key": "profile_tooltip",
        "icon": "bi-person"
    },
]

_PERSONAL_EXPLORE_FEATURES = [
    {
        "endpoint": "budget.main",
        "label": "Budget",
        "label_key": "budget_budget_planner",
        "description_key": "budget_budget_desc",
        "tooltip_key": "budget_tooltip",
        "icon": "bi-wallet"
    },
    {
        "endpoint": "bill.main",
        "label": "Bills",
        "label_key": "bill_bill_planner",
        "description_key": "bill_bill_desc",
        "tooltip_key": "bill_tooltip",
        "icon": "bi-receipt"
    },
    {
        "endpoint": "shopping.main",
        "label": "Shopping",
        "label_key": "shopping_management",
        "description_key": "shopping_management_desc",
        "tooltip_key": "shopping_tooltip",
        "icon": "bi-cart"
    },
]

_ADMIN_TOOLS = [
    {
        "endpoint": "admin.dashboard",
        "label": "Dashboard",
        "label_key": "admin_dashboard",
        "description_key": "admin_dashboard_desc",
        "tooltip_key": "admin_dashboard_tooltip",
        "icon": "bi-speedometer"
    },
    {
        "endpoint": "admin.manage_users",
        "label": "Manage Users",
        "label_key": "admin_manage_users",
        "description_key": "admin_manage_users_desc",
        "tooltip_key": "admin_manage_users_tooltip",
        "icon": "bi-people"
    },
]

_ADMIN_NAV = [
    {
        "endpoint": "admin.dashboard",
        "label": "Dashboard",
        "label_key": "admin_dashboard",
        "description_key": "admin_dashboard_desc",
        "tooltip_key": "admin_dashboard_tooltip",
        "icon": "bi-speedometer"
    },
    {
        "endpoint": "admin.manage_users",
        "label": "Manage Users",
        "label_key": "admin_manage_users",
        "description_key": "admin_manage_users_desc",
        "tooltip_key": "admin_manage_users_tooltip",
        "icon": "bi-people"
    },
    {
        "endpoint": "admin.admin_budgets",
        "label": "Manage Budgets",
        "label_key": "admin_manage_budgets",
        "description_key": "admin_manage_budgets_desc",
        "tooltip_key": "admin_manage_budgets_tooltip",
        "icon": "bi-wallet"
    },
    {
        "endpoint": "admin.admin_bills",
        "label": "Manage Bills",
        "label_key": "admin_manage_bills",
        "description_key": "admin_manage_bills_desc",
        "tooltip_key": "admin_manage_bills_tooltip",
        "icon": "bi-receipt"
    },
]

_ADMIN_EXPLORE_FEATURES = [
    {
        "endpoint": "admin.dashboard",
        "label": "Dashboard",
        "label_key": "admin_dashboard",
        "description_key": "admin_dashboard_desc",
        "tooltip_key": "admin_dashboard_tooltip",
        "icon": "bi-speedometer"
    },
    {
        "endpoint": "admin.manage_users",
        "label": "Manage Users",
        "label_key": "admin_manage_users",
        "description_key": "admin_manage_users_desc",
        "tooltip_key": "admin_manage_users_tooltip",
        "icon": "bi-people"
    },
    {
        "endpoint": "admin.admin_budgets",
        "label": "Manage Budgets",
        "label_key": "admin_manage_budgets",
        "description_key": "admin_manage_budgets_desc",
        "tooltip_key": "admin_manage_budgets_tooltip",
        "icon": "bi-wallet"
    },
    {
        "endpoint": "admin.admin_bills",
        "label": "Manage Bills",
        "label_key": "admin_manage_bills",
        "description_key": "admin_manage_bills_desc",
        "tooltip_key": "admin_manage_bills_tooltip",
        "icon": "bi-receipt"
    },
]

def get_explore_features():
    """Return explore features for unauthenticated users on the landing page with resolved URLs and ensured label_key."""
    try:
        with current_app.app_context():
            features = [
                {
                    "endpoint": "budget.main",
                    "label": "Budget",
                    "label_key": "budget_budget_planner",
                    "description_key": "budget_budget_desc",
                    "tooltip_key": "budget_tooltip",
                    "icon": "bi-wallet",
                    "category": "Personal"
                },
                {
                    "endpoint": "bill.main",
                    "label": "Bills",
                    "label_key": "bill_bill_planner",
                    "description_key": "bill_bill_desc",
                    "tooltip_key": "bill_tooltip",
                    "icon": "bi-receipt",
                    "category": "Personal"
                },
                {
                    "endpoint": "shopping.main",
                    "label": "Shopping",
                    "label_key": "shopping_management",
                    "description_key": "shopping_management_desc",
                    "tooltip_key": "shopping_tooltip",
                    "icon": "bi-cart",
                    "category": "Personal"
                },
            ]
            required_keys = ['endpoint', 'label', 'label_key', 'description_key', 'tooltip_key', 'icon']
            for feature in features:
                for key in required_keys:
                    if key not in feature:
                        default_value = feature.get('label', 'default_feature').lower().replace(' ', '_') + f'_{key}' if key == 'label_key' else 'default_' + key
                        feature[key] = default_value
                        logger.warning(
                            f"Missing {key} for feature {feature.get('label', 'unknown')}, assigned default: {feature[key]}",
                            extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr if has_request_context() else 'unknown'}
                        )
            return generate_tools_with_urls(features)
    except Exception as e:
        logger.error(f"Error generating explore features: {str(e)}", exc_info=True)
        return []

# Initialize module-level variables
PERSONAL_TOOLS = []
PERSONAL_NAV = []
PERSONAL_EXPLORE_FEATURES = []
ADMIN_TOOLS = []
ADMIN_NAV = []
ADMIN_EXPLORE_FEATURES = []
ALL_TOOLS = []

def initialize_tools_with_urls(app):
    """
    Initialize all tool/navigation lists with resolved URLs.
    
    Args:
        app: Flask application instance
    """
    global PERSONAL_TOOLS, PERSONAL_NAV, PERSONAL_EXPLORE_FEATURES
    global ADMIN_TOOLS, ADMIN_NAV, ADMIN_EXPLORE_FEATURES
    global ALL_TOOLS
    
    try:
        with app.app_context():
            PERSONAL_TOOLS = generate_tools_with_urls(_PERSONAL_TOOLS)
            PERSONAL_NAV = generate_tools_with_urls(_PERSONAL_NAV)
            PERSONAL_EXPLORE_FEATURES = generate_tools_with_urls(_PERSONAL_EXPLORE_FEATURES)
            ADMIN_TOOLS = generate_tools_with_urls(_ADMIN_TOOLS)
            ADMIN_NAV = generate_tools_with_urls(_ADMIN_NAV)
            ADMIN_EXPLORE_FEATURES = generate_tools_with_urls(_ADMIN_EXPLORE_FEATURES)
            ALL_TOOLS = (
                PERSONAL_TOOLS +
                ADMIN_TOOLS +
                generate_tools_with_urls([{
                    "endpoint": "admin.dashboard",
                    "label": "Management",
                    "label_key": "admin_dashboard",
                    "description_key": "admin_dashboard_desc",
                    "tooltip_key": "admin_dashboard_tooltip",
                    "icon": "bi-speedometer"
                }])
            )
            logger.info('Initialized tools and navigation with resolved URLs')
    except Exception as e:
        logger.error(f'Error initializing tools with URLs: {str(e)}', exc_info=True)
        raise

def generate_tools_with_urls(tools):
    """
    Generate a list of tools with resolved URLs and validated icons.
    
    Args:
        tools: List of dictionaries containing 'endpoint' and 'icon' keys
    
    Returns:
        List of dictionaries with 'url' keys added and validated 'icon' fields
    """
    result = []
    for tool in tools:
        try:
            url = url_for(tool['endpoint'], _external=True)
            icon = tool.get('icon', 'bi-question-circle')
            if not icon or not icon.startswith('bi-'):
                logger.warning(f"Invalid or missing icon for tool {tool.get('label', 'unknown')}: {icon}. Using fallback 'bi-question-circle'.")
                icon = 'bi-question-circle'
            result.append({**tool, 'url': url, 'icon': icon})
        except BuildError as e:
            logger.warning(f"Failed to generate URL for endpoint {tool.get('endpoint', 'unknown')}: {str(e)}. Ensure endpoint is defined in blueprint.")
            result.append({**tool, 'url': '#', 'icon': tool.get('icon', 'bi-question-circle')})
        except RuntimeError as e:
            logger.warning(f"Runtime error generating URL for endpoint {tool.get('endpoint', 'unknown')}: {str(e)}")
            result.append({**tool, 'url': '#', 'icon': tool.get('icon', 'bi-question-circle')})
    return result

def get_limiter():
    """
    Return the initialized Flask-Limiter instance.
    
    Returns:
        Limiter: The configured Flask-Limiter instance
    """
    return limiter

def log_tool_usage(action, tool_name=None, details=None, user_id=None, db=None, session_id=None):
    """
    Log tool usage to MongoDB tool_usage collection with improved error handling and session support.
    Now requires user_id for all tool usage logging.
    
    Args:
        action (str): The action performed (e.g., 'main_view', 'add_bill').
        tool_name (str, optional): The name of the tool used. Defaults to action if None.
        details (dict, optional): Additional details about the action.
        user_id (str, required): ID of the user performing the action.
        db (MongoDB database, optional): MongoDB database instance. If None, fetched via get_mongo_db().
        session_id (str, optional): Session ID for the action.
    
    Raises:
        RuntimeError: If database connection fails or insertion fails.
        ValueError: If user_id is not provided.
    """
    try:
        if db is None:
            db = get_mongo_db()
        
        if not action or not isinstance(action, str):
            raise ValueError("Action must be a non-empty string")
        
        if not user_id:
            raise ValueError("user_id is required for tool usage logging")
        
        effective_session_id = session_id or session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'
        
        log_entry = {
            'tool_name': tool_name or action,
            'user_id': str(user_id),
            'session_id': effective_session_id,
            'action': details.get('action') if details else None,
            'timestamp': datetime.utcnow(),
            'ip_address': request.remote_addr if has_request_context() else 'unknown',
            'user_agent': request.headers.get('User-Agent') if has_request_context() else 'unknown'
        }
        
        db.tool_usage.insert_one(log_entry)
        logger.info(
            f"Logged tool usage: {action}",
            extra={
                'user_id': user_id,
                'session_id': effective_session_id,
                'ip_address': request.remote_addr if has_request_context() else 'unknown'
            }
        )
    except ValueError as e:
        logger.error(
            f"Invalid input for log_tool_usage: {str(e)}",
            exc_info=True,
            extra={
                'user_id': user_id or 'unknown',
                'session_id': session_id or session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id',
                'ip_address': request.remote_addr if has_request_context() else 'unknown'
            }
        )
        raise
    except Exception as e:
        logger.error(
            f"Failed to log tool usage for action {action}: {str(e)}",
            exc_info=True,
            extra={
                'user_id': user_id or 'unknown',
                'session_id': session_id or session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id',
                'ip_address': request.remote_addr if has_request_context() else 'unknown'
            }
        )
        raise RuntimeError(f"Failed to log tool usage: {str(e)}")

# All users must be authenticated - no anonymous sessions


def clean_currency(value, max_value=10000000000):
    """
    Clean currency input by removing non-numeric characters, handling various currency formats and edge cases.
    
    Args:
        value: Input value to clean (str, int, float, or None)
        max_value: Maximum allowed value (default: 10 billion)
    
    Returns:
        float: Cleaned numeric value
    
    Raises:
        ValidationError: If the input cannot be converted to a valid float or exceeds max_value
    """
    try:
        # Handle None or empty inputs
        if value is None or str(value).strip() == '':
            logger.debug(
                "clean_currency received empty or None input, returning 0.0",
                extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
            )
            return 0.0

        # Handle numeric inputs (int or float) directly
        if isinstance(value, (int, float)):
            result = float(value)
            if result < 0:
                logger.warning(
                    f"Negative currency value not allowed: value={result}",
                    extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
                )
                raise ValidationError(trans('negative_currency_not_allowed', default='Negative currency values are not allowed', lang=get_user_language()))
            if result > max_value:
                logger.warning(
                    f"Currency value exceeds maximum: value={result}, max_value={max_value}",
                    extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
                )
                raise ValidationError(trans('bill_amount_max', default=f"Input cannot exceed {max_value:,}", lang=get_user_language()))
            return result

        # Convert to string and clean formatting
        value_str = str(value).strip()
        logger.debug(
            f"clean_currency processing input: '{value_str}'",
            extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
        )
        
        # Remove currency symbols, commas, and other formatting characters, keeping digits and decimal point
        cleaned = re.sub(r'[^\d.]', '', value_str)
        
        # Handle multiple decimal points - keep only the first one
        if cleaned.count('.') > 1:
            parts = cleaned.split('.')
            cleaned = parts[0] + '.' + ''.join(parts[1:])
        
        # Validate cleaned value
        if not cleaned or cleaned == '.':
            logger.warning(
                f"Invalid currency format after cleaning: original='{value_str}', cleaned='{cleaned}'",
                extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
            )
            raise ValidationError(trans('invalid_currency_format', default='Invalid currency format', lang=get_user_language()))
            
        # Convert to float
        result = float(cleaned)
        
        # Validate range
        if result < 0:
            logger.warning(
                f"Negative currency value not allowed: original='{value_str}', result={result}",
                extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
            )
            raise ValidationError(trans('negative_currency_not_allowed', default='Negative currency values are not allowed', lang=get_user_language()))
        
        if result > max_value:
            logger.warning(
                f"Currency value exceeds maximum: original='{value_str}', result={result}, max_value={max_value}",
                extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
            )
            raise ValidationError(trans('bill_amount_max', default=f"Input cannot exceed {max_value:,}", lang=get_user_language()))

        logger.debug(
            f"clean_currency successfully processed '{value_str}' to {result}",
            extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
        )
        return result

    except (ValueError, ValidationError) as e:
        logger.warning(
            f"Currency format error: original='{value}', error='{str(e)}'",
            extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
        )
        raise ValidationError(trans('invalid_currency_format', default='Invalid currency format', lang=get_user_language())) from e
    except Exception as e:
        logger.error(
            f"Unexpected error in clean_currency for value '{value}': {str(e)}",
            extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
        )
        raise ValidationError(trans('invalid_currency_format', default='Invalid currency format', lang=get_user_language())) from e

def trans_function(key, lang=None, **kwargs):
    """
    Translation function wrapper for backward compatibility.
    
    Args:
        key: Translation key
        lang: Language code ('en', 'ha'). Defaults to session['lang'] or 'en'
        **kwargs: String formatting parameters
    
    Returns:
        Translated string with formatting applied
    """
    try:
        with current_app.app_context():
            translated = trans(key, lang=lang, **kwargs)
            if translated == key:  # Translation missing
                logger.warning(
                    f"Missing translation for key='{key}' in module='general', lang='{lang or session.get('lang', 'en')}'",
                    extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
                )
                return key  # Fallback to the key itself
            return translated
    except Exception as e:
        logger.error(
            f"Translation error for key '{key}': {str(e)}",
            exc_info=True,
            extra={'session_id': session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'}
        )
        return key  # Fallback to the key itself

def is_valid_email(email):
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
    
    Returns:
        bool: True if email is valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email.strip()) is not None

def get_mongo_db():
    """
    Get MongoDB database instance with retry logic.
    
    Returns:
        Database object
    """
    max_retries = 3
    retry_delay = 1
    for attempt in range(max_retries):
        try:
            with current_app.app_context():
                if 'mongo' not in current_app.extensions:
                    mongo_uri = os.getenv('MONGO_URI')
                    if not mongo_uri:
                        logger.error("MONGO_URI environment variable not set",
                                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr if has_request_context() else 'unknown'})
                        raise RuntimeError("MONGO_URI environment variable not set")
                    
                    client = MongoClient(
                        mongo_uri,
                        serverSelectionTimeoutMS=5000,
                        tls=True,
                        tlsCAFile=certifi.where() if os.getenv('MONGO_CA_FILE') is None else os.getenv('MONGO_CA_FILE'),
                        maxPoolSize=50,
                        minPoolSize=5
                    )
                    client.admin.command('ping')
                    current_app.extensions['mongo'] = client
                    logger.info("MongoDB client initialized successfully in utils.get_mongo_db",
                               extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr if has_request_context() else 'unknown'})
                
                db = current_app.extensions['mongo']['ficodb']
                db.command('ping')
                return db
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(
                f"Attempt {attempt + 1}/{max_retries} failed to connect to MongoDB: {str(e)}",
                exc_info=True,
                extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr if has_request_context() else 'unknown'}
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to connect to MongoDB after {max_retries} attempts: {str(e)}",
                    exc_info=True,
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr if has_request_context() else 'unknown'}
                )
                raise RuntimeError(f"Failed to connect to MongoDB: {str(e)}")
            time.sleep(retry_delay)
    raise RuntimeError("Failed to connect to MongoDB after retries")

def close_mongo_db():
    """
    No-op function for backward compatibility.
    """
    pass

def get_mail(app):
    """
    Initialize and return Flask-Mail instance.
    
    Args:
        app: Flask application instance
    
    Returns:
        Mail instance
    """
    try:
        with app.app_context():
            mail = Mail(app)
            logger.info(trans('general_mail_service_initialized', default='Mail service initialized'))
            return mail
    except Exception as e:
        logger.error(f"{trans('general_mail_service_error', default='Error initializing mail service')}: {str(e)}", exc_info=True)
        return None

def requires_role(role):
    """
    Decorator to require specific user role.
    
    Args:
        role: Required role (e.g., 'admin', 'personal') or list of roles
    
    Returns:
        Decorator function
    """
    def decorator(f):
        from functools import wraps
        from flask_login import current_user
        from flask import redirect, url_for, flash
        
        @wraps(f)
        def decorated_function(*args, **kwargs):
            with current_app.app_context():
                if not current_user.is_authenticated:
                    flash(trans('general_login_required', default='Please log in to access this page.'), 'warning')
                    return redirect(url_for('users.login'))
                if is_admin():
                    return f(*args, **kwargs)
                allowed_roles = role if isinstance(role, list) else [role]
                if current_user.role not in allowed_roles:
                    flash(trans('general_access_denied', default='You do not have permission to access this page.'), 'danger')
                    return redirect(url_for('dashboard.index'))
                return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_user_query(user_id):
    """
    Get user query for MongoDB operations.
    
    Args:
        user_id: User ID
    
    Returns:
        dict: MongoDB query for user
    """
    return {'_id': user_id}

def is_admin():
    """
    Check if current user is admin.
    
    Returns:
        bool: True if current user is admin, False otherwise
    """
    try:
        with current_app.app_context():
            from flask_login import current_user
            return current_user.is_authenticated and (current_user.role == 'admin' or getattr(current_user, 'is_admin', False))
    except Exception:
        return False

def format_currency(amount, currency='₦', lang=None, include_symbol=True):
    """
    Format currency amount with proper locale.
    
    Args:
        amount: Amount to format
        currency: Currency symbol (default: '₦')
        lang: Language code for formatting
        include_symbol: Whether to include the currency symbol (default: True)
    
    Returns:
        Formatted currency string
    """
    try:
        with current_app.app_context():
            if lang is None:
                lang = session.get('lang', 'en') if has_request_context() else 'en'
            amount = clean_currency(amount) if isinstance(amount, str) else float(amount) if amount is not None else 0
            if amount.is_integer():
                formatted = f"{int(amount):,}"
            else:
                formatted = f"{amount:,.2f}"
            return f"{currency}{formatted}" if include_symbol else formatted
    except (TypeError, ValueError, ValidationError) as e:
        logger.warning(f"{trans('general_currency_format_error', default='Error formatting currency')} {amount}: {str(e)}")
        return f"{currency}0" if include_symbol else "0"

def format_date(date_obj, lang=None, format_type='short'):
    """
    Format date according to language preference.
    
    Args:
        date_obj: Date object to format
        lang: Language code
        format_type: 'short', 'long', or 'iso'
    
    Returns:
        Formatted date string
    """
    try:
        with current_app.app_context():
            if lang is None:
                lang = session.get('lang', 'en') if has_request_context() else 'en'
            if not date_obj:
                return ''
            if isinstance(date_obj, str):
                try:
                    date_obj = datetime.strptime(date_obj, '%Y-%m-%d')
                except ValueError:
                    try:
                        date_obj = datetime.fromisoformat(date_obj.replace('Z', '+00:00'))
                    except ValueError:
                        return date_obj
            if format_type == 'iso':
                return date_obj.strftime('%Y-%m-%d')
            elif format_type == 'long':
                if lang == 'ha':
                    return date_obj.strftime('%d %B %Y')
                else:
                    return date_obj.strftime('%B %d, %Y')
            else:
                if lang == 'ha':
                    return date_obj.strftime('%d/%m/%Y')
                else:
                    return date_obj.strftime('%m/%d/%Y')
    except Exception as e:
        logger.warning(f"{trans('general_date_format_error', default='Error formatting date')} {date_obj}: {str(e)}")
        return str(date_obj) if date_obj else ''

def sanitize_input(input_string, max_length=None):
    """
    Sanitize user input to prevent XSS and other attacks.
    
    Args:
        input_string: String to sanitize
        max_length: Maximum allowed length
    
    Returns:
        Sanitized string
    """
    if not input_string:
        return ''
    sanitized = str(input_string).strip()
    sanitized = re.sub(r'[<>"\']', '', sanitized)
    if max_length and len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    return sanitized

def generate_unique_id(prefix=''):
    """
    Generate a unique identifier.
    
    Args:
        prefix: Optional prefix for the ID
    
    Returns:
        Unique identifier string
    """
    unique_id = str(uuid.uuid4())
    if prefix:
        return f"{prefix}_{unique_id}"
    return unique_id

def validate_required_fields(data, required_fields):
    """
    Validate that all required fields are present and not empty.
    
    Args:
        data: Dictionary of data to validate
        required_fields: List of required field names
    
    Returns:
        tuple: (is_valid, missing_fields)
    """
    missing_fields = []
    for field in required_fields:
        if field not in data or not data[field] or str(data[field]).strip() == '':
            missing_fields.append(field)
    return len(missing_fields) == 0, missing_fields

def get_user_language():
    """
    Get the current user's language preference.
    
    Returns:
        Language code ('en' or 'ha')
    """
    try:
        with current_app.app_context():
            return session.get('lang', 'en') if has_request_context() else 'en'
    except Exception:
        return 'en'

def log_user_action(action, details=None, user_id=None):
    """
    Log user action for audit purposes.
    
    Args:
        action: Action performed
        details: Additional details about the action
        user_id: User ID (optional, will use current_user if not provided)
    """
    try:
        with current_app.app_context():
            from flask_login import current_user
            from flask import request
            if user_id is None and current_user.is_authenticated:
                user_id = current_user.id
            session_id = session.get('sid', 'no-session-id') if has_request_context() else 'no-session-id'
            log_entry = {
                'user_id': user_id,
                'session_id': session_id,
                'action': action,
                'details': details or {},
                'timestamp': datetime.utcnow(),
                'ip_address': request.remote_addr if has_request_context() else None,
                'user_agent': request.headers.get('User-Agent') if has_request_context() else None
            }
            db = get_mongo_db()
            if db:
                db.audit_logs.insert_one(log_entry)
            logger.info(f"{trans('general_user_action_logged', default='User action logged')}: {action} by user {user_id}")
    except Exception as e:
        logger.error(f"{trans('general_user_action_log_error', default='Error logging user action')}: {str(e)}", exc_info=True)

def get_recent_activities(user_id=None, is_admin_user=False, db=None, session_id=None, limit=10):
    """
    Fetch recent activities across all tools for a user or session.
    
    Args:
        user_id: ID of the user (optional for admin)
        is_admin_user: Whether the user is an admin (default: False)
        db: MongoDB database instance (optional)
        session_id: Session ID for anonymous users (optional)
        limit: Maximum number of activities to return (default: 10)
    
    Returns:
        list: List of recent activity records
    """
    if db is None:
        db = get_mongo_db()
    
    query = {} if is_admin_user else {'user_id': str(user_id)} if user_id else {'session_id': session_id} if session_id else {}
    
    try:
        activities = []
        
        # Fetch recent bills
        bills = db.bills.find(query).sort('created_at', -1).limit(5)
        for bill in bills:
            if not bill.get('created_at') or not bill.get('bill_name'):
                logger.warning(f"Skipping invalid bill record: {bill.get('_id')}", extra={'session_id': session_id or 'unknown', 'ip': request.remote_addr or 'unknown'})
                continue
            activities.append({
                'type': 'bill',
                'description': trans('recent_activity_bill_added', default='Added bill: {name}', name=bill.get('bill_name', 'Unknown')),
                'timestamp': bill.get('created_at', datetime.utcnow()).isoformat(),
                'details': {
                    'amount': bill.get('amount', 0),
                    'due_date': bill.get('due_date', 'N/A'),
                    'status': bill.get('status', 'Unknown')
                },
                'icon': 'bi-receipt'
            })

        # Fetch recent budgets
        budgets = db.budgets.find(query).sort('created_at', -1).limit(5)
        for budget in budgets:
            activities.append({
                'type': 'budget',
                'description': trans('recent_activity_budget_created', default='Created budget with income: {amount}', amount=budget.get('income', 0)),
                'timestamp': budget.get('created_at', datetime.utcnow()).isoformat(),
                'details': {
                    'income': budget.get('income', 0),
                    'surplus_deficit': budget.get('surplus_deficit', 0)
                },
                'icon': 'bi-cash-coin'
            })

        # Fetch recent shopping lists
        shopping_lists = db.shopping_lists.find(query).sort('created_at', -1).limit(5)
        for list_item in shopping_lists:
            activities.append({
                'type': 'shopping_list',
                'description': trans('recent_activity_shopping_list_created', default='Created shopping list: {name}', name=list_item.get('name', 'Unknown')),
                'timestamp': list_item.get('created_at', datetime.utcnow()).isoformat(),
                'details': {
                    'budget': list_item.get('budget', 0),
                    'total_spent': list_item.get('total_spent', 0)
                },
                'icon': 'bi-cart'
            })

        # Fetch recent shopping items
        shopping_items = db.shopping_items.find(query).sort('created_at', -1).limit(5)
        for item in shopping_items:
            activities.append({
                'type': 'shopping_item',
                'description': trans('recent_activity_shopping_item_added', default='Added shopping item: {name}', name=item.get('name', 'Unknown')),
                'timestamp': item.get('created_at', datetime.utcnow()).isoformat(),
                'details': {
                    'quantity': item.get('quantity', 0),
                    'price': item.get('price', 0),
                    'status': item.get('status', 'to_buy')
                },
                'icon': 'bi-check-circle'
            })

        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        
        logger.debug(
            f"Fetched {len(activities)} recent activities for {'user ' + str(user_id) if user_id else 'session ' + str(session_id) if session_id else 'all'}",
            extra={'session_id': session_id or 'unknown', 'ip': request.remote_addr or 'unknown'}
        )
        
        return activities[:limit]
    except Exception as e:
        logger.error(
            f"Failed to fetch recent activities: {str(e)}",
            exc_info=True,
            extra={'session_id': session_id or 'unknown', 'ip': request.remote_addr or 'unknown'}
        )
        raise

def get_all_recent_activities(user_id=None, is_admin_user=False, db=None, session_id=None, limit=10):
    """
    Fetch recent activities across all tools for a user or session.
    
    Args:
        user_id: ID of the user (optional for admin)
        is_admin_user: Whether the user is an admin (default: False)
        db: MongoDB database instance (optional)
        session_id: Session ID for anonymous users (optional)
        limit: Maximum number of activities to return (default: 10)
    
    Returns:
        list: List of recent activity records
    """
    return get_recent_activities(user_id, is_admin_user, db, session_id, limit)

def check_ficore_credit_balance(required_amount=1, user_id=None):
    """
    Check if user has sufficient Ficore Credits.
    
    Args:
        required_amount: Amount of credits required (default: 1)
        user_id: User ID (optional, uses current_user if not provided)
    
    Returns:
        bool: True if user has sufficient credits, False otherwise
    """
    try:
        from flask_login import current_user
        if user_id is None and current_user.is_authenticated:
            user_id = current_user.id
        if not user_id:
            logger.warning("No user_id provided for credit balance check")
            return False
        
        db = get_mongo_db()
        user = db.users.find_one({'_id': user_id})
        if not user:
            logger.error(f"User {user_id} not found for credit balance check")
            return False
        
        # Use float to match the MongoDB schema and deduct_ficore_credits function
        current_balance = float(user.get('ficore_credit_balance', 0))
        has_sufficient = current_balance >= required_amount
        
        logger.debug(f"Credit balance check for user {user_id}: required={required_amount}, available={current_balance}, sufficient={has_sufficient}")
        return has_sufficient
    except Exception as e:
        logger.error(f"Error checking Ficore Credit balance for user {user_id}: {str(e)}", exc_info=True)
        return False

def send_sms_reminder(phone, message):
    """
    Send SMS reminder (placeholder implementation).
    
    Args:
        phone: Phone number
        message: SMS message
    
    Returns:
        tuple: (success, response)
    """
    # Placeholder implementation - replace with actual SMS service
    logger.info(f"SMS reminder sent to {phone}: {message}")
    return True, {'status': 'sent'}

def send_whatsapp_reminder(phone, message):
    """
    Send WhatsApp reminder (placeholder implementation).
    
    Args:
        phone: Phone number
        message: WhatsApp message
    
    Returns:
        tuple: (success, response)
    """
    # Placeholder implementation - replace with actual WhatsApp service
    logger.info(f"WhatsApp reminder sent to {phone}: {message}")
    return True, {'status': 'sent'}

# Export all functions and variables
__all__ = [
    'login_manager', 'clean_currency', 'log_tool_usage', 'flask_session', 'csrf', 'limiter',
    'get_limiter', 'trans_function', 'is_valid_email',
    'get_mongo_db', 'close_mongo_db', 'get_mail', 'requires_role',
    'get_user_query', 'is_admin', 'format_currency', 'format_date', 'sanitize_input',
    'generate_unique_id', 'validate_required_fields', 'get_user_language',
    'log_user_action', 'initialize_tools_with_urls',
    'PERSONAL_TOOLS', 'PERSONAL_NAV', 'PERSONAL_EXPLORE_FEATURES',
    'ADMIN_TOOLS', 'ADMIN_NAV', 'ADMIN_EXPLORE_FEATURES', 'ALL_TOOLS', 'get_explore_features',
    'get_recent_activities', 'get_all_recent_activities', 'check_ficore_credit_balance',
    'send_sms_reminder', 'send_whatsapp_reminder'
]
