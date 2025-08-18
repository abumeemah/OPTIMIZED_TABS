from flask import Blueprint, jsonify, current_app, session, request
from flask_login import current_user, login_required
from datetime import datetime, date
from models import get_budgets, get_bills
from utils import get_mongo_db, trans, requires_role, logger, is_admin
from bson import ObjectId

summaries_bp = Blueprint('summaries', __name__, url_prefix='/summaries')

# --- HELPER FUNCTION ---
def parse_currency(value):
    """Parse a currency string to a float, removing symbols and thousand separators."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Remove currency symbol (₦) and commas
        cleaned_value = str(value).replace('₦', '').replace(',', '')
        return float(cleaned_value)
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Currency Format Error {value}: could not convert string to float: {str(e)}",
            extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr}
        )
        return 0.0

# --- HELPER FUNCTION ---
def get_recent_activities(user_id=None, is_admin_user=False, db=None):
    if db is None:
        db = get_mongo_db()
    query = {} if is_admin_user else {'user_id': str(user_id)}
    activities = []

    # Log the user_id and is_admin_user for debugging
    logger.info(f"Fetching recent activities for user_id={user_id}, is_admin_user={is_admin_user}, query={query}", 
                extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})

    # Define required fields for each activity type
    activity_configs = {
        'bills': {
            'collection': 'bills',
            'required_fields': ['created_at', 'bill_name'],
            'type': 'bill',
            'icon': 'bi-receipt',
            'description_key': 'recent_activity_bill_added',
            'default_description': 'Added bill: {name}',
            'details': lambda x: {
                'amount': x.get('amount', 0),
                'due_date': x.get('due_date', 'N/A'),
                'status': x.get('status', 'Unknown')
            }
        },
        'budgets': {
            'collection': 'budgets',
            'required_fields': ['created_at', 'income'],
            'type': 'budget',
            'icon': 'bi-cash-coin',
            'description_key': 'recent_activity_budget_created',
            'default_description': 'Created budget with income: {amount}',
            'details': lambda x: {
                'income': x.get('income', 0),
                'surplus_deficit': x.get('surplus_deficit', 0)
            }
        },
        'shopping_lists': {
            'collection': 'shopping_lists',
            'required_fields': ['created_at', 'name'],
            'type': 'shopping',  # Changed to 'shopping' to match JS filter
            'icon': 'bi-cart',
            'description_key': 'recent_activity_shopping_list_created',
            'default_description': 'Created shopping list: {name}',
            'details': lambda x: {
                'budget': x.get('budget', 0),
                'total_spent': x.get('total_spent', 0)
            }
        },
        'shopping_items': {
            'collection': 'shopping_items',
            'required_fields': ['updated_at', 'name', 'status'],
            'type': 'shopping',  # Changed to 'shopping' to match JS filter
            'icon': 'bi-check-circle',
            'description_key': 'recent_activity_shopping_item_bought',
            'default_description': 'Bought item: {name}',
            'details': lambda x: {
                'quantity': x.get('quantity', 1),
                'price': x.get('price', 0),
                'store': x.get('store', 'Unknown')
            },
            'filter': lambda x: x.get('status') == 'bought'
        },
        'ficore_credit_transactions': {
            'collection': 'ficore_credit_transactions',
            'required_fields': ['timestamp', 'amount', 'action'],
            'type': 'credits',  # Changed to 'credits' to match JS filter
            'icon': 'bi-wallet2',
            'description_key': 'recent_activity_ficore_credit',
            'default_description': '{action}: {amount} credits',
            'details': lambda x: {
                'amount': x.get('amount', 0),
                'action': x.get('action', 'Unknown')
            }
        }
    }

    for config in activity_configs.values():
        try:
            # Use aggregation pipeline for optimized querying
            pipeline = [
                {'$match': query},
                {'$sort': {config.get('sort_field', 'created_at'): -1}},
                {'$limit': 2}  # Fetch only 2 records per collection
            ]
            cursor = db[config['collection']].aggregate(pipeline)
            for record in cursor:
                # Validate required fields
                if any(record.get(field) is None for field in config['required_fields']):
                    logger.warning(
                        f"Skipping invalid {config['collection']} record: {record.get('_id', 'unknown')}",
                        extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr}
                    )
                    continue
                # Apply additional filter if specified
                if 'filter' in config and not config['filter'](record):
                    continue
                # Validate timestamp format
                try:
                    timestamp = record.get(config.get('sort_field', 'created_at'), datetime.utcnow())
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    activity_timestamp = timestamp.isoformat()
                except ValueError as ve:
                    logger.warning(
                        f"Invalid timestamp in {config['collection']} record: {record.get('_id', 'unknown')}, error: {str(ve)}",
                        extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr}
                    )
                    continue
                # Construct activity object
                activity = {
                    'type': config['type'],
                    'description_key': config['description_key'],
                    'description': trans(
                        config['description_key'],
                        default=config['default_description'].format(**{
                            'name': record.get('name', 'Unknown'),
                            'amount': abs(record.get('amount', record.get('income', 0))),
                            'action': record.get('action', 'Transaction')
                        }),
                        module=config['collection']
                    ),
                    'timestamp': activity_timestamp,
                    'details': config['details'](record),
                    'icon': config['icon']
                }
                activities.append(activity)
        except Exception as e:
            logger.error(
                f"Error processing {config['collection']} for recent activities: {str(e)}",
                extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr}
            )
            continue

    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    return activities[:10]

# --- HELPER FUNCTION ---
def _get_recent_activities_data(user_id=None, is_admin_user=False, db=None):
    """Fetch recent activities across all personal finance tools for a user."""
    if db is None:
        db = get_mongo_db()
    return get_recent_activities(user_id, is_admin_user, db)

# --- HELPER FUNCTION FOR NOTIFICATIONS ---
def _get_notifications_data(user_id, is_admin_user, db):
    """Helper function to fetch recent notifications for a user from bill_reminders collection."""
    query = {} if is_admin_user else {'user_id': str(user_id)}
    notifications = db.bill_reminders.find(query).sort('sent_at', -1).limit(10)
    return [{
        'id': str(n.get('notification_id', ObjectId())),
        'message': n.get('message', 'No message'),
        'message_key': n.get('message_key', 'unknown_notification'),
        'type': n.get('type', 'info'),
        'timestamp': n.get('sent_at', datetime.utcnow()).isoformat(),
        'read': n.get('read_status', False),
        'icon': get_notification_icon(n.get('type', 'info'))
    } for n in notifications]

# --- HELPER FUNCTION FOR NOTIFICATION ICONS ---
def get_notification_icon(notification_type):
    """Map notification types to Bootstrap Icons."""
    icons = {
        'info': 'bi-info-circle',
        'warning': 'bi-exclamation-triangle',
        'error': 'bi-x-circle',
        'success': 'bi-check-circle'
    }
    return icons.get(notification_type, 'bi-info-circle')

@summaries_bp.route('/budget/summary')
@login_required
@requires_role(['personal', 'admin'])
def budget_summary():
    """Fetch the latest budget summary for the authenticated user."""
    try:
        db = get_mongo_db()
        filter_criteria = {} if is_admin() else {'user_id': str(current_user.id)}
        latest_budget = get_budgets(db, filter_criteria)
        if latest_budget:
            latest_budget = latest_budget[0]
            income = parse_currency(latest_budget.get('income', 0.0))
            fixed_expenses = parse_currency(latest_budget.get('fixed_expenses', 0.0))
            variable_expenses = parse_currency(latest_budget.get('variable_expenses', 0.0))
            total_budget = income - (fixed_expenses + variable_expenses)
        else:
            total_budget = 0.0
        logger.info(f"Fetched budget summary for user {current_user.id}: {total_budget}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'totalBudget': total_budget}), 200
    except Exception as e:
        logger.error(f"Error fetching budget summary for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'totalBudget': 0.0, 'error': trans('budget_summary_error', default='Error fetching budget summary', module='budget')}), 500

@summaries_bp.route('/bill/summary')
@login_required
@requires_role(['personal', 'admin'])
def bill_summary():
    """Fetch the summary of bills for the authenticated user."""
    try:
        db = get_mongo_db()
        today = date.today()
        filter_criteria = {} if is_admin() else {'user_id': str(current_user.id)}
        bills = get_bills(db, filter_criteria)
        
        overdue_amount = 0.0
        pending_amount = 0.0
        unpaid_amount = 0.0
        
        for bill in bills:
            try:
                due_date = bill.get('due_date')
                if isinstance(due_date, str):
                    due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
                amount = parse_currency(bill.get('amount', 0))
                status = bill.get('status', 'unpaid')
                
                if status in ['unpaid', 'pending', 'overdue']:
                    if status == 'unpaid':
                        unpaid_amount += amount
                        if due_date < today:
                            overdue_amount += amount
                        elif due_date >= today:
                            pending_amount += amount
                    elif status == 'pending':
                        pending_amount += amount
                    elif status == 'overdue':
                        overdue_amount += amount
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid bill data for bill {bill.get('_id')}: {str(e)}", 
                              extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
                continue

        logger.info(f"Fetched bill summary for user {current_user.id}: overdue={overdue_amount}, pending={pending_amount}, unpaid={unpaid_amount}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'overdue_amount': overdue_amount,
            'pending_amount': pending_amount,
            'unpaid_amount': unpaid_amount
        }), 200
    except Exception as e:
        logger.error(f"Error fetching bill summary for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'overdue_amount': 0.0,
            'pending_amount': 0.0,
            'unpaid_amount': 0.0,
            'error': trans('bill_summary_error', default='Error fetching bill summary', module='budget')
        }), 500

@summaries_bp.route('/shopping/summary')
@login_required
@requires_role(['personal', 'admin'])
def shopping_summary():
    """Fetch the summary of active shopping lists for the authenticated user."""
    try:
        db = get_mongo_db()
        shopping_lists = db.shopping_lists.find({'user_id': str(current_user.id), 'status': 'active'}).sort('updated_at', -1)
        total_budget = 0.0
        total_spent = 0.0
        active_lists = 0
        for shopping_list in shopping_lists:
            try:
                total_budget += parse_currency(shopping_list.get('budget', 0))
                total_spent += parse_currency(shopping_list.get('total_spent', 0))
                active_lists += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid shopping list data for list {shopping_list.get('_id')}: {str(e)}", 
                              extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
                continue
        
        logger.info(f"Fetched shopping summary for user {current_user.id}: budget={total_budget}, spent={total_spent}, active_lists={active_lists}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'total_shopping_budget': float(total_budget),
            'total_shopping_spent': float(total_spent),
            'active_lists': active_lists
        }), 200
    except Exception as e:
        logger.error(f"Error fetching shopping summary for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({
            'total_shopping_budget': 0.0,
            'total_shopping_spent': 0.0,
            'active_lists': 0,
            'error': trans('shopping_summary_error', default='Error fetching shopping summary', module='shopping')
        }), 500

@summaries_bp.route('/ficore_balance')
@login_required
@requires_role(['personal', 'admin'])
def ficore_balance():
    """Fetch the Ficore Credits balance for the authenticated user."""
    try:
        db = get_mongo_db()
        user = db.users.find_one({'_id': current_user.id})
        balance = parse_currency(user.get('ficore_credit_balance', 0))
        logger.info(f"Fetched Ficore Credits balance for user {current_user.id}: {balance}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'balance': balance}), 200
    except Exception as e:
        logger.error(f"Error fetching Ficore Credits balance for user {current_user.id}: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'balance': 0.0, 'error': trans('ficore_balance_error', default='Error fetching Ficore Credits balance', module='general')}), 500

@summaries_bp.route('/recent_activity')
@login_required
@requires_role(['personal', 'admin'])
def recent_activity():
    """Return recent activity across all personal finance tools for the current user."""
    try:
        # Log current_user details for debugging
        logger.info(f"Accessing recent_activity for user_id={current_user.id}, role={getattr(current_user, 'role', 'unknown')}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        activities = _get_recent_activities_data(user_id=current_user.id, is_admin_user=getattr(current_user, 'role', None) == 'admin')
        logger.info(f"Fetched {len(activities)} recent activities for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify(activities), 200
    except Exception as e:
        logger.error(f"Error in summaries.recent_activity: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify([]), 200  # Return empty array instead of error to avoid client-side issues

@summaries_bp.route('/notification_count')
@login_required
@requires_role(['personal', 'admin'])
def notification_count():
    """Return the count of unread notifications for the current user."""
    try:
        db = get_mongo_db()
        query = {} if getattr(current_user, 'role', None) == 'admin' else {'user_id': str(current_user.id), 'read_status': False}
        count = db.bill_reminders.count_documents(query)
        logger.info(f"Fetched notification count {count} for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'count': count}), 200
    except Exception as e:
        logger.error(f"Error fetching notification count: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify({'count': 0, 'error': trans('general_something_went_wrong', default='Failed to fetch notification count', module='general')}), 500

@summaries_bp.route('/notifications')
@login_required
@requires_role(['personal', 'admin'])
def notifications():
    """Return the list of recent notifications for the current user."""
    try:
        db = get_mongo_db()
        query = {} if getattr(current_user, 'role', None) == 'admin' else {'user_id': str(current_user.id)}
        notifications = list(db.bill_reminders.find(query).sort('sent_at', -1).limit(10))

        # Handle cases where notification_id or sent_at might be missing
        notification_ids = []
        for n in notifications:
            if 'notification_id' in n and not n.get('read_status', False):
                notification_ids.append(n['notification_id'])

        if notification_ids:
            db.bill_reminders.update_many(
                {'notification_id': {'$in': notification_ids}},
                {'$set': {'read_status': True}}
            )

        result = []
        for n in notifications:
            try:
                result.append({
                    'id': str(n.get('notification_id', ObjectId())),
                    'message': n.get('message', 'No message'),
                    'message_key': n.get('message_key', 'unknown_notification'),
                    'type': n.get('type', 'info'),
                    'timestamp': n.get('sent_at', datetime.utcnow()).isoformat(),
                    'read': n.get('read_status', False),
                    'icon': get_notification_icon(n.get('type', 'info'))
                })
            except Exception as e:
                logger.warning(f"Skipping invalid notification: {str(e)}", 
                               extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
                continue

        logger.info(f"Fetched {len(result)} notifications for user {current_user.id}", 
                    extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}", 
                     extra={'session_id': session.get('sid', 'no-session-id'), 'ip_address': request.remote_addr})
        return jsonify([]), 200  # Return empty array instead of error to avoid client-side issues
