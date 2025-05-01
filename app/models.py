import secrets
from datetime import datetime, timezone, timedelta
from hashlib import md5
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
import json
import time
import redis
import rq
from flask import current_app, url_for  # Gebruik current_app voor app-context

# Klasse om paginatie en API-respons te ondersteunen
class PaginatedAPIMixin(object):
    # Methode om een paginated query om te zetten naar een dictionary voor API-respons
    @staticmethod
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        # Pagineer de query met de opgegeven pagina en items per pagina
        resources = db.paginate(query, page=page, per_page=per_page, error_out=False)
        # Maak een dictionary met de items, metadata en links naar andere pagina's
        data = {
            'items': [item.to_dict() for item in resources.items], # Converteer elk item naar een dictionary
            '_meta': {'page': page, 'per_page': per_page, 'total_pages': resources.pages, 'total_items': resources.total},
            # Metadata over de paginatie
            '_links': {
                'self': url_for(endpoint, page=page, per_page=per_page, **kwargs),
                'next': url_for(endpoint, page=page + 1, per_page=per_page, **kwargs) if resources.has_next else None,
                'prev': url_for(endpoint, page=page - 1, per_page=per_page, **kwargs) if resources.has_prev else None
            }
        }
        return data

# Definieer de 'followers' tabel voor een many-to-many relatie tussen gebruikers (voor volgen/volgers)
followers = sa.Table(
    'followers', # Naam van de tabel
    db.metadata,
    sa.Column('follower_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True),
    sa.Column('followed_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True)
)
# Klasse gebruiker
class User(PaginatedAPIMixin, db.Model):
    # Definitie kolommen
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True)
    sub = db.Column(db.String(120), index=True, unique=True, nullable=False)  # Auth0
    last_message_read_time: so.Mapped[Optional[datetime]]
    token: so.Mapped[Optional[str]] = so.mapped_column(sa.String(32), index=True, unique=True)
    token_expiration: so.Mapped[Optional[datetime]]

    # Relaties met andere tabellen (gebruik WriteOnlyMapped voor efficiënte queries)
    posts: so.WriteOnlyMapped['Post'] = so.relationship(back_populates='author')
    notifications: so.WriteOnlyMapped['Notification'] = so.relationship(back_populates='user')
    tasks: so.WriteOnlyMapped['Task'] = so.relationship(back_populates='user')
    about_me: so.Mapped[Optional[str]] = so.mapped_column(sa.String(140))
    last_seen: so.Mapped[Optional[datetime]] = so.mapped_column(default=lambda: datetime.now(timezone.utc))
    calendar_credentials: so.WriteOnlyMapped['CalendarCredentials'] = so.relationship(back_populates='user')

    # Many-to-many relaties voor volgen/volgers
    following: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id), back_populates='followers')
    followers: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.followed_id == id),
        secondaryjoin=(followers.c.follower_id == id), back_populates='following')
    messages_sent: so.WriteOnlyMapped['Message'] = so.relationship(foreign_keys='Message.sender_id', back_populates='author')
    messages_received: so.WriteOnlyMapped['Message'] = so.relationship(foreign_keys='Message.recipient_id', back_populates='recipient')

    # Stringrepresentatie van de gebruiker (voor debugging)
    def __repr__(self):
        return '<User {}>'.format(self.username)

    # Genereer een Gravatar URL gebaseerd op het e-mailadres van de gebruiker
    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return f'https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}'

    # Volg een andere gebruiker
    def follow(self, user):
        if not self.is_following(user):
            self.following.add(user)

    # Ontvolg een andere gebruiker
    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)

    # Controleer of deze gebruiker een andere gebruiker volgt
    def is_following(self, user):
        query = self.following.select().where(User.id == user.id)
        return db.session.scalar(query) is not None

    # Tel het aantal volgers van deze gebruiker
    def followers_count(self):
        query = sa.select(sa.func.count()).select_from(self.followers.select().subquery())
        return db.session.scalar(query)

    # Tel het aantal gebruikers dat deze gebruiker volgt
    def following_count(self):
        query = sa.select(sa.func.count()).select_from(self.following.select().subquery())
        return db.session.scalar(query)


    # Haal posts op van gebruikers die deze gebruiker volgt (inclusief eigen posts)
    def following_posts(self):
        Author = so.aliased(User)
        Follower = so.aliased(User)
        return (
            sa.select(Post)
            .join(Post.author.of_type(Author))
            .join(Author.followers.of_type(Follower), isouter=True)
            .where(sa.or_(Follower.id == self.id, Author.id == self.id))
            .group_by(Post)
            .order_by(Post.timestamp.desc())
        )

    # Tel het aantal ongelezen berichten van deze gebruiker
    def unread_message_count(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        query = sa.select(Message).where(Message.recipient == self, Message.timestamp > last_read_time)
        return db.session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))


    # Voeg een notificatie toe voor deze gebruiker (vervang bestaande notificatie met dezelfde naam)
    def add_notification(self, name, data):
        db.session.execute(self.notifications.delete().where(Notification.name == name))
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    # Genereer een nieuwe API-token voor deze gebruiker
    def get_token(self, expires_in=3600):
        now = datetime.now(timezone.utc)
        if self.token and self.token_expiration.replace(tzinfo=timezone.utc) > now + timedelta(seconds=60):
            return self.token
        self.token = secrets.token_hex(16)
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    # Maak de huidige API-token ongeldig
    def revoke_token(self):
        self.token_expiration = datetime.now(timezone.utc) - timedelta(seconds=1)

    # Controleer of een API-token geldig is en retourneer de bijbehorende gebruiker
    @staticmethod
    def check_token(token):
        user = db.session.scalar(sa.select(User).where(User.token == token))
        if user is None or user.token_expiration.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        return user

# Klasse die een post van een gebruiker
class Post(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(index=True, default=lambda: datetime.now(timezone.utc))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    author: so.Mapped[User] = so.relationship(back_populates='posts')

    # Stringrepresentatie van het bericht (voor debugging)
    def __repr__(self):
        return '<Post {}>'.format(self.body)

# Klasse voor privéberichten tussen gebruikers
class Message(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    sender_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    recipient_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(index=True, default=lambda: datetime.now(timezone.utc))
    author: so.Mapped[User] = so.relationship(foreign_keys='Message.sender_id', back_populates='messages_sent')
    recipient: so.Mapped[User] = so.relationship(foreign_keys='Message.recipient_id', back_populates='messages_received')

    # Stringrepresentatie van het bericht (voor debugging)
    def __repr__(self):
        return '<Message {}>'.format(self.body)

# Klasse die een notificatie voor een gebruiker
class Notification(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    timestamp: so.Mapped[float] = so.mapped_column(index=True, default=time.time)
    payload_json: so.Mapped[str] = so.mapped_column(sa.Text)
    user: so.Mapped[User] = so.relationship(back_populates='notifications')

    # Haal de JSON-data op als een Python-object
    def get_data(self):
        return json.loads(str(self.payload_json))

# Klasse die een taak van een gebruiker
class Task(db.Model):
    id: so.Mapped[str] = so.mapped_column(sa.String(36), primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id))
    complete: so.Mapped[bool] = so.mapped_column(default=False)
    user: so.Mapped[User] = so.relationship(back_populates='tasks')

    # Haal de RQ-job op die bij deze taak hoort
    def get_rq_job(self):
        try:
            # Gebruik current_app.config voor Redis-verbinding
            redis_url = current_app.config['REDIS_URL']
            redis_conn = redis.Redis.from_url(redis_url)
            rq_job = rq.job.Job.fetch(self.id, connection=redis_conn)
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    # Haal de voortgang van de taak op
    def get_progress(self):
        job = self.get_rq_job()
        return job.meta.get('progress', 0) if job is not None else 100

# Klasse die de kalenderreferenties van een gebruiker opslaat (voor integratie met Google Calendar)
class CalendarCredentials(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    token: so.Mapped[str] = so.mapped_column(sa.Text)
    refresh_token: so.Mapped[str] = so.mapped_column(sa.String(200))
    token_uri: so.Mapped[str] = so.mapped_column(sa.String(200))
    client_id: so.Mapped[str] = so.mapped_column(sa.String(200))
    client_secret: so.Mapped[str] = so.mapped_column(sa.String(200))
    scopes: so.Mapped[str] = so.mapped_column(sa.Text)
    expiry: so.Mapped[datetime] = so.mapped_column()

    user: so.Mapped[User] = so.relationship(back_populates='calendar_credentials')