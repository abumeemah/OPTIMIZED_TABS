import logging
from bson import ObjectId
from flask import Blueprint, request, session as flask_session, redirect, url_for, render_template, flash, current_app, jsonify, Response
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SelectField, SubmitField, TextAreaField, DateField, IntegerField, validators, BooleanField
from wtforms.validators import DataRequired, NumberRange, ValidationError
from translations import trans
import utils
import datetime
from models import get_budgets, get_bills
from credits import ApproveCreditRequestForm, fix_ficore_credit_balances
from utils import logger

admin_bp = Blueprint('admin', __name__, template_folder='templates/admin')

# Form Definitions
class CreditRequestsListForm(FlaskForm):
    status = SelectField(
        trans('credits_request_status_filter', default='Filter by Status'),
        choices=[
            ('all', trans('credits_all_statuses', default='All')),
            ('pending', trans('credits_pending', default='Pending')),
            ('approved', trans('credits_approved', default='Approved')),
            ('denied', trans('credits_denied', default='Denied'))
        ],
        validators=[validators.DataRequired()],
        render_kw={'class': 'form-select'}
    )
    submit = SubmitField(
        trans('credits_filter', default='Filter'),
        render_kw={'class': 'btn btn-primary'}
    )

# Helper Functions
def log_audit_action(action, details=None):
    """Log an admin action to audit_logs collection."""
    try:
        db = utils.get_mongo_db()
        db.audit_logs.insert_one({
            'admin_id': str(current_user.id),
            'action': action,
            'details': details or {},
            'timestamp': datetime.datetime.utcnow()
        })
    except Exception as e:
        logger.error(f"Error logging audit action: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})

# Routes
@admin_bp.route('/dashboard', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def dashboard():
    """Admin dashboard with system statistics."""
    try:
        # Run ficore_credit_balance fix to ensure integer balances
        fix_ficore_credit_balances()
        
        db = utils.get_mongo_db()
        
        # Calculate system statistics
        stats = {
            'users': db.users.count_documents({}),
            'budgets': db.budgets.count_documents({}),
            'bills': db.bills.count_documents({}),
            'shopping_lists': db.shopping_lists.count_documents({}),
            'credit_transactions': db.ficore_credit_transactions.count_documents({}),
            'audit_logs': db.audit_logs.count_documents({})
        }
        
        # Get tool usage statistics
        tool_usage = {
            'audit_logs': db.audit_logs.count_documents({'action': {'$in': ['tool_used', 'tool_accessed']}})
        }
        
        # Get recent users
        recent_users = list(db.users.find().sort('created_at', -1).limit(5))
        for user in recent_users:
            user['_id'] = str(user['_id'])
            user['ficore_credit_balance'] = int(user.get('ficore_credit_balance', 0))  # Ensure integer
            
        logger.info(f"Admin {current_user.id} accessed dashboard at {datetime.datetime.utcnow()}",
                    extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        return render_template(
            'admin/dashboard.html',
            stats=stats,
            tool_usage=tool_usage,
            recent_users=recent_users,
            title=trans('admin_dashboard', default='Admin Dashboard')
        )
    except Exception as e:
        logger.error(f"Error loading admin dashboard for {current_user.id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_dashboard_error', default='An error occurred while loading the dashboard'), 'danger')
        return redirect(url_for('personal_bp.error'))

@admin_bp.route('/feedbacks', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def view_feedbacks():
    """View all feedbacks."""
    try:
        db = utils.get_mongo_db()
        feedbacks = list(db.feedback.find().sort('timestamp', -1))
        for feedback in feedbacks:
            feedback['_id'] = str(feedback['_id'])
        return render_template('admin/feedback_list.html', feedbacks=feedbacks, title=trans('admin_feedbacks_title', default='Feedbacks'))
    except Exception as e:
        logger.error(f"Error fetching feedbacks for admin: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return render_template('admin/feedback_list.html', feedbacks=[]), 500

@admin_bp.route('/users', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def manage_users():
    """View and manage users."""
    try:
        db = utils.get_mongo_db()
        users = list(db.users.find({'role': {'$in': ['personal', 'admin']}}).sort('created_at', -1))
        for user in users:
            user['_id'] = str(user['_id'])
            user['username'] = user['_id']
            user['ficore_credit_balance'] = int(user.get('ficore_credit_balance', 0))  # Ensure integer
        return render_template('admin/users.html', users=users, title=trans('admin_manage_users_title', default='Manage Users'))
    except Exception as e:
        logger.error(f"Error fetching users for admin: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return render_template('admin/users.html', users=[]), 500

@admin_bp.route('/users/suspend/<user_id>', methods=['POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("10 per hour")
def suspend_user(user_id):
    """Suspend a user account."""
    try:
        db = utils.get_mongo_db()
        user_query = utils.get_user_query(user_id)
        user = db.users.find_one(user_query)
        if not user:
            flash(trans('admin_user_not_found', default='User not found'), 'danger')
            return redirect(url_for('admin.manage_users'))
        if user['role'] == 'admin':
            flash(trans('admin_cannot_suspend_admin', default='Cannot suspend an admin account'), 'danger')
            return redirect(url_for('admin.manage_users'))
        result = db.users.update_one(
            user_query,
            {'$set': {'suspended': True, 'updated_at': datetime.datetime.utcnow()}}
        )
        if result.modified_count == 0:
            flash(trans('admin_user_not_updated', default='User could not be suspended'), 'danger')
        else:
            flash(trans('admin_user_suspended', default='User suspended successfully'), 'success')
            logger.info(f"Admin {current_user.id} suspended user {user_id}",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            log_audit_action('suspend_user', {'user_id': user_id})
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        logger.error(f"Error suspending user {user_id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.manage_users'))

@admin_bp.route('/users/delete/<user_id>', methods=['POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("5 per hour")
def delete_user(user_id):
    """Delete a user and their data."""
    try:
        db = utils.get_mongo_db()
        user_query = utils.get_user_query(user_id)
        user = db.users.find_one(user_query)
        if not user:
            flash(trans('admin_user_not_found', default='User not found'), 'danger')
            return redirect(url_for('admin.manage_users'))
        if user['role'] == 'admin':
            flash(trans('admin_cannot_delete_admin', default='Cannot delete an admin account'), 'danger')
            return redirect(url_for('admin.manage_users'))
        db.budgets.delete_many({'user_id': user_id})
        db.bills.delete_many({'user_id': user_id})
        db.shopping_lists.delete_many({'user_id': user_id})
        db.ficore_credit_transactions.delete_many({'user_id': user_id})
        db.credit_requests.delete_many({'user_id': user_id})
        db.audit_logs.delete_many({'details.user_id': user_id})
        result = db.users.delete_one(user_query)
        if result.deleted_count == 0:
            flash(trans('admin_user_not_deleted', default='User could not be deleted'), 'danger')
        else:
            flash(trans('admin_user_deleted', default='User deleted successfully'), 'success')
            logger.info(f"Admin {current_user.id} deleted user {user_id}",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            log_audit_action('delete_user', {'user_id': user_id})
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.manage_users'))

@admin_bp.route('/data/delete/<collection>/<item_id>', methods=['POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("10 per hour")
def delete_item(collection, item_id):
    """Delete an item from a collection."""
    valid_collections = ['budgets', 'bills', 'shopping_lists', 'credit_requests']
    if collection not in valid_collections:
        flash(trans('admin_invalid_collection', default='Invalid collection selected'), 'danger')
        return redirect(url_for('admin.dashboard'))
    try:
        db = utils.get_mongo_db()
        result = db[collection].delete_one({'_id': ObjectId(item_id)})
        if result.deleted_count == 0:
            flash(trans('admin_item_not_found', default='Item not found'), 'danger')
        else:
            flash(trans('admin_item_deleted', default='Item deleted successfully'), 'success')
            logger.info(f"Admin {current_user.id} deleted {collection} item {item_id}",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            log_audit_action(f'delete_{collection}_item', {'item_id': item_id, 'collection': collection})
        return redirect(url_for(f'admin.admin_{collection}' if collection in ['budgets', 'bills', 'credit_requests'] else 'admin.dashboard'))
    except Exception as e:
        logger.error(f"Error deleting {collection} item {item_id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/credits/requests', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def view_credit_requests():
    """View all pending credit requests."""
    form = CreditRequestsListForm()
    try:
        db = utils.get_mongo_db()
        status_filter = request.args.get('status', 'pending') if not form.validate_on_submit() else form.status.data
        query = {} if status_filter == 'all' else {'status': status_filter}
        requests = list(db.credit_requests.find(query).sort('created_at', -1).limit(50))
        for req in requests:
            req['_id'] = str(req['_id'])
            req['receipt_file_id'] = str(req['receipt_file_id']) if req.get('receipt_file_id') else None
            user = db.users.find_one({'_id': req['user_id']})
            req['ficore_credit_balance'] = int(user.get('ficore_credit_balance', 0)) if user else 0  # Ensure integer
        return render_template(
            'admin/credits_requests.html',
            form=form,
            requests=requests,
            title=trans('credits_requests_title', default='Pending Credit Requests')
        )
    except Exception as e:
        logger.error(f"Error fetching credit requests for admin {current_user.id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return render_template('admin/credits_requests.html', form=form, requests=[], title=trans('general_error', default='Error'))

@admin_bp.route('/credits/request/<request_id>', methods=['GET', 'POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("20 per hour")
def manage_credit_request(request_id):
    """Approve or deny a credit request."""
    form = ApproveCreditRequestForm()
    try:
        db = utils.get_mongo_db()
        client = db.client
        request_data = db.credit_requests.find_one({'_id': ObjectId(request_id)})
        if not request_data:
            flash(trans('credits_request_not_found', default='Credit request not found'), 'danger')
            return redirect(url_for('admin.view_credit_requests'))

        if form.validate_on_submit():
            status = form.status.data
            ref = f"REQ_PROCESS_{datetime.datetime.utcnow().isoformat()}"
            with client.start_session() as mongo_session:
                with mongo_session.start_transaction():
                    db.credit_requests.update_one(
                        {'_id': ObjectId(request_id)},
                        {
                            '$set': {
                                'status': status,
                                'updated_at': datetime.datetime.utcnow(),
                                'admin_id': str(current_user.id)
                            }
                        },
                        session=mongo_session
                    )
                    if status == 'approved':
                        from credits import credit_ficore_credits
                        credit_ficore_credits(
                            user_id=request_data['user_id'],
                            amount=int(request_data['amount']),  # Ensure integer
                            ref=ref,
                            type='add',
                            admin_id=str(current_user.id)
                        )
                    db.audit_logs.insert_one({
                        'admin_id': str(current_user.id),
                        'action': f'credit_request_{status}',
                        'details': {'request_id': request_id, 'user_id': request_data['user_id'], 'amount': int(request_data['amount'])},
                        'timestamp': datetime.datetime.utcnow()
                    }, session=mongo_session)
            flash(trans(f'credits_request_{status}', default=f'Credit request {status} successfully'), 'success')
            logger.info(f"Admin {current_user.id} {status} credit request {request_id} for user {request_data['user_id']}",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            return redirect(url_for('admin.view_credit_requests'))
        
        request_data['ficore_credit_balance'] = int(db.users.find_one({'_id': request_data['user_id']}).get('ficore_credit_balance', 0))  # Ensure integer
        return render_template(
            'admin/credits_request.html',
            form=form,
            request=request_data,
            title=trans('credits_manage_request_title', default='Manage Credit Request')
        )
    except Exception as e:
        logger.error(f"Error managing credit request {request_id} by admin {current_user.id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.view_credit_requests'))

@admin_bp.route('/audit', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def audit():
    """View audit logs of admin actions."""
    try:
        db = utils.get_mongo_db()
        db.tool_usage.insert_one({
            'tool_name': 'audit_logs',
            'user_id': str(current_user.id),
            'timestamp': datetime.datetime.utcnow()
        })
        logs = list(db.audit_logs.find().sort('timestamp', -1).limit(100))
        for log in logs:
            log['_id'] = str(log['_id'])
        return render_template('admin/audit.html', logs=logs, title=trans('admin_audit_title', default='Audit Logs'))
    except Exception as e:
        logger.error(f"Error fetching audit logs for admin {current_user.id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return render_template('admin/audit.html', logs=[])

@admin_bp.route('/budgets', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def admin_budgets():
    """View all user budgets."""
    try:
        db = utils.get_mongo_db()
        budgets = list(get_budgets(db, {}))
        for budget in budgets:
            budget['_id'] = str(budget['_id'])
        return render_template('admin/budgets.html', budgets=budgets, title=trans('admin_budgets_title', default='Manage Budgets'))
    except Exception as e:
        logger.error(f"Error fetching budgets for admin: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return render_template('admin/budgets.html', budgets=[]), 500

@admin_bp.route('/budgets/delete/<budget_id>', methods=['POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("10 per hour")
def admin_delete_budget(budget_id):
    """Delete a budget."""
    try:
        db = utils.get_mongo_db()
        result = db.budgets.delete_one({'_id': ObjectId(budget_id)})
        if result.deleted_count == 0:
            flash(trans('admin_item_not_found', default='Budget not found'), 'danger')
        else:
            flash(trans('admin_item_deleted', default='Budget deleted successfully'), 'success')
            logger.info(f"Admin {current_user.id} deleted budget {budget_id}",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            log_audit_action('delete_budget', {'budget_id': budget_id})
        return redirect(url_for('admin.admin_budgets'))
    except Exception as e:
        logger.error(f"Error deleting budget {budget_id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.admin_budgets'))

@admin_bp.route('/bills', methods=['GET'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("50 per hour")
def admin_bills():
    """View all user bills."""
    try:
        db = utils.get_mongo_db()
        bills = list(get_bills(db, {}))
        for bill in bills:
            bill['_id'] = str(bill['_id'])
        return render_template('admin/bills.html', bills=bills, title=trans('admin_bills_title', default='Manage Bills'))
    except Exception as e:
        logger.error(f"Error fetching bills for admin: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return render_template('admin/bills.html', bills=[]), 500

@admin_bp.route('/bills/delete/<bill_id>', methods=['POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("10 per hour")
def admin_delete_bill(bill_id):
    """Delete a bill."""
    try:
        db = utils.get_mongo_db()
        result = db.bills.delete_one({'_id': ObjectId(bill_id)})
        if result.deleted_count == 0:
            flash(trans('admin_item_not_found', default='Bill not found'), 'danger')
        else:
            flash(trans('admin_item_deleted', default='Bill deleted successfully'), 'success')
            logger.info(f"Admin {current_user.id} deleted bill {bill_id}",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            log_audit_action('delete_bill', {'bill_id': bill_id})
        return redirect(url_for('admin.admin_bills'))
    except Exception as e:
        logger.error(f"Error deleting bill {bill_id}: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.admin_bills'))

@admin_bp.route('/bills/mark_paid/<bill_id>', methods=['POST'])
@login_required
@utils.requires_role('admin')
@utils.limiter.limit("10 per hour")
def admin_mark_bill_paid(bill_id):
    """Mark a bill as paid."""
    try:
        db = utils.get_mongo_db()
        result = db.bills.update_one(
            {'_id': ObjectId(bill_id)},
            {'$set': {'status': 'paid', 'updated_at': datetime.datetime.utcnow()}}
        )
        if result.modified_count == 0:
            flash(trans('admin_item_not_updated', default='Bill could not be updated'), 'danger')
        else:
            flash(trans('admin_bill_marked_paid', default='Bill marked as paid'), 'success')
            logger.info(f"Admin {current_user.id} marked bill {bill_id} as paid",
                        extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            log_audit_action('mark_bill_paid', {'bill_id': bill_id})
        return redirect(url_for('admin.admin_bills'))
    except Exception as e:
        logger.error(f"Error marking bill {bill_id} as paid: {str(e)}",
                     extra={'session_id': flask_session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('admin_database_error', default='An error occurred while accessing the database'), 'danger')
        return redirect(url_for('admin.admin_bills'))
