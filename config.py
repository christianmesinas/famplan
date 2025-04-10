import os
from dotenv import load_dotenv, find_dotenv
basedir = os.path.abspath(os.path.dirname(__file__))

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

class Config:
    SECRET_KEY = os.getenv('APP_SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT =int(os.getenv('MAIL_PORT'))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    ADMINS = ['chris1991.cg@gmail.com']
    LANGUAGES= ['en', 'es']
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
    MS_TRANSLATOR_KEY = os.environ.get('MS_TRANSLATOR_KEY')
    POSTS_PER_PAGE = 25
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    AUTH0_DOMAIN = os.getenv('AUTH0_DOMAIN')
    AUTH0_CLIENT_ID = os.getenv('AUTH0_CLIENT_ID')
    AUTH0_CLIENT_SECRET = os.getenv('AUTH0_CLIENT_SECRET')
