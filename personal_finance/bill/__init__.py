from flask import Blueprint

bill_bp = Blueprint('bill', __name__, template_folder='templates')

from .bill import *