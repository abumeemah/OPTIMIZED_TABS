from flask import Blueprint

summaries_bp = Blueprint('summaries', __name__, template_folder='templates')

from .routes import *