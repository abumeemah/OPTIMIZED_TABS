from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from translations import trans
import utils
from bson import ObjectId
from datetime import datetime
import logging
from utils import logger

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@dashboard_bp.route('/')
@login_required
def index():
    """Display the user's dashboard with personal finance summary."""
    try:
        db = utils.get_mongo_db()
        
        # Determine query based on user role
        query = {} if utils.is_admin() else {'user_id': str(current_user.id)}

        # Initialize data container
        personal_finance_summary = {}

        # Fetch personal finance data for personal users and admins
        if current_user.role in ['personal', 'admin']:
            try:
                # Get latest records from each personal finance tool
                latest_budget = db.budgets.find_one(query, sort=[('created_at', -1)])
                latest_bill = db.bills.find_one(query, sort=[('created_at', -1)])
                latest_shopping_list = db.shopping_lists.find_one(query, sort=[('created_at', -1)])

                # Count total records
                total_budgets = db.budgets.count_documents(query)
                total_bills = db.bills.count_documents(query)
                overdue_bills = db.bills.count_documents({**query, 'status': 'overdue'})
                total_shopping_lists = db.shopping_lists.count_documents(query)

                # Calculate total shopping spent and budget
                shopping_lists = db.shopping_lists.find(query)
                total_shopping_spent = sum(
                    float(item.get('total_amount', 0)) for item in shopping_lists
                    if item.get('total_amount') is not None
                )
                total_shopping_budget = sum(
                    float(item.get('budget', 0)) for item in db.shopping_lists.find(query)
                    if item.get('budget') is not None
                )

                personal_finance_summary = {
                    'latest_budget': latest_budget,
                    'latest_bill': latest_bill,
                    'total_budgets': total_budgets,
                    'total_bills': total_bills,
                    'overdue_bills': overdue_bills,
                    'latest_shopping_list': latest_shopping_list,
                    'total_shopping_lists': total_shopping_lists,
                    'total_shopping_spent': total_shopping_spent,
                    'total_shopping_budget': total_shopping_budget,
                    'has_personal_data': any([latest_budget, latest_bill, latest_shopping_list, total_shopping_lists > 0])
                }
            except Exception as e:
                logger.error(f"Error fetching personal finance data for user {current_user.id}: {str(e)}")
                personal_finance_summary = {
                    'has_personal_data': False,
                    'total_shopping_lists': 0,
                    'total_shopping_spent': 0.0,
                    'total_shopping_budget': 0.0
                }

        return render_template(
            'dashboard/index.html',
            personal_finance_summary=personal_finance_summary
        )
    except Exception as e:
        logger.error(f"Error fetching dashboard data for user {current_user.id}: {str(e)}")
        flash(trans('dashboard_load_error', default='An error occurred while loading the dashboard'), 'danger')
        return redirect(url_for('general_bp.home'))
