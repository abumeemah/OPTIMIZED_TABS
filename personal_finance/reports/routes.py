from flask import Blueprint, session, request, render_template, redirect, url_for, flash, jsonify, current_app, Response
from flask_login import login_required, current_user
from translations import trans
import utils
from bson import ObjectId
from datetime import datetime, date
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import inch
from io import BytesIO
from flask_wtf import FlaskForm
from wtforms import DateField, SubmitField
from wtforms.validators import Optional
import logging
from helpers.branding_helpers import draw_ficore_pdf_header
from utils import logger

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

class ReportForm(FlaskForm):
    start_date = DateField(trans('reports_start_date', default='Start Date'), validators=[Optional()])
    end_date = DateField(trans('reports_end_date', default='End Date'), validators=[Optional()])
    submit = SubmitField(trans('reports_generate_report', default='Generate Report'))

class CustomerReportForm(FlaskForm):
    submit = SubmitField('Generate Report')

class BudgetPerformanceReportForm(FlaskForm):
    start_date = DateField(trans('reports_start_date', default='Start Date'), validators=[Optional()])
    end_date = DateField(trans('reports_end_date', default='End Date'), validators=[Optional()])
    submit = SubmitField(trans('reports_generate_report', default='Generate Report'))

class ShoppingReportForm(FlaskForm):
    start_date = DateField(trans('reports_start_date', default='Start Date'), validators=[Optional()])
    end_date = DateField(trans('reports_end_date', default='End Date'), validators=[Optional()])
    submit = SubmitField(trans('reports_generate_report', default='Generate Report'))

def to_dict_budget(record):
    if not record:
        return {'surplus_deficit': None, 'savings_goal': None}
    return {
        'id': str(record.get('_id', '')),
        'income': record.get('income', 0),
        'fixed_expenses': record.get('fixed_expenses', 0),
        'variable_expenses': record.get('variable_expenses', 0),
        'savings_goal': record.get('savings_goal', 0),
        'surplus_deficit': record.get('surplus_deficit', 0),
        'housing': record.get('housing', 0),
        'food': record.get('food', 0),
        'transport': record.get('transport', 0),
        'dependents': record.get('dependents', 0),
        'miscellaneous': record.get('miscellaneous', 0),
        'others': record.get('others', 0),
        'created_at': utils.format_date(record.get('created_at'), format_type='iso')
    }

def to_dict_bill(record):
    if not record:
        return {'amount': None, 'status': None}
    return {
        'id': str(record.get('_id', '')),
        'bill_name': record.get('bill_name', ''),
        'amount': record.get('amount', 0),
        'due_date': utils.format_date(record.get('due_date'), format_type='iso'),
        'frequency': record.get('frequency', ''),
        'category': record.get('category', ''),
        'status': record.get('status', ''),
        'send_email': record.get('send_email', False),
        'reminder_days': record.get('reminder_days'),
        'user_email': record.get('user_email', ''),
        'first_name': record.get('first_name', '')
    }

def to_dict_shopping_list(record):
    if not record:
        return {'name': None, 'budget': None}
    return {
        'id': str(record.get('_id', '')),
        'user_id': str(record.get('user_id', '')),
        'name': record.get('name', ''),
        'budget': record.get('budget', 0),
        'total_spent': record.get('total_spent', 0),
        'created_at': utils.format_date(record.get('created_at'), format_type='iso'),
        'updated_at': utils.format_date(record.get('updated_at'), format_type='iso') if record.get('updated_at') else None,
        'collaborators': record.get('collaborators', [])
    }

def to_dict_shopping_item(record):
    if not record:
        return {'name': None, 'price': None}
    return {
        'id': str(record.get('_id', '')),
        'list_id': str(record.get('list_id', '')),
        'name': str(record.get('name', '')),
        'quantity': record.get('quantity', 0),
        'price': record.get('price', 0),
        'status': record.get('status', ''),
        'category': record.get('category', ''),
        'store': record.get('store', ''),
        'created_at': utils.format_date(record.get('created_at'), format_type='iso'),
        'updated_at': utils.format_date(record.get('updated_at'), format_type='iso') if record.get('updated_at') else None
    }

def to_dict_shopping_suggestion(record):
    if not record:
        return {'name': None, 'price': None}
    return {
        'id': str(record.get('_id', '')),
        'list_id': str(record.get('list_id', '')),
        'user_id': str(record.get('user_id', '')),
        'name': str(record.get('name', '')),
        'quantity': record.get('quantity', 0),
        'price': record.get('price', 0),
        'category': record.get('category', ''),
        'status': record.get('status', ''),
        'created_at': utils.format_date(record.get('created_at'), format_type='iso'),
        'updated_at': utils.format_date(record.get('updated_at'), format_type='iso') if record.get('updated_at') else None
    }

@reports_bp.route('/')
@login_required
@utils.requires_role(['personal', 'admin'])
def index():
    """Display report selection page."""
    try:
        return render_template(
            'reports/index.html',
            title=utils.trans('reports_index', default='Reports', lang=session.get('lang', 'en'))
        )
    except Exception as e:
        logger.error(f"Error loading reports index for user {current_user.id}: {str(e)}", exc_info=True)
        flash(trans('reports_load_error', default='An error occurred'), 'danger')
        return redirect(url_for('dashboard.index'))

@reports_bp.route('/budget_performance', methods=['GET', 'POST'])
@login_required
@utils.requires_role(['personal', 'admin'])
def budget_performance():
    """Generate budget performance report with filters."""
    form = BudgetPerformanceReportForm()
    if not utils.is_admin() and not utils.check_ficore_credit_balance(1):
        flash(trans('debtors_insufficient_credits', default='Insufficient credits to generate a report. Request more credits.'), 'danger')
        return redirect(url_for('credits.request_credits'))
    budget_data = []
    query = {} if utils.is_admin() else {'user_id': str(current_user.id)}
    if form.validate_on_submit():
        try:
            db = utils.get_mongo_db()
            budget_query = query.copy()
            cashflow_query = query.copy()
            if form.start_date.data:
                start_datetime = datetime.combine(form.start_date.data, datetime.min.time())
                budget_query['created_at'] = {'$gte': start_datetime}
                cashflow_query['created_at'] = {'$gte': start_datetime}
            if form.end_date.data:
                end_datetime = datetime.combine(form.end_date.data, datetime.max.time())
                budget_query['created_at'] = budget_query.get('created_at', {}) | {'$lte': end_datetime}
                cashflow_query['created_at'] = cashflow_query.get('created_at', {}) | {'$lte': end_datetime}
            budgets = list(db.budgets.find(budget_query).sort('created_at', -1))
            cashflows = [utils.to_dict_cashflow(cf) for cf in db.cashflows.find(cashflow_query).sort('created_at', -1)]
            for budget in budgets:
                budget_dict = to_dict_budget(budget)
                actual_income = sum(cf['amount'] for cf in cashflows if cf['type'] == 'receipt')
                actual_expenses = sum(cf['amount'] for cf in cashflows if cf['type'] == 'payment')
                budget_dict['actual_income'] = actual_income
                budget_dict['actual_expenses'] = actual_expenses
                budget_dict['income_variance'] = actual_income - budget_dict['income']
                budget_dict['expense_variance'] = actual_expenses - (budget_dict['fixed_expenses'] + budget_dict['variable_expenses'])
                budget_data.append(budget_dict)
            return generate_budget_performance_pdf(budget_data)
        except Exception as e:
            logger.error(f"Error generating budget performance report for user {current_user.id}: {str(e)}", exc_info=True)
            flash(trans('reports_generation_error', default='An error occurred'), 'danger')
    else:
        try:
            db = utils.get_mongo_db()
            budgets = list(db.budgets.find(query).sort('created_at', -1))
            cashflows = [utils.to_dict_cashflow(cf) for cf in db.cashflows.find(query).sort('created_at', -1)]
            for budget in budgets:
                budget_dict = to_dict_budget(budget)
                actual_income = sum(cf['amount'] for cf in cashflows if cf['type'] == 'receipt')
                actual_expenses = sum(cf['amount'] for cf in cashflows if cf['type'] == 'payment')
                budget_dict['actual_income'] = actual_income
                budget_dict['actual_expenses'] = actual_expenses
                budget_dict['income_variance'] = actual_income - budget_dict['income']
                budget_dict['expense_variance'] = actual_expenses - (budget_dict['fixed_expenses'] + budget_dict['variable_expenses'])
                budget_data.append(budget_dict)
        except Exception as e:
            logger.error(f"Error fetching budget data for user {current_user.id}: {str(e)}", exc_info=True)
            flash(trans('reports_generation_error', default='An error occurred'), 'danger')
    return render_template(
        'reports/budget_performance.html',
        form=form,
        budget_data=budget_data,
        title=utils.trans('reports_budget_performance', default='Budget Performance Report', lang=session.get('lang', 'en'))
    )

@reports_bp.route('/shopping', methods=['GET', 'POST'])
@login_required
@utils.requires_role(['personal', 'admin'])
def shopping_report():
    """Generate shopping report with filters for personal users."""
    form = ShoppingReportForm()
    if not utils.is_admin() and not utils.check_ficore_credit_balance(1):
        flash(trans('debtors_insufficient_credits', default='Insufficient credits to generate a report. Request more credits.'), 'danger')
        return redirect(url_for('credits.request_credits'))
    shopping_data = {'lists': [], 'items': [], 'suggestions': []}
    query = {} if utils.is_admin() else {'user_id': str(current_user.id)}
    if form.validate_on_submit():
        try:
            db = utils.get_mongo_db()
            list_query = query.copy()
            item_query = query.copy()
            suggestion_query = query.copy()
            if form.start_date.data:
                start_datetime = datetime.combine(form.start_date.data, datetime.min.time())
                list_query['created_at'] = {'$gte': start_datetime}
                item_query['created_at'] = {'$gte': start_datetime}
                suggestion_query['created_at'] = {'$gte': start_datetime}
            if form.end_date.data:
                end_datetime = datetime.combine(form.end_date.data, datetime.max.time())
                list_query['created_at'] = list_query.get('created_at', {}) | {'$lte': end_datetime}
                item_query['created_at'] = item_query.get('created_at', {}) | {'$lte': end_datetime}
                suggestion_query['created_at'] = suggestion_query.get('created_at', {}) | {'$lte': end_datetime}
            lists = [to_dict_shopping_list(lst) for lst in db.shopping_lists.find(list_query).sort('created_at', -1)]
            items = [to_dict_shopping_item(item) for item in db.shopping_items.find(item_query).sort('created_at', -1)]
            suggestions = [to_dict_shopping_suggestion(sug) for sug in db.shopping_suggestions.find(suggestion_query).sort('created_at', -1)]
            shopping_data = {'lists': lists, 'items': items, 'suggestions': suggestions}
            return generate_shopping_report_pdf(shopping_data)
        except Exception as e:
            logger.error(f"Error generating shopping report for user {current_user.id}: {str(e)}", exc_info=True)
            flash(trans('reports_generation_error', default='An error occurred'), 'danger')
    else:
        try:
            db = utils.get_mongo_db()
            lists = [to_dict_shopping_list(lst) for lst in db.shopping_lists.find(query).sort('created_at', -1)]
            items = [to_dict_shopping_item(item) for item in db.shopping_items.find(query).sort('created_at', -1)]
            suggestions = [to_dict_shopping_suggestion(sug) for sug in db.shopping_suggestions.find(query).sort('created_at', -1)]
            shopping_data = {'lists': lists, 'items': items, 'suggestions': suggestions}
        except Exception as e:
            logger.error(f"Error fetching shopping data for user {current_user.id}: {str(e)}", exc_info=True)
            flash(trans('reports_generation_error', default='An error occurred'), 'danger')
    return render_template(
        'reports/shopping.html',
        form=form,
        shopping_data=shopping_data,
        title=utils.trans('reports_shopping', default='Shopping Report', lang=session.get('lang', 'en'))
    )

@reports_bp.route('/admin/customer-reports', methods=['GET', 'POST'])
@login_required
@utils.requires_role('admin')
def customer_reports():
    """Generate customer reports for admin."""
    form = CustomerReportForm()
    if form.validate_on_submit():
        try:
            db = utils.get_mongo_db()
            pipeline = [
                {'$match': {'role': {'$in': ['personal', 'admin']}}},
                {'$lookup': {
                    'from': 'budgets',
                    'let': {'user_id': '$_id'},
                    'pipeline': [
                        {'$match': {'$expr': {'$eq': ['$user_id', '$$user_id']}}},
                        {'$sort': {'created_at': -1}},
                        {'$limit': 1}
                    ],
                    'as': 'latest_budget'
                }},
                {'$lookup': {
                    'from': 'bills',
                    'let': {'user_id': '$_id'},
                    'pipeline': [
                        {'$match': {'$expr': {'$eq': ['$user_id', '$$user_id']}}},
                        {'$group': {
                            '_id': '$status',
                            'count': {'$sum': 1}
                        }}
                    ],
                    'as': 'bill_status_counts'
                }},
                {'$lookup': {
                    'from': 'learning_materials',
                    'let': {'user_id': '$_id'},
                    'pipeline': [
                        {'$match': {'$expr': {'$eq': ['$user_id', '$$user_id']}}},
                        {'$group': {
                            '_id': None,
                            'total_lessons_completed': {'$sum': {'$size': '$lessons_completed'}}
                        }}
                    ],
                    'as': 'learning_progress'
                }}
            ]
            users = list(db.users.aggregate(pipeline))
            report_data = []
            for user in users:
                budget = to_dict_budget(user['latest_budget'][0] if user['latest_budget'] else None)
                bill_counts = {status['_id']: status['count'] for status in user['bill_status_counts']} if user['bill_status_counts'] else {'pending': 0, 'paid': 0, 'overdue': 0}
                learning_progress = user['learning_progress'][0]['total_lessons_completed'] if user['learning_progress'] else 0
                data = {
                    'username': user['_id'],
                    'email': user.get('email', ''),
                    'role': user.get('role', ''),
                    'ficore_credit_balance': user.get('ficore_credit_balance', 0),
                    'language': user.get('language', 'en'),
                    'budget_income': budget['income'] if budget['income'] is not None else '-',
                    'budget_fixed_expenses': budget['fixed_expenses'] if budget['fixed_expenses'] is not None else '-',
                    'budget_variable_expenses': budget['variable_expenses'] if budget['variable_expenses'] is not None else '-',
                    'budget_surplus_deficit': budget['surplus_deficit'] if budget['surplus_deficit'] is not None else '-',
                    'pending_bills': bill_counts.get('pending', 0),
                    'paid_bills': bill_counts.get('paid', 0),
                    'overdue_bills': bill_counts.get('overdue', 0),
                    'lessons_completed': learning_progress
                }
                report_data.append(data)
            return generate_customer_report_pdf(report_data)
        except Exception as e:
            logger.error(f"Error generating customer report: {str(e)}", exc_info=True)
            flash('An error occurred while generating the report', 'danger')
    return render_template('reports/customer_reports_form.html', form=form, title='Generate Customer Report')

def generate_budget_performance_pdf(budget_data):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    # Page setup
    header_height = 0.7
    extra_space = 0.2
    row_height = 0.3
    bottom_margin = 0.5
    max_y = 10.5
    title_y = max_y - header_height - extra_space
    page_height = (max_y - bottom_margin) * inch
    rows_per_page = int((page_height - (title_y - 0.6) * inch) / (row_height * inch))

    def draw_table_headers(y):
        p.setFillColor(colors.black)
        headers = [
            trans('general_date', default='Date'),
            trans('general_income', default='Income'),
            trans('general_actual_income', default='Actual Income'),
            trans('general_income_variance', default='Income Variance'),
            trans('general_fixed_expenses', default='Fixed Expenses'),
            trans('general_variable_expenses', default='Variable Expenses'),
            trans('general_actual_expenses', default='Actual Expenses'),
            trans('general_expense_variance', default='Expense Variance')
        ]
        x_positions = [1 * inch + i * 0.9 * inch for i in range(len(headers))]
        for header, x in zip(headers, x_positions):
            p.drawString(x, y * inch, header)
        return y - row_height, x_positions

    # Initialize first page
    draw_ficore_pdf_header(p, current_user, y_start=max_y)
    p.setFont("Helvetica", 10)
    p.drawString(1 * inch, title_y * inch, trans('reports_budget_performance_report', default='Budget Performance Report'))
    p.drawString(1 * inch, (title_y - 0.3) * inch, f"{trans('reports_generated_on', default='Generated on')}: {utils.format_date(datetime.utcnow())}")
    y = title_y - 0.6
    y, x_positions = draw_table_headers(y)

    row_count = 0
    for bd in budget_data:
        if row_count >= rows_per_page:
            p.showPage()
            draw_ficore_pdf_header(p, current_user, y_start=max_y)
            y = title_y - 0.6
            y, x_positions = draw_table_headers(y)
            row_count = 0

        values = [
            utils.format_date(bd['created_at']),
            utils.format_currency(bd['income']),
            utils.format_currency(bd['actual_income']),
            utils.format_currency(bd['income_variance']),
            utils.format_currency(bd['fixed_expenses']),
            utils.format_currency(bd['variable_expenses']),
            utils.format_currency(bd['actual_expenses']),
            utils.format_currency(bd['expense_variance'])
        ]
        for value, x in zip(values, x_positions):
            p.drawString(x, y * inch, value)
        y -= row_height
        row_count += 1

    p.save()
    buffer.seek(0)
    return Response(buffer, mimetype='application/pdf', headers={'Content-Disposition': 'attachment;filename=budget_performance.pdf'})

def generate_shopping_report_pdf(shopping_data):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    # Page setup
    header_height = 0.7
    extra_space = 0.2
    row_height = 0.3
    section_space = 0.5
    bottom_margin = 0.5
    max_y = 10.5
    title_y = max_y - header_height - extra_space
    page_height = (max_y - bottom_margin) * inch
    rows_per_page = int((page_height - (title_y - 0.6) * inch) / (row_height * inch))

    def draw_list_headers(y):
        p.setFont("Helvetica", 10)
        headers = [
            trans('general_date', default='Date'),
            trans('shopping_list_name', default='List Name'),
            trans('shopping_budget', default='Budget'),
            trans('shopping_total_spent', default='Total Spent'),
            trans('shopping_collaborators', default='Collaborators')
        ]
        x_positions = [1 * inch, 2 * inch, 3.5 * inch, 4.5 * inch, 5.5 * inch]
        for header, x in zip(headers, x_positions):
            p.drawString(x, y * inch, header)
        return y - row_height, x_positions

    def draw_item_headers(y):
        p.setFont("Helvetica", 10)
        headers = [
            trans('general_date', default='Date'),
            trans('shopping_item_name', default='Item Name'),
            trans('shopping_quantity', default='Quantity'),
            trans('shopping_price', default='Price'),
            trans('shopping_status', default='Status'),
            trans('shopping_category', default='Category'),
            trans('shopping_store', default='Store')
        ]
        x_positions = [1 * inch, 2 * inch, 3 * inch, 3.5 * inch, 4 * inch, 4.8 * inch, 5.5 * inch]
        for header, x in zip(headers, x_positions):
            p.drawString(x, y * inch, header)
        return y - row_height, x_positions

    def draw_suggestion_headers(y):
        p.setFont("Helvetica", 10)
        headers = [
            trans('general_date', default='Date'),
            trans('shopping_item_name', default='Item Name'),
            trans('shopping_quantity', default='Quantity'),
            trans('shopping_price', default='Price'),
            trans('shopping_status', default='Status'),
            trans('shopping_category', default='Category')
        ]
        x_positions = [1 * inch, 2 * inch, 3 * inch, 3.5 * inch, 4 * inch, 4.8 * inch]
        for header, x in zip(headers, x_positions):
            p.drawString(x, y * inch, header)
        return y - row_height, x_positions

    # Initialize first page
    draw_ficore_pdf_header(p, current_user, y_start=max_y)
    p.setFont("Helvetica", 12)
    p.drawString(1 * inch, title_y * inch, trans('reports_shopping_report', default='Shopping Report'))
    p.drawString(1 * inch, (title_y - 0.3) * inch, f"{trans('reports_generated_on', default='Generated on')}: {utils.format_date(datetime.utcnow())}")
    y = title_y - 0.6

    # Shopping Lists Section
    p.setFont("Helvetica-Bold", 12)
    p.drawString(1 * inch, y * inch, trans('shopping_lists', default='Shopping Lists'))
    y -= row_height
    y, x_positions = draw_list_headers(y)
    total_budget = 0
    total_spent = 0
    row_count = 0

    for lst in shopping_data['lists']:
        if row_count >= rows_per_page:
            p.showPage()
            draw_ficore_pdf_header(p, current_user, y_start=max_y)
            y = title_y - 0.6
            p.setFont("Helvetica-Bold", 12)
            p.drawString(1 * inch, y * inch, trans('shopping_lists', default='Shopping Lists'))
            y -= row_height
            y, x_positions = draw_list_headers(y)
            row_count = 0

        p.drawString(x_positions[0], y * inch, utils.format_date(lst['created_at']))
        p.drawString(x_positions[1], y * inch, lst['name'][:20])
        p.drawString(x_positions[2], y * inch, utils.format_currency(lst['budget']))
        p.drawString(x_positions[3], y * inch, utils.format_currency(lst['total_spent']))
        p.drawString(x_positions[4], y * inch, ', '.join(lst['collaborators'])[:20])
        total_budget += lst['budget']
        total_spent += lst['total_spent']
        y -= row_height
        row_count += 1

    if row_count + 2 <= rows_per_page:
        y -= row_height
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_budget', default='Total Budget')}: {utils.format_currency(total_budget)}")
        y -= row_height
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_spent', default='Total Spent')}: {utils.format_currency(total_spent)}")
    else:
        p.showPage()
        draw_ficore_pdf_header(p, current_user, y_start=max_y)
        y = title_y - 0.6
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_budget', default='Total Budget')}: {utils.format_currency(total_budget)}")
        y -= row_height
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_spent', default='Total Spent')}: {utils.format_currency(total_spent)}")
    y -= section_space

    # Shopping Items Section
    if row_count + 3 >= rows_per_page:
        p.showPage()
        draw_ficore_pdf_header(p, current_user, y_start=max_y)
        y = title_y - 0.6
        row_count = 0
    p.setFont("Helvetica-Bold", 12)
    p.drawString(1 * inch, y * inch, trans('shopping_items', default='Shopping Items'))
    y -= row_height
    y, x_positions = draw_item_headers(y)
    row_count += 2

    total_price = 0
    for item in shopping_data['items']:
        if row_count >= rows_per_page:
            p.showPage()
            draw_ficore_pdf_header(p, current_user, y_start=max_y)
            y = title_y - 0.6
            p.setFont("Helvetica-Bold", 12)
            p.drawString(1 * inch, y * inch, trans('shopping_items', default='Shopping Items'))
            y -= row_height
            y, x_positions = draw_item_headers(y)
            row_count = 0

        p.drawString(x_positions[0], y * inch, utils.format_date(item['created_at']))
        p.drawString(x_positions[1], y * inch, item['name'][:20])
        p.drawString(x_positions[2], y * inch, str(item['quantity']))
        p.drawString(x_positions[3], y * inch, utils.format_currency(item['price']))
        p.drawString(x_positions[4], y * inch, trans(item['status'], default=item['status']))
        p.drawString(x_positions[5], y * inch, item['category'][:15])
        p.drawString(x_positions[6], y * inch, item['store'][:15])
        total_price += item['price'] * item['quantity']
        y -= row_height
        row_count += 1

    if row_count + 1 <= rows_per_page:
        y -= row_height
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_price', default='Total Price')}: {utils.format_currency(total_price)}")
    else:
        p.showPage()
        draw_ficore_pdf_header(p, current_user, y_start=max_y)
        y = title_y - 0.6
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_price', default='Total Price')}: {utils.format_currency(total_price)}")
    y -= section_space

    # Suggestions Section
    if row_count + 3 >= rows_per_page:
        p.showPage()
        draw_ficore_pdf_header(p, current_user, y_start=max_y)
        y = title_y - 0.6
        row_count = 0
    p.setFont("Helvetica-Bold", 12)
    p.drawString(1 * inch, y * inch, trans('shopping_suggestions', default='Suggestions'))
    y -= row_height
    y, x_positions = draw_suggestion_headers(y)
    row_count += 2

    total_suggestion_price = 0
    for sug in shopping_data['suggestions']:
        if row_count >= rows_per_page:
            p.showPage()
            draw_ficore_pdf_header(p, current_user, y_start=max_y)
            y = title_y - 0.6
            p.setFont("Helvetica-Bold", 12)
            p.drawString(1 * inch, y * inch, trans('shopping_suggestions', default='Suggestions'))
            y -= row_height
            y, x_positions = draw_suggestion_headers(y)
            row_count = 0

        p.drawString(x_positions[0], y * inch, utils.format_date(sug['created_at']))
        p.drawString(x_positions[1], y * inch, sug['name'][:20])
        p.drawString(x_positions[2], y * inch, str(sug['quantity']))
        p.drawString(x_positions[3], y * inch, utils.format_currency(sug['price']))
        p.drawString(x_positions[4], y * inch, trans(sug['status'], default=sug['status']))
        p.drawString(x_positions[5], y * inch, sug['category'][:15])
        total_suggestion_price += sug['price'] * sug['quantity']
        y -= row_height
        row_count += 1

    if row_count + 1 <= rows_per_page:
        y -= row_height
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_suggestion_price', default='Total Suggestion Price')}: {utils.format_currency(total_suggestion_price)}")
    else:
        p.showPage()
        draw_ficore_pdf_header(p, current_user, y_start=max_y)
        y = title_y - 0.6
        p.drawString(x_positions[0], y * inch, f"{trans('shopping_total_suggestion_price', default='Total Suggestion Price')}: {utils.format_currency(total_suggestion_price)}")

    p.save()
    buffer.seek(0)
    return Response(buffer, mimetype='application/pdf', headers={'Content-Disposition': 'attachment;filename=shopping_report.pdf'})

def generate_customer_report_pdf(report_data):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    # Page setup
    header_height = 0.7
    extra_space = 0.2
    row_height = 0.2
    bottom_margin = 0.5
    max_y = 10.5
    title_y = max_y - header_height - extra_space
    page_height = (max_y - bottom_margin) * inch
    rows_per_page = int((page_height - (title_y - 0.6) * inch) / (row_height * inch))

    def draw_table_headers(y):
        p.setFillColor(colors.black)
        headers = [
            'Username', 'Email', 'Role', 'Credits', 'Lang',
            'Income', 'Fixed Exp', 'Var Exp', 'Surplus',
            'Pending Bills', 'Paid Bills', 'Overdue Bills',
            'Lessons'
        ]
        x_positions = [0.5 * inch + i * 0.3 * inch for i in range(len(headers))]
        for header, x in zip(headers, x_positions):
            p.drawString(x, y * inch, header)
        return y - row_height, x_positions

    # Initialize first page
    draw_ficore_pdf_header(p, current_user, y_start=max_y)
    p.setFont("Helvetica", 8)
    p.drawString(0.5 * inch, title_y * inch, trans('reports_customer_report', default='Customer Report'))
    p.drawString(0.5 * inch, (title_y - 0.3) * inch, f"{trans('reports_generated_on', default='Generated on')}: {utils.format_date(datetime.utcnow())}")
    y = title_y - 0.6
    y, x_positions = draw_table_headers(y)

    row_count = 0
    for data in report_data:
        if row_count >= rows_per_page:
            p.showPage()
            draw_ficore_pdf_header(p, current_user, y_start=max_y)
            y = title_y - 0.6
            y, x_positions = draw_table_headers(y)
            row_count = 0

        values = [
            data['username'], data['email'], data['role'], str(data['ficore_credit_balance']), data['language'],
            str(data['budget_income']), str(data['budget_fixed_expenses']), str(data['budget_variable_expenses']), str(data['budget_surplus_deficit']),
            str(data['pending_bills']), str(data['paid_bills']), str(data['overdue_bills']),
            str(data['lessons_completed'])
        ]
        for value, x in zip(values, x_positions):
            p.drawString(x, y * inch, str(value)[:15])
        y -= row_height
        row_count += 1

    p.save()
    buffer.seek(0)
    return Response(buffer, mimetype='application/pdf', headers={'Content-Disposition': 'attachment;filename=customer_report.pdf'})
