from flask import Blueprint

# Create a blueprint for user-facing routes
bp = Blueprint("main", __name__)

# Import the user routes so they register with the blueprint
from . import user_routes, admin_routes
