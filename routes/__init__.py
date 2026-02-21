from flask import Blueprint


def register_blueprints(app):
    """Register all blueprints"""
    from routes.auth import auth_bp
    from routes.registration import registration_bp
    from routes.attendance import attendance_bp
    from routes.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(reports_bp)
