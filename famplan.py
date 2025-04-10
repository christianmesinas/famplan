import sqlalchemy as sa
import sqlalchemy.orm as so
from app import app, db, cli
from app.models import User, Post, Message, Notification, Task

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


@app.shell_context_processor
def make_shell_context():
    return {'sa': sa, 'so': so, 'db': db, 'User': User, 'Post': Post, 'Message': Message, 'Notification': Notification, 'Task': Task}