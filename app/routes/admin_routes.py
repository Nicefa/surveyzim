from flask import render_template
from flask_login import login_required
from . import bp  # blueprint from __init__.py

# Example admin dashboard route
@bp.route("/admin/dashboard")
@login_required
def admin_dashboard():
    # You can add admin checks here later
    return render_template("admin_dashboard.html")
