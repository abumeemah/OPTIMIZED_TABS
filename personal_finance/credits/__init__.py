from flask import Blueprint

credits_bp = Blueprint('credits', __name__, template_folder='templates')

from .routes import *
