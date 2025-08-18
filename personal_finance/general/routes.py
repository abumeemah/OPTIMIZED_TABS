from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify, make_response
from flask_login import login_required, current_user
from translations import trans
from jinja2.exceptions import TemplateNotFound
from datetime import datetime
from models import create_feedback
from flask_wtf.csrf import CSRFError
from flask import current_app
import utils
from users.routes import get_post_login_redirect  # Import the redirect function

general_bp = Blueprint('general_bp', __name__, url_prefix='/general')

@general_bp.route('/landing')
def landing():
    """Render the public landing page."""
    try:
        # Redirect authenticated users to their role-specific dashboard
        if current_user.is_authenticated:
            current_app.logger.info(f"Authenticated user {current_user.id} redirected from landing to {get_post_login_redirect(current_user.role)}")
            return redirect(get_post_login_redirect(current_user.role))

        current_app.logger.info(f"Accessing general.landing - User: Unauthenticated, Session: {dict(session)}")
        explore_features = utils.get_explore_features()
        response = make_response(render_template(
            'general/landingpage.html',
            title=trans('general_welcome', lang=session.get('lang', 'en'), default='Welcome'),
            explore_features_for_template=explore_features
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        current_app.logger.error(f"Error rendering landing page: {str(e)}", extra={'session_id': session.get('sid', 'unknown')})
        flash(trans('general_error', default='An error occurred'), 'danger')
        response = make_response(render_template(
            'general/error.html',
            error_message="Unable to load the landing page due to an internal error.",
            title=trans('general_welcome', lang=session.get('lang', 'en'), default='Welcome')
        ), 500)
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

@general_bp.route('/home')
@login_required
def home():
    """Personal homepage."""
    if current_user.role not in ['personal', 'admin']:
        flash(trans('general_access_denied', default='You do not have permission to access this page.'), 'danger')
        return redirect(url_for('index'))
    
    return render_template(
        'general/home.html',
        title=trans('general_business_home', lang=session.get('lang', 'en'))
    )

@general_bp.route('/access_denied')
@login_required
def access_denied():
    """Render a friendly access denied page."""
    return render_template(
        'general/access_denied.html',
        title=trans('access_denied', default='Access Denied'),
        message=trans('general_access_denied', default='You do not have permission to access this page.')
    ), 403

@general_bp.route('/about')
def about():
    """Public about page."""
    return render_template(
        'general/about.html',
        title=trans('general_about', lang=session.get('lang', 'en'))
    )

@general_bp.route('/contact')
def contact():
    """Public contact page."""
    return render_template(
        'general/contact.html',
        title=trans('general_contact', lang=session.get('lang', 'en'))
    )

@general_bp.route('/privacy')
def privacy():
    """Public privacy policy page."""
    lang = session.get('lang', 'en')
    try:
        return render_template(
            'general/privacy.html',
            title=trans('general_privacy', lang=lang)
        )
    except TemplateNotFound as e:
        current_app.logger.error(f'Template not found: {str(e)}', exc_info=True)
        return render_template(
            'general/error.html',
            error=str(e),
            title=trans('general_privacy', lang=lang)
        ), 404

@general_bp.route('/terms')
def terms():
    """Public terms of service page."""
    lang = session.get('lang', 'en')
    try:
        return render_template(
            'general/terms.html',
            title=trans('general_terms', lang=lang)
        )
    except TemplateNotFound as e:
        current_app.logger.error(f'Template not found: {str(e)}', exc_info=True)
        return render_template(
            'general/error.html',
            error=str(e),
            title=trans('general_terms', lang=lang)
        ), 404

@general_bp.route('/personal-finance-tips')
def personal_finance_tips():
    """Public personal finance tips page."""
    lang = session.get('lang', 'en')
    try:
        return render_template(
            'general/personal_finance_tips.html',
            title=trans('personal_finance_tips_title', lang=lang, default='Personal Finance Tips')
        )
    except TemplateNotFound as e:
        current_app.logger.error(f'Template not found: {str(e)}', exc_info=True)
        return render_template(
            'general/error.html',
            error=str(e),
            title=trans('personal_finance_tips_title', lang=lang, default='Personal Finance Tips')
        ), 404

@general_bp.route('/feedback', methods=['GET', 'POST'])
@utils.limiter.limit('10 per minute')
def feedback():
    """Public feedback page."""
    lang = session.get('lang', 'en')
    current_app.logger.info('Handling feedback', extra={'ip_address': request.remote_addr})
    tool_options = [
        ['profile', trans('general_profile', default='Profile')],
        ['report', trans('reports_dashboard', default='Reports')],
        ['budget', trans('budget_budget_planner', default='Budget')],
        ['bill', trans('bill_bill_planner', default='Bill')],
    ]
    if request.method == 'POST':
        try:
            tool_name = request.form.get('tool_name')
            rating = request.form.get('rating')
            comment = request.form.get('comment', '').strip()
            valid_tools = [option[0] for option in tool_options]
            if not tool_name or tool_name not in valid_tools:
                current_app.logger.error(f'Invalid feedback tool: {tool_name}', extra={'ip_address': request.remote_addr})
                flash(trans('general_invalid_input', default='Please select a valid tool'), 'danger')
                return render_template('general/feedback.html', tool_options=tool_options, title=trans('general_feedback', lang=lang))
            if not rating or not rating.isdigit() or int(rating) < 1 or int(rating) > 5:
                current_app.logger.error(f'Invalid rating: {rating}', extra={'ip_address': request.remote_addr})
                flash(trans('general_invalid_input', default='Please provide a rating between 1 and 5'), 'danger')
                return render_template('general/feedback.html', tool_options=tool_options, title=trans('general_feedback', lang=lang))
            with current_app.app_context():
                from models import get_mongo_db
                if current_user.is_authenticated:
                    from utils import get_user_query
                    query = get_user_query(str(current_user.id))
                    result = get_mongo_db().users.update_one(query, {'$inc': {'coin_balance': -1}})
                    if result.matched_count == 0:
                        raise ValueError(f'No user found for ID {current_user.id}')
                    get_mongo_db().coin_transactions.insert_one({
                        'user_id': str(current_user.id),
                        'amount': -1,
                        'type': 'spend',
                        'ref': f'FEEDBACK_{datetime.utcnow().isoformat()}',
                        'date': datetime.utcnow()
                    })
                feedback_entry = {
                    'user_id': current_user.id if current_user.is_authenticated else None,
                    'session_id': session.get('sid', 'no-session-id'),
                    'tool_name': tool_name,
                    'rating': int(rating),
                    'comment': comment or None,
                    'timestamp': datetime.utcnow()
                }
                create_feedback(get_mongo_db(), feedback_entry)
                get_mongo_db().audit_logs.insert_one({
                    'admin_id': 'system',
                    'action': 'submit_feedback',
                    'details': {'user_id': str(current_user.id) if current_user.is_authenticated else None, 'tool_name': tool_name},
                    'timestamp': datetime.utcnow()
                })
            current_app.logger.info(f'Feedback submitted: tool={tool_name}, rating={rating}', 
                                   extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
            flash(trans('general_thank_you', default='Thank you for your feedback!'), 'success')
            return redirect(url_for('general_bp.home'))
        except ValueError as e:
            current_app.logger.error(f'User not found: {str(e)}', extra={'ip_address': request.remote_addr})
            flash(trans('general_error', default='User not found'), 'danger')
            return render_template('general/feedback.html', tool_options=tool_options, title=trans('general_feedback', lang=lang)), 400
        except Exception as e:
            current_app.logger.error(f'Error processing feedback: {str(e)}', exc_info=True, extra={'ip_address': request.remote_addr})
            flash(trans('general_error', default='Error occurred during feedback submission'), 'danger')
            try:
                return render_template('general/feedback.html', tool_options=tool_options, title=trans('general_feedback', lang=lang)), 500
            except TemplateNotFound as e:
                current_app.logger.error(f'Template not found: {str(e)}', exc_info=True)
                return render_template('general/error.html', error=str(e), title=trans('general_feedback', lang=lang)), 500
    # Handle GET request
    return render_template('general/feedback.html', tool_options=tool_options, title=trans('general_feedback', lang=lang))
