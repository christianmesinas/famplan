import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, create_app
from app.models import User, Post, Message, Notification, Task
from flask_migrate import Migrate

app = create_app()
migrate = Migrate(app, db)


@app.shell_context_processor
def make_shell_context():
    return {'sa': sa, 'so': so, 'db': db, 'User': User, 'Post': Post, 'Message': Message, 'Notification': Notification, 'Task': Task}