from flask import Blueprint

shopping_bp = Blueprint('shopping', __name__, template_folder='templates')

from .shopping import *