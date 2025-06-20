import os
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import logging
from logging.handlers import SMTPHandler, RotatingFileHandler
from flask_mail import Mail
from flask_moment import Moment
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth

# Initialiseer Flask-extensies
db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
moment = Moment()
oauth = OAuth()

load_dotenv()  # Laad omgevingsvariabelen uit .env bestand

def create_app():
    app = Flask(__name__, static_folder='static')
    app.config.from_object(Config)
    app.secret_key = os.getenv('APP_SECRET_KEY')

    # Initialiseer extensies met app
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    moment.init_app(app)
    oauth.init_app(app)

    # Configureer OAuth voor Auth0
    oauth.register(
        'auth0',
        client_id=os.getenv('AUTH0_CLIENT_ID'),
        client_secret=os.getenv('AUTH0_CLIENT_SECRET'),
        server_metadata_url=f"https://{os.getenv('AUTH0_DOMAIN')}/.well-known/openid-configuration",
        client_kwargs={'scope': 'openid profile email'},
    )

    # Configureer logging (alleen in productie)
    if not app.debug:
        # Email-logging voor errors
        if app.config['MAIL_SERVER']:
            auth = None
            if app.config['MAIL_USERNAME'] or app.config['MAIL_PASSWORD']:
                auth = (app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            secure = None
            if app.config['MAIL_USE_TLS']:
                secure = ()
            mail_handler = SMTPHandler(
                mailhost=(app.config['MAIL_SERVER'], app.config['MAIL_PORT']),
                fromaddr='no-reply@' + app.config['MAIL_SERVER'],
                toaddrs=app.config['ADMINS'], subject='famplan Failure',
                credentials=auth, secure=secure)
            mail_handler.setLevel(logging.ERROR)
            app.logger.addHandler(mail_handler)

        # File-logging voor alle events
        if not os.path.exists('logs'):
            os.mkdir('logs')
        file_handler = RotatingFileHandler('logs/famplan.log', maxBytes=10240, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('famplan startup')

    # Importeer app-modules
    from app import routes, models
    routes.register_routes(app)

    # Registreer calendar blueprint
    from app.calendar import bp as calendar_bp
    app.register_blueprint(calendar_bp)

    return app