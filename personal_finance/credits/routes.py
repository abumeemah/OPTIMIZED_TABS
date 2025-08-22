from flask import Blueprint, session, request, render_template, redirect, url_for, flash, jsonify, current_app
from models import (
    get_user, get_user_by_email, create_credit_request, update_credit_request,
    get_credit_requests, to_dict_credit_request, get_ficore_credit_transactions, to_dict_ficore_credit_transaction
)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from gridfs import GridFS
from wtforms import SelectField, SubmitField, validators
from translations import trans
import utils
from bson import ObjectId
from datetime import datetime
from logging import getLogger
from pymongo import errors
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

logger = getLogger(__name__)

credits_bp = Blueprint('credits', __name__, template_folder='templates/credits')

class RequestCreditsForm(FlaskForm):
    amount = SelectField(
        trans('credits_amount', default='Ficore Credit Amount'),
        choices=[('10', '10 Ficore Credits'), ('50', '50 Ficore Credits'), ('100', '100 Ficore Credits')],
        validators=[validators.DataRequired(message=trans('credits_amount_required', default='Ficore Credit amount is required'))],
        render_kw={'class': 'form-select'}
    )
    payment_method = SelectField(
        trans('general_payment_method', default='Payment Method'),
        choices=[
            ('card', trans('general_card', default='Credit/Debit Card')),
            ('cash', trans('general_cash', default='Cash')),
            ('bank', trans('general_bank_transfer', default='Bank Transfer'))
        ],
        validators=[validators.DataRequired(message=trans('general_payment_method_required', default='Payment method is required'))],
        render_kw={'class': 'form-select'}
    )
    receipt = FileField(
        trans('credits_receipt', default='Receipt'),
        validators=[
            FileAllowed(['jpg', 'png', 'pdf'], trans('credits_invalid_file_type', default='Only JPG, PNG, or PDF files are allowed')),
            validators.DataRequired(message=trans('credits_receipt_required', default='Receipt file is required'))
        ],
        render_kw={'class': 'form-control'}
    )
    submit = SubmitField(trans('credits_request', default='Request Ficore Credits'), render_kw={'class': 'btn btn-primary w-100'})

class ApproveCreditRequestForm(FlaskForm):
    status = SelectField(
        trans('credits_request_status', default='Request Status'),
        choices=[('approved', 'Approve'), ('denied', 'Deny')],
        validators=[validators.DataRequired(message=trans('credits_status_required', default='Status is required'))],
        render_kw={'class': 'form-select'}
    )
    submit = SubmitField(trans('credits_update_status', default='Update Request Status'), render_kw={'class': 'btn btn-primary w-100'})

class ReceiptUploadForm(FlaskForm):
    receipt = FileField(
        trans('credits_receipt', default='Receipt'),
        validators=[
            FileAllowed(['jpg', 'png', 'pdf'], trans('credits_invalid_file_type', default='Only JPG, PNG, or PDF files are allowed')),
            validators.DataRequired(message=trans('credits_receipt_required', default='Receipt file is required'))
        ],
        render_kw={'class': 'form-control'}
    )
    submit = SubmitField(trans('credits_upload_receipt', default='Upload Receipt'), render_kw={'class': 'btn btn-primary w-100'})

def fix_ficore_credit_balances():
    """Convert all double ficore_credit_balance values to int."""
    try:
        db = utils.get_mongo_db()
        if not db.system_config.find_one({'_id': 'ficore_credit_balance_fix_applied'}):
            result = db.users.update_many(
                {'ficore_credit_balance': {'$type': 'double'}},
                [{'$set': {'ficore_credit_balance': {'$toInt': '$ficore_credit_balance'}}}]
            )
            db.system_config.insert_one({
                '_id': 'ficore_credit_balance_fix_applied',
                'applied_at': datetime.utcnow()
            })
            logger.info(f"Converted {result.modified_count} users' ficore_credit_balance from double to int",
                        extra={'session_id': 'system', 'ip_address': 'system'})
    except Exception as e:
        logger.error(f"Error converting ficore_credit_balance to int: {str(e)}",
                     extra={'session_id': 'system', 'ip_address': 'system'})

def credit_ficore_credits(user_id: str, amount: int, ref: str, description: str, type: str = 'add', admin_id: str = None) -> None:
    """Credit or log Ficore Credits with MongoDB transaction, ensuring double balance."""
    try:
        db = utils.get_mongo_db()
        client = db.client
        user_query = utils.get_user_query(user_id)
        with client.start_session() as mongo_session:
            with mongo_session.start_transaction():
                # Ensure amount is converted to float for double type
                amount = float(amount)
                if type == 'add':
                    result = db.users.update_one(
                        user_query,
                        {'$inc': {'ficore_credit_balance': amount}},
                        session=mongo_session
                    )
                    if result.matched_count == 0:
                        logger.error(f"No user found for ID {user_id} to credit Ficore Credits, ref: {ref}",
                                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': user_id})
                        raise ValueError(f"No user found for ID {user_id}")
                    # Ensure the resulting balance is a double
                    db.users.update_one(
                        user_query,
                        [{'$set': {'ficore_credit_balance': {'$toDouble': '$ficore_credit_balance'}}}],
                        session=mongo_session
                    )
                # Map type to action
                action = 'credit' if type == 'add' else 'debit'
                # Prepare transaction document
                document = {
                    'user_id': user_id,
                    'action': action,
                    'amount': amount,
                    'timestamp': datetime.utcnow(),
                    'session_id': session.get('sid', 'no-session-id'),
                    'status': 'completed',
                    'type': type,
                    'ref': ref,
                    'description': description,
                    'payment_method': 'approved_request' if type == 'add' else None
                }
                logger.debug(f"Inserting ficore_credit_transaction: {document}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': user_id})
                db.ficore_credit_transactions.insert_one(document, session=mongo_session)
                db.audit_logs.insert_one({
                    'admin_id': admin_id or 'system',
                    'action': f'credit_ficore_credits_{type}',
                    'details': {'user_id': user_id, 'amount': amount, 'ref': ref, 'description': description},
                    'timestamp': datetime.utcnow()
                }, session=mongo_session)
    except ValueError as e:
        if mongo_session.in_transaction:
            mongo_session.abort_transaction()
        logger.error(f"Transaction aborted for ref {ref}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': user_id})
        raise
    except errors.PyMongoError as e:
        if mongo_session.in_transaction:
            mongo_session.abort_transaction()
        logger.error(f"MongoDB error during Ficore Credit transaction for user {user_id}, ref {ref}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': user_id})
        raise
    except Exception as e:
        if mongo_session.in_transaction:
            mongo_session.abort_transaction()
        logger.error(f"Unexpected error in credit_ficore_credits for user {user_id}, ref {ref}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': user_id})
        raise

@credits_bp.route('/request', methods=['GET', 'POST'])
@login_required
@utils.requires_role(['personal'])
@limiter.limit("50 per hour")
def request_credits():
    """Handle Ficore Credit request submissions."""
    form = RequestCreditsForm()
    price = 500
    amount = 10
    if form.amount.data:
        try:
            amount = int(form.amount.data)
            price = amount * 50  # 50 Naira per 1 FC
        except ValueError:
            amount = 10
            price = 500  # Default to minimum purchase (10 FCs)
    else:
        price = 500  # Default to minimum purchase (10 FCs)

    if form.validate_on_submit():
        try:
            db = utils.get_mongo_db()
            client = db.client
            fs = GridFS(db)
            amount = int(form.amount.data)
            payment_method = form.payment_method.data
            receipt_file = form.receipt.data
            ref = f"REQ_{datetime.utcnow().isoformat()}"

            # Validate payment_method against allowed values
            valid_payment_methods = ['card', 'cash', 'bank']
            if payment_method not in valid_payment_methods:
                logger.error(f"Invalid payment method {payment_method} for user {current_user.id}, ref {ref}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                flash(trans('general_invalid_payment_method', default='Invalid payment method selected'), 'danger')
                return redirect(url_for('credits.request_credits'))

            receipt_file_id = None
            # Step 1: Handle file upload outside the transaction
            try:
                receipt_file_id = fs.put(
                    receipt_file,
                    filename=receipt_file.filename,
                    user_id=str(current_user.id),
                    upload_date=datetime.utcnow()
                )
            except Exception as e:
                logger.error(f"Failed to upload receipt to GridFS for user {current_user.id}, ref {ref}: {str(e)}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                flash(trans('credits_file_upload_failed', default='Failed to upload receipt file'), 'danger')
                return redirect(url_for('credits.request_credits'))

            # Step 2: Create credit request
            request_data = {
                'user_id': str(current_user.id),
                'amount': amount,
                'payment_method': payment_method,
                'receipt_file_id': receipt_file_id,
                'status': 'pending',
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'admin_id': None
            }
            try:
                with client.start_session() as mongo_session:
                    with mongo_session.start_transaction():
                        request_id = create_credit_request(db, request_data)
                        db.audit_logs.insert_one({
                            'admin_id': 'system',
                            'action': 'credit_request_submitted',
                            'details': {'user_id': str(current_user.id), 'amount': amount, 'ref': ref, 'request_id': request_id},
                            'timestamp': datetime.utcnow()
                        }, session=mongo_session)
            except errors.PyMongoError as e:
                logger.error(f"MongoDB error submitting credit request for user {current_user.id}, ref {ref}: {str(e)}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                if receipt_file_id:
                    try:
                        fs.delete(receipt_file_id)
                        logger.info(f"Deleted orphaned GridFS file {receipt_file_id} for user {current_user.id}, ref {ref}",
                                    extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                    except Exception as delete_err:
                        logger.error(f"Failed to delete orphaned GridFS file {receipt_file_id}: {str(delete_err)}",
                                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
                return redirect(url_for('credits.request_credits'))

            flash(trans('credits_request_success', default='Ficore Credit request submitted successfully'), 'success')
            logger.info(f"User {current_user.id} submitted credit request {request_id} for {amount} Ficore Credits via {payment_method}, ref: {ref}",
                        extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            return redirect(url_for('credits.history'))
        except Exception as e:
            logger.error(f"Unexpected error submitting credit request for user {current_user.id}, ref {ref}: {str(e)}",
                         extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            if receipt_file_id:
                try:
                    fs.delete(receipt_file_id)
                    logger.info(f"Deleted orphaned GridFS file {receipt_file_id} for user {current_user.id}, ref {ref}",
                                extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                except Exception as delete_err:
                    logger.error(f"Failed to delete orphaned GridFS file {receipt_file_id}: {str(delete_err)}",
                                 extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
    return render_template(
        'credits/request.html',
        form=form,
        price=price,
        amount=amount,
        title=trans('credits_request_title', default='Request Ficore Credits', lang=session.get('lang', 'en'))
    )

@credits_bp.route('/history', methods=['GET'])
@login_required
@limiter.limit("100 per hour")
def history():
    """View Ficore Credit transaction and request history, including all statuses."""
    try:
        logger.debug(f"Loading utils module: {utils.__file__}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        db = utils.get_mongo_db()
        # Clear cache to ensure fresh data
        get_user.cache_clear()
        get_user_by_email.cache_clear()
        user = get_user(db, str(current_user.id))
        query = {} if utils.is_admin() else {'user_id': str(current_user.id)}

        # Query ficore_credit_transactions
        ficore_transactions = get_ficore_credit_transactions(db, query)

        # Query legacy credit_transactions safely
        try:
            legacy_transactions = list(db.credit_transactions.find(query))
            valid_legacy_transactions = [
                tx for tx in legacy_transactions
                if 'date' in tx and isinstance(tx['date'], datetime)
            ]
            if len(valid_legacy_transactions) < len(legacy_transactions):
                logger.warning(f"Filtered out {len(legacy_transactions) - len(valid_legacy_transactions)} invalid credit_transactions for user {current_user.id}",
                               extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        except errors.PyMongoError as e:
            logger.warning(f"Failed to query legacy credit_transactions for user {current_user.id}: {str(e)}",
                           extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            valid_legacy_transactions = []

        # Combine and sort transactions by date in descending order
        all_transactions = ficore_transactions + valid_legacy_transactions
        all_transactions.sort(key=lambda x: x.get('timestamp', x.get('date', datetime.min)), reverse=True)

        # Format dates and descriptions in Python before passing to template
        formatted_transactions = []
        for tx in all_transactions:
            tx_dict = to_dict_ficore_credit_transaction(tx)
            if 'timestamp' in tx and isinstance(tx['timestamp'], datetime):
                tx_dict['date_str'] = tx['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            elif 'date' in tx and isinstance(tx['date'], datetime):
                tx_dict['date_str'] = tx['date'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                tx_dict['date_str'] = None
            # Add description, falling back to ref or 'Unknown' for legacy transactions
            tx_dict['description'] = tx.get('description', tx.get('ref', trans('general_unknown', default='Unknown')))
            formatted_transactions.append(tx_dict)

        requests = get_credit_requests(db, query)
        formatted_requests = [to_dict_credit_request(req) for req in requests]
        logger.info(f"Fetched {len(ficore_transactions)} ficore_credit_transactions, {len(valid_legacy_transactions)} credit_transactions, and {len(requests)} requests for user {current_user.id}",
                    extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        return render_template(
            'credits/history.html',
            transactions=formatted_transactions,
            requests=formatted_requests,
            ficore_credit_balance=user.ficore_credit_balance if user else 0,
            title=trans('credits_history_title', default='Ficore Credit Transaction History', lang=session.get('lang', 'en')),
            is_admin=utils.is_admin()
        )
    except AttributeError as e:
        logger.error(f"AttributeError in history route for user {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash('Error loading transaction history due to module configuration.', 'danger')
        return render_template(
            'credits/history.html',
            transactions=[],
            requests=[],
            ficore_credit_balance=0,
            title=trans('general_error', default='Error', lang=session.get('lang', 'en')),
            is_admin=False
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching history for user {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
        return render_template(
            'credits/history.html',
            transactions=[],
            requests=[],
            ficore_credit_balance=0,
            title=trans('general_error', default='Error', lang=session.get('lang', 'en')),
            is_admin=False
        )

@credits_bp.route('/requests', methods=['GET'])
@login_required
@utils.requires_role('admin')
@limiter.limit("50 per hour")
def view_credit_requests():
    """View all credit requests (admin only)."""
    try:
        db = utils.get_mongo_db()
        requests = get_credit_requests(db, {})
        formatted_requests = [to_dict_credit_request(req) for req in requests]
        return render_template(
            'credits/requests.html',
            requests=formatted_requests,
            title=trans('credits_requests_title', default='Pending Credit Requests', lang=session.get('lang', 'en'))
        )
    except AttributeError as e:
        logger.error(f"AttributeError in view_credit_requests for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash('Error loading credit requests due to module configuration.', 'danger')
        return render_template(
            'credits/requests.html',
            requests=[],
            title=trans('general_error', default='Error', lang=session.get('lang', 'en'))
        )
    except Exception as e:
        logger.error(f"Error fetching credit requests for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
        return render_template(
            'credits/requests.html',
            requests=[],
            title=trans('general_error', default='Error', lang=session.get('lang', 'en'))
        )

@credits_bp.route('/request/<request_id>', methods=['GET', 'POST'])
@login_required
@utils.requires_role('admin')
@limiter.limit("20 per hour")
def manage_credit_request(request_id):
    """Approve or deny a credit request (admin only)."""
    form = ApproveCreditRequestForm()
    try:
        if not ObjectId.is_valid(request_id):
            logger.error(f"Invalid request_id {request_id} for admin {current_user.id}",
                         extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            flash(trans('credits_request_not_found', default='Credit request not found'), 'danger')
            return redirect(url_for('credits.view_credit_requests'))

        db = utils.get_mongo_db()
        client = db.client
        request_data = db.credit_requests.find_one({'_id': ObjectId(request_id)})
        if not request_data:
            logger.error(f"Credit request {request_id} not found for admin {current_user.id}",
                         extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            flash(trans('credits_request_not_found', default='Credit request not found'), 'danger')
            return redirect(url_for('credits.view_credit_requests'))

        if form.validate_on_submit():
            status = form.status.data
            ref = f"REQ_PROCESS_{datetime.utcnow().isoformat()}"
            description = trans('credits_approval_description', default='Credit Request Approved') if status == 'approved' else trans('credits_denial_description', default='Credit Request Denied')
            with client.start_session() as mongo_session:
                with mongo_session.start_transaction():
                    update_credit_request(db, request_id, {
                        'status': status,
                        'admin_id': str(current_user.id)
                    })
                    if status == 'approved':
                        credit_ficore_credits(
                            user_id=request_data['user_id'],
                            amount=request_data['amount'],
                            ref=ref,
                            description=description,
                            type='add',
                            admin_id=str(current_user.id)
                        )
                    db.audit_logs.insert_one({
                        'admin_id': str(current_user.id),
                        'action': f'credit_request_{status}',
                        'details': {'request_id': request_id, 'user_id': request_data['user_id'], 'amount': request_data['amount'], 'ref': ref, 'description': description},
                        'timestamp': datetime.utcnow()
                    }, session=mongo_session)
            flash(trans(f'credits_request_{status}', default=f'Credit request {status} successfully'), 'success')
            logger.info(f" mln {current_user.id} {status} credit request {request_id} for user {request_data['user_id']}, ref: {ref}, description: {description}",
                        extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            return redirect(url_for('credits.view_credit_requests'))
        
        return render_template(
            'credits/manage_request.html',
            form=form,
            request=to_dict_credit_request(request_data),
            title=trans('credits_manage_request_title', default='Manage Credit Request', lang=session.get('lang', 'en'))
        )
    except errors.PyMongoError as e:
        logger.error(f"MongoDB error managing credit request {request_id} by admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
        return redirect(url_for('credits.view_credit_requests'))
    except AttributeError as e:
        logger.error(f"AttributeError managing credit request {request_id} by admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash('Error managing credit request due to module configuration.', 'danger')
        return redirect(url_for('credits.view_credit_requests'))
    except Exception as e:
        logger.error(f"Unexpected error managing credit request {request_id} by admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
        return redirect(url_for('credits.view_credit_requests'))

@credits_bp.route('/receipt_upload', methods=['GET', 'POST'])
@login_required
@utils.requires_role(['personal'])
@limiter.limit("10 per hour")
def receipt_upload():
    """Handle payment receipt uploads with transaction for Ficore Credit deduction."""
    form = ReceiptUploadForm()
    try:
        if not utils.is_admin() and not utils.check_ficore_credit_balance(1):
            flash(trans('credits_insufficient_credits', default='Insufficient Ficore Credits to upload receipt. Get more Ficore Credits.'), 'danger')
            return redirect(url_for('credits.request_credits'))
        if form.validate_on_submit():
            db = utils.get_mongo_db()
            client = db.client
            fs = GridFS(db)
            receipt_file = form.receipt.data
            ref = f"UPLOAD_RECEIPT_{datetime.utcnow().isoformat()}"
            description = trans('credits_receipt_upload_description', default='Receipt Upload Deduction')
            file_id = None

            # Step 1: Handle file upload outside the transaction
            try:
                file_id = fs.put(
                    receipt_file,
                    filename=receipt_file.filename,
                    user_id=str(current_user.id),
                    upload_date=datetime.utcnow()
                )
            except Exception as e:
                logger.error(f"Failed to upload receipt to GridFS for user {current_user.id}, ref {ref}: {str(e)}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                flash(trans('credits_file_upload_failed', default='Failed to upload receipt file'), 'danger')
                return redirect(url_for('credits.receipt_upload'))

            # Step 2: Perform database operations within a transaction
            try:
                with client.start_session() as mongo_session:
                    with mongo_session.start_transaction():
                        if not utils.is_admin():
                            user_query = utils.get_user_query(str(current_user.id))
                            result = db.users.update_one(
                                user_query,
                                {'$inc': {'ficore_credit_balance': -1}},
                                session=mongo_session
                            )
                            if result.matched_count == 0:
                                logger.error(f"No user found for ID {current_user.id} to deduct Ficore Credits, ref: {ref}",
                                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                                raise ValueError(f"No user found for ID {current_user.id}")
                            # Ensure the resulting balance is a double
                            db.users.update_one(
                                user_query,
                                [{'$set': {'ficore_credit_balance': {'$toDouble': '$ficore_credit_balance'}}}],
                                session=mongo_session
                            )
                            # Insert transaction with all required fields
                            document = {
                                'user_id': str(current_user.id),
                                'action': 'debit',
                                'amount': float(-1),
                                'timestamp': datetime.utcnow(),
                                'session_id': session.get('sid', 'no-session-id'),
                                'status': 'completed',
                                'type': 'spend',
                                'ref': ref,
                                'description': description,
                                'payment_method': None
                            }
                            logger.debug(f"Inserting ficore_credit_transaction: {document}",
                                         extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                            db.ficore_credit_transactions.insert_one(document, session=mongo_session)
                        db.audit_logs.insert_one({
                            'admin_id': 'system',
                            'action': 'receipt_upload',
                            'details': {'user_id': str(current_user.id), 'file_id': str(file_id), 'ref': ref, 'description': description},
                            'timestamp': datetime.utcnow()
                        }, session=mongo_session)
            except (ValueError, errors.PyMongoError) as e:
                if mongo_session.in_transaction:
                    mongo_session.abort_transaction()
                logger.error(f"Error during transaction for receipt upload for user {current_user.id}, ref {ref}: {str(e)}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                try:
                    fs.delete(file_id)
                    logger.info(f"Deleted orphaned GridFS file {file_id} for user {current_user.id}, ref {ref}",
                                extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                except Exception as delete_err:
                    logger.error(f"Failed to delete orphaned GridFS file {file_id}: {str(delete_err)}",
                                 extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
                flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
                return redirect(url_for('credits.receipt_upload'))

            flash(trans('credits_receipt_uploaded', default='Receipt uploaded successfully'), 'success')
            logger.info(f"User {current_user.id} uploaded receipt {file_id}, ref: {ref}, description: {description}",
                        extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            return redirect(url_for('credits.history'))
    except AttributeError as e:
        logger.error(f"AttributeError in receipt_upload for user {current_user.id}, ref {ref}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash('Error uploading receipt due to module configuration.', 'danger')
        return redirect(url_for('credits.receipt_upload'))
    except Exception as e:
        logger.error(f"Unexpected error uploading receipt for user {current_user.id}, ref {ref}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        if file_id:
            try:
                fs.delete(file_id)
                logger.info(f"Deleted orphaned GridFS file {file_id} for user {current_user.id}, ref {ref}",
                            extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            except Exception as delete_err:
                logger.error(f"Failed to delete orphaned GridFS file {file_id}: {str(delete_err)}",
                             extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
    return render_template(
        'credits/receipt_upload.html',
        form=form,
        title=trans('credits_receipt_upload_title', default='Upload Receipt', lang=session.get('lang', 'en'))
    )

@credits_bp.route('/receipts', methods=['GET'])
@login_required
@utils.requires_role('admin')
@limiter.limit("50 per hour")
def view_receipts():
    """View all uploaded receipts (admin only)."""
    try:
        db = utils.get_mongo_db()
        fs = GridFS(db)
        receipts = list(fs.find().sort('upload_date', -1).limit(50))
        for receipt in receipts:
            receipt['_id'] = str(receipt['_id'])
            receipt['user_id'] = receipt.get('user_id', 'Unknown')
        return render_template(
            'credits/receipts.html',
            receipts=receipts,
            title=trans('credits_receipts_title', default='View Receipts', lang=session.get('lang', 'en'))
        )
    except AttributeError as e:
        logger.error(f"AttributeError in view_receipts for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash('Error loading receipts due to module configuration.', 'danger')
        return render_template(
            'credits/receipts.html',
            receipts=[],
            title=trans('general_error', default='Error', lang=session.get('lang', 'en'))
        )
    except Exception as e:
        logger.error(f"Error fetching receipts for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
        return render_template(
            'credits/receipts.html',
            receipts=[],
            title=trans('general_error', default='Error', lang=session.get('lang', 'en'))
        )

@credits_bp.route('/receipt/<file_id>', methods=['GET'])
@login_required
@utils.requires_role('admin')
@limiter.limit("20 per hour")
def view_receipt(file_id):
    """Serve a specific receipt file (admin only)."""
    try:
        if not ObjectId.is_valid(file_id):
            logger.error(f"Invalid file_id {file_id} for admin {current_user.id}",
                         extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
            flash(trans('credits_receipt_not_found', default='Receipt not found'), 'danger')
            return redirect(url_for('credits.view_receipts'))

        db = utils.get_mongo_db()
        fs = GridFS(db)
        file = fs.get(ObjectId(file_id))
        response = current_app.response_class(
            file.read(),
            mimetype=file.content_type or 'application/octet-stream',
            direct_passthrough=True
        )
        response.headers.set('Content-Disposition', 'inline', filename=file.filename)
        logger.info(f"Admin {current_user.id} viewed receipt {file_id}",
                    extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        return response
    except errors.PyMongoError as e:
        logger.error(f"MongoDB error serving receipt {file_id} for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
    except AttributeError as e:
        logger.error(f"AttributeError serving receipt {file_id} for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash('Error serving receipt due to module configuration.', 'danger')
    except Exception as e:
        logger.error(f"Unexpected error serving receipt {file_id} for admin {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        flash(trans('general_something_went_wrong', default='An error occurred'), 'danger')
    return redirect(url_for('credits.view_receipts'))

@credits_bp.route('/api/balance', methods=['GET'])
@login_required
@limiter.limit("100 per hour")
def get_balance():
    """API endpoint to get current user's Ficore Credit balance."""
    try:
        db = utils.get_mongo_db()
        user = get_user(db, str(current_user.id))
        balance = user.ficore_credit_balance if user else 0
        # Ensure balance is returned as float
        balance = float(balance)
        return jsonify({'balance': balance})
    except AttributeError as e:
        logger.error(f"AttributeError fetching Ficore Credit balance for user {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        return jsonify({'error': 'Failed to fetch balance due to module configuration'}), 500
    except Exception as e:
        logger.error(f"Error fetching Ficore Credit balance for user {current_user.id}: {str(e)}",
                     extra={'session_id': session.get('sid', 'no-session-id'), 'user_id': current_user.id})
        return jsonify({'error': 'Failed to fetch balance'}), 500

@credits_bp.route('/info', methods=['GET'])
@login_required
@limiter.limit("100 per hour")
def ficore_credits_info():
    """Display information about Ficore Credits."""
    return render_template(
        'credits/info.html',
        title=trans('credits_info_title', default='What Are Ficore Credits?', lang=session.get('lang', 'en'))
    )
