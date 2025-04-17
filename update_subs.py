from app import create_app, db
from app.models import User

app = create_app()
with app.app_context():
    users = User.query.filter(User.sub.is_(None)).all()
    for user in users:
        user.sub = f"manual|{user.id}"
    db.session.commit()