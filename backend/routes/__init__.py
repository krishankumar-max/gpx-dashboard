"""
backend.routes — Flask Blueprint package.

Call register_blueprints(app) after the Flask app is created and services
are attached to the app object.
"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from backend.routes.auth           import bp as auth_bp
    from backend.routes.core_bp        import bp as core_bp
    from backend.routes.overview_bp    import bp as overview_bp
    from backend.routes.health_bp      import bp as health_bp
    from backend.routes.publishers_bp  import bp as publishers_bp
    from backend.routes.offers_bp      import bp as offers_bp
    from backend.routes.analytics_bp   import bp as analytics_bp
    from backend.routes.admin_bp       import bp as admin_bp
    from backend.routes.sync_bp        import bp as sync_bp
    from backend.routes.structures_bp  import bp as structures_bp

    for blueprint in (
        auth_bp, core_bp, overview_bp, health_bp, publishers_bp,
        offers_bp, analytics_bp, admin_bp, sync_bp, structures_bp,
    ):
        app.register_blueprint(blueprint)
