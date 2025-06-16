import secrets
from datetime import datetime, timezone, timedelta
from hashlib import md5
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
# ──────────────────────────────────────────────────────────────────────────────
# NEW: import the association_proxy helper
from sqlalchemy.ext.associationproxy import association_proxy
# ──────────────────────────────────────────────────────────────────────────────
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
        resources = db.paginate(query, page=page, per_page=per_page, error_out=False)
        data = {
            'items': [item.to_dict() for item in resources.items],
            '_meta': {
                'page': page,
                'per_page': per_page,
                'total_pages': resources.pages,
                'total_items': resources.total
            },
            '_links': {
                'self':  url_for(endpoint, page=page, per_page=per_page, **kwargs),
                'next':  url_for(endpoint, page=page+1, per_page=per_page, **kwargs) if resources.has_next else None,
                'prev':  url_for(endpoint, page=page-1, per_page=per_page, **kwargs) if resources.has_prev else None
            }
        }
        return data

# Definieer de 'followers' tabel voor een many-to-many relatie tussen gebruikers
followers = sa.Table(
    'followers',
    db.metadata,
    sa.Column('follower_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True),
    sa.Column('followed_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True)
)

# -------------------------------------------------------------------
# Nieuwe modellen voor familie-functionaliteit
# -------------------------------------------------------------------

class Family(db.Model):
    """Vertegenwoordigt een gezinsgroep waartoe meerdere gebruikers behoren."""
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)

    # relatie naar FamilyInvite
    invites: so.Mapped[list['FamilyInvite']] = so.relationship(
        'FamilyInvite',
        back_populates='family',
        cascade='all, delete-orphan',
        doc="Alle uitnodigingen behorend bij deze family"
    )

    # Relatie naar de Membership-koppeltabel (de “write path”)
    memberships: so.Mapped[list['Membership']] = so.relationship(
        'Membership',
        back_populates='family',
        cascade='all, delete-orphan',
        doc="Membership-objecten (elk lid heeft er één)"
    )

    # ────────────────────────────────────────────────────────────────────────
    # NEW: een “read-only shortcut” naar alle User-objecten in deze Family.
    # Gebruik association_proxy zodat we geen overlapping relationships krijgen.
    members = association_proxy(
        'memberships',  # verwijst naar Membership.user
        'user'         # haalt het user-object uit elke membership
    )
    # ────────────────────────────────────────────────────────────────────────

class Membership(db.Model):
    """
    Koppeltabel tussen User en Family (lidmaatschap).
    Voorkomt dubbele inschrijvingen door een UNIQUE-constrainte
    op (user_id, family_id).
    """
    __tablename__ = 'membership'
    __table_args__ = (
        # Zorg dat elke (user, family)-combinatie slechts één keer voorkomt
        sa.UniqueConstraint('user_id', 'family_id', name='uq_membership_user_family'),
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    user_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey('user.id'),
        nullable=False,
        doc="FK naar de User die lid is"
    )
    family_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey('family.id'),
        nullable=False,
        doc="FK naar de Family waartoe lidmaatschap hoort"
    )

    # Relatie terug naar User
    user: so.Mapped['User'] = so.relationship(
        'User',
        back_populates='memberships',
        doc="De User die deelneemt aan deze membership"
    )
    # Relatie terug naar Family
    family: so.Mapped['Family'] = so.relationship(
        'Family',
        back_populates='memberships',
        doc="De Family waartoe deze membership behoort"
    )


# -------------------------------------------------------------------
# Uitnodigings-model voor discrete, token-gebaseerde toegang tot families
# -------------------------------------------------------------------

class FamilyInvite(db.Model):
    """
    Slaat uitnodigingen voor families op.
    - Elke invite heeft een unieke token.
    - Optioneel gebonden aan een e-mailadres.
    - Kan verlopen of worden geaccepteerd.
    """
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    family_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey('family.id'), nullable=False, index=True
    )
    token: so.Mapped[str] = so.mapped_column(
        sa.String(32), unique=True, nullable=False,
        doc="Unieke, moeilijk te raden join-token"
    )
    invited_email: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(120), nullable=True,
        doc="E-mail waarnaar je de uitnodiging stuurt (optioneel)"
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc),
        doc="Tijdstip waarop de invite is aangemaakt"
    )
    expires_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        nullable=True,
        doc="Optioneel vervaltijdstip (bijv. 7 dagen na creatie)"
    )
    accepted: so.Mapped[bool] = so.mapped_column(
        default=False,
        doc="Wordt True zodra de invite is geaccepteerd"
    )

    # Relationship back to Family
    family: so.Mapped['Family'] = so.relationship(
        'Family', back_populates='invites'
    )

# -------------------------------------------------------------------
# User-model met extra relaties voor families
# -------------------------------------------------------------------

class User(PaginatedAPIMixin, db.Model):
    # Kolommen
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True)
    sub = db.Column(db.String(120), index=True, unique=True, nullable=False)  # Auth0 sub
    last_message_read_time: so.Mapped[Optional[datetime]]
    token: so.Mapped[Optional[str]] = so.mapped_column(sa.String(32), index=True, unique=True)
    token_expiration: so.Mapped[Optional[datetime]]
    profile_image: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128), nullable=True)
    profile_image_data = db.Column(db.LargeBinary, nullable=True)  # Voor de binaire data van de foto
    profile_image_mime = db.Column(db.String(64), nullable=True)  # Voor de MIME-type (bijv. image/jpeg)

    # Relaties met andere entiteiten
    posts: so.WriteOnlyMapped['Post'] = so.relationship(back_populates='author')
    notifications: so.WriteOnlyMapped['Notification'] = so.relationship(back_populates='user')
    tasks: so.WriteOnlyMapped['Task'] = so.relationship(back_populates='user')
    about_me: so.Mapped[Optional[str]] = so.mapped_column(sa.String(140))
    last_seen: so.Mapped[Optional[datetime]] = so.mapped_column(default=lambda: datetime.now(timezone.utc))
    calendar_credentials: so.WriteOnlyMapped['CalendarCredentials'] = so.relationship(back_populates='user')

    # Many-to-many voor volgen/volgers
    following: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        back_populates='followers'
    )
    followers: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers,
        primaryjoin=(followers.c.followed_id == id),
        secondaryjoin=(followers.c.follower_id == id),
        back_populates='following'
    )

    # -------------------------------------------------------------------
    # Nieuwe relaties voor Family/Membership
    # -------------------------------------------------------------------

    # -------------------------------------------------------------------
    # Lidmaatschapsrelatie: welke Membership objects horen bij deze User?
    # (dit is de “write”-kant van User <--> Family via Membership)
    # -------------------------------------------------------------------
    memberships: so.Mapped[list['Membership']] = so.relationship(
        'Membership',
        back_populates='user',
        cascade='all, delete-orphan',
        doc="Alle Family-memberships voor deze user"
    )

    # ────────────────────────────────────────────────────────────────────────
    # NEW: association_proxy voor families: directe lijst van Family-objecten
    families = association_proxy(
        'memberships',  # verwijzing naar Membership.family
        'family'      # haalt het family-object uit elke membership
    )
    # ────────────────────────────────────────────────────────────────────────

    # Berichten-relaties
    messages_sent: so.WriteOnlyMapped['Message'] = so.relationship(
        foreign_keys='Message.sender_id',
        back_populates='author'
    )
    messages_received: so.WriteOnlyMapped['Message'] = so.relationship(
        foreign_keys='Message.recipient_id',
        back_populates='recipient'
    )

    def __repr__(self):
        return f'<User {self.username}>'

    # Bestaande methodes (avatar, follow, unread_message_count, etc.) hieronder…
    def avatar(self, size):
        if self.profile_image_data:  # Als er een foto in de database staat
            return url_for('get_profile_image', user_id=self.id, _external=True)
        # Fallback naar Gravatar
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return f'https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}'


    def follow(self, user):
        if not self.is_following(user):
            self.following.add(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)

    def is_following(self, user):
        query = self.following.select().where(User.id == user.id)
        return db.session.scalar(query) is not None

    def followers_count(self):
        query = sa.select(sa.func.count()).select_from(self.followers.select().subquery())
        return db.session.scalar(query)

    def following_count(self):
        query = sa.select(sa.func.count()).select_from(self.following.select().subquery())
        return db.session.scalar(query)

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

    def unread_message_count(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        query = sa.select(Message).where(
            Message.recipient == self,
            Message.timestamp > last_read_time
        )
        return db.session.scalar(
            sa.select(sa.func.count()).select_from(query.subquery())
        )

    def add_notification(self, name, data):
        db.session.execute(
            self.notifications.delete().where(Notification.name == name)
        )
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    def get_token(self, expires_in=3600):
        now = datetime.now(timezone.utc)
        if (self.token and
            self.token_expiration.replace(tzinfo=timezone.utc) > now + timedelta(seconds=60)):
            return self.token
        self.token = secrets.token_hex(16)
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    def revoke_token(self):
        self.token_expiration = datetime.now(timezone.utc) - timedelta(seconds=1)

    @staticmethod
    def check_token(token):
        user = db.session.scalar(sa.select(User).where(User.token == token))
        if (user is None or
            user.token_expiration.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)):
            return None
        return user

# Bestaande: Post-model
class Post(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(500))
    timestamp: so.Mapped[datetime] = so.mapped_column(
        index=True, default=lambda: datetime.now(timezone.utc)
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    author: so.Mapped[User] = so.relationship(back_populates='posts')

    # maakt mogelijk om familie-gebonden posts te maken
    family_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey('family.id'), nullable=True, index=True
    )
    family: so.Mapped[Optional['Family']] = so.relationship('Family', backref='posts')

    def __repr__(self):
        return f'<Post {self.body}>'

# Bestaande: Message-model
class Message(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    sender_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    recipient_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(
        index=True, default=lambda: datetime.now(timezone.utc)
    )
    author: so.Mapped[User] = so.relationship(
        foreign_keys='Message.sender_id', back_populates='messages_sent'
    )
    recipient: so.Mapped[User] = so.relationship(
        foreign_keys='Message.recipient_id', back_populates='messages_received'
    )

    def __repr__(self):
        return f'<Message {self.body}>'

# Bestaande: Notification-model
class Notification(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    timestamp: so.Mapped[float] = so.mapped_column(index=True, default=time.time)
    payload_json: so.Mapped[str] = so.mapped_column(sa.Text)
    user: so.Mapped[User] = so.relationship(back_populates='notifications')

    def get_data(self):
        return json.loads(str(self.payload_json))

# Bestaande: Task-model
class Task(db.Model):
    id: so.Mapped[str] = so.mapped_column(sa.String(36), primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id))
    complete: so.Mapped[bool] = so.mapped_column(default=False)
    user: so.Mapped[User] = so.relationship(back_populates='tasks')

# Bestaande: CalendarCredentials-model
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
