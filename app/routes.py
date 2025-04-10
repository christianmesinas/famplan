from flask import session, render_template, flash, redirect, url_for, request, g, current_app, jsonify
from flask_babel import _, get_locale
import sqlalchemy as sa
from app import db, oauth  # Gebruik oauth in plaats van auth0
from app.forms import PostForm, EditProfileForm, EmptyForm, MessageForm
from app.models import User, Post, Message, Notification
from langdetect import detect, LangDetectException
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.DEBUG)

def get_current_user():
    if 'user' in session:
        user_info = session['user']['userinfo']
        current_app.logger.debug(f"Checking user with email: {user_info['email']}")
        user = db.session.scalar(sa.select(User).where(User.email == user_info['email']))
        if not user:
            current_app.logger.debug("User not found in database, should have been created in callback")
        return user
    current_app.logger.debug("No user in session")
    return None

def register_routes(app):
    # Contextprocessor
    @app.context_processor
    def inject_current_user():
        return dict(get_current_user=get_current_user)

    # Before request
    @app.before_request
    def before_request():
        user = get_current_user()
        if user:
            user.last_seen = datetime.now(timezone.utc)
            db.session.commit()
        g.locale = str(get_locale())

    @app.route('/login')
    def login():
        if 'user' in session:
            return redirect(url_for('index'))
        return oauth.auth0.authorize_redirect(redirect_uri='http://localhost:5000/callback')

    @app.route('/callback')
    def callback():
        try:
            token = oauth.auth0.authorize_access_token()
            app.logger.debug(f"Token received: {token}")
            session['user'] = token
            user_info = token['userinfo']
            app.logger.debug(f"User info: {user_info}")
            user = db.session.scalar(sa.select(User).where(User.email == user_info['email']))
            if not user:
                user = User(
                    username=user_info.get('nickname', user_info['email'].split('@')[0]),
                    email=user_info['email']
                )
                db.session.add(user)
                db.session.commit()
                app.logger.debug(f"New user added: {user.email}")
            else:
                app.logger.debug(f"Existing user found: {user.email}")
            app.logger.debug(f"Session after callback: {session}")
            return redirect(url_for('index'))
        except Exception as e:
            app.logger.error(f"Error in callback: {str(e)}")
            return "An error occurred during login", 500

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(
            f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
            f"returnTo={url_for('index', _external=True)}&client_id={app.config['AUTH0_CLIENT_ID']}"
        )

    @app.route('/api/users', methods=['POST'])
    def create_user():
        data = request.get_json()
        if not data or 'email' not in data:
            return jsonify({'error': 'Email is required'}), 400
        user = db.session.scalar(sa.select(User).where(User.email == data['email']))
        if not user:
            user = User(
                email=data['email'],
                username=data.get('username', data['email'].split('@')[0]),
            )
            db.session.add(user)
            db.session.commit()
            app.logger.debug(f"User created: {user.email}")
        return jsonify({'message': 'User created'}), 201

    @app.route('/', methods=['GET', 'POST'])
    @app.route('/index', methods=['GET', 'POST'])
    def index():
        if 'user' not in session:
            app.logger.debug("No user in session, redirecting to login")
            return redirect(url_for('login'))
        user = get_current_user()
        if user is None:
            app.logger.error("User is None despite session, forcing logout")
            session.clear()
            return redirect(url_for('login'))
        form = PostForm()
        if form.validate_on_submit():
            try:
                language = detect(form.post.data)
            except LangDetectException:
                language = ''
            post = Post(body=form.post.data, author=user, language=language)
            db.session.add(post)
            db.session.commit()
            flash(_('Your post is now live!'))
            return redirect(url_for('index'))
        page = request.args.get('page', 1, type=int)
        posts = db.paginate(user.following_posts(), page=page,
                            per_page=app.config['POSTS_PER_PAGE'], error_out=False)
        next_url = url_for('index', page=posts.next_num) if posts.has_next else None
        prev_url = url_for('index', page=posts.prev_num) if posts.has_prev else None
        return render_template('index.html', title=_('Home'), form=form,
                               posts=posts.items, next_url=next_url, prev_url=prev_url)

    @app.route('/explore')
    def explore():
        if 'user' not in session:
            return redirect(url_for('login'))
        page = request.args.get('page', 1, type=int)
        query = sa.select(Post).order_by(Post.timestamp.desc())
        posts = db.paginate(query, page=page,
                            per_page=app.config['POSTS_PER_PAGE'], error_out=False)
        next_url = url_for('explore', page=posts.next_num) if posts.has_next else None
        prev_url = url_for('explore', page=posts.prev_num) if posts.has_prev else None
        return render_template('index.html', title=_('Explore'),
                               posts=posts.items, next_url=next_url, prev_url=prev_url)

    @app.route('/user/<username>')
    def user(username):
        if 'user' not in session:
            return redirect(url_for('login'))
        user = db.first_or_404(sa.select(User).where(User.username == username))
        page = request.args.get('page', 1, type=int)
        query = user.posts.select().order_by(Post.timestamp.desc())
        posts = db.paginate(query, page=page,
                            per_page=app.config['POSTS_PER_PAGE'], error_out=False)
        next_url = url_for('user', username=user.username, page=posts.next_num) if posts.has_next else None
        prev_url = url_for('user', username=user.username, page=posts.prev_num) if posts.has_prev else None
        form = EmptyForm()
        return render_template('user.html', user=user, posts=posts.items,
                               next_url=next_url, prev_url=prev_url, form=form)

    @app.route('/edit_profile', methods=['GET', 'POST'])
    def edit_profile():
        if 'user' not in session:
            return redirect(url_for('login'))
        user = get_current_user()
        form = EditProfileForm(user.username)
        if form.validate_on_submit():
            user.username = form.username.data
            user.about_me = form.about_me.data
            db.session.commit()
            flash(_('Your changes have been saved.'))
            return redirect(url_for('edit_profile'))
        elif request.method == 'GET':
            form.username.data = user.username
            form.about_me.data = user.about_me
        return render_template('edit_profile.html', title=_('Edit Profile'), form=form)

    @app.route('/follow/<username>', methods=['POST'])
    def follow(username):
        if 'user' not in session:
            return redirect(url_for('login'))
        form = EmptyForm()
        if form.validate_on_submit():
            user = db.session.scalar(sa.select(User).where(User.username == username))
            current_user = get_current_user()
            if user is None:
                flash(_('User %(username)s not found.', username=username))
                return redirect(url_for('index'))
            if user == current_user:
                flash(_('You cannot follow yourself!'))
                return redirect(url_for('user', username=username))
            current_user.follow(user)
            db.session.commit()
            flash(_('You are following %(username)s!', username=username))
            return redirect(url_for('user', username=username))
        return redirect(url_for('index'))

    @app.route('/unfollow/<username>', methods=['POST'])
    def unfollow(username):
        if 'user' not in session:
            return redirect(url_for('login'))
        form = EmptyForm()
        if form.validate_on_submit():
            user = db.session.scalar(sa.select(User).where(User.username == username))
            current_user = get_current_user()
            if user is None:
                flash(_('User %(username)s not found.', username=username))
                return redirect(url_for('index'))
            if user == current_user:
                flash(_('You cannot unfollow yourself!'))
                return redirect(url_for('user', username=username))
            current_user.unfollow(user)
            db.session.commit()
            flash(_('You are not following %(username)s.', username=username))
            return redirect(url_for('user', username=username))
        return redirect(url_for('index'))

    @app.route('/messages')
    def messages():
        if 'user' not in session:
            return redirect(url_for('login'))
        current_user = get_current_user()
        current_user.last_message_read_time = datetime.now(timezone.utc)
        current_user.add_notification('unread_message_count', 0)
        db.session.commit()
        page = request.args.get('page', 1, type=int)
        query = current_user.messages_received.select().order_by(Message.timestamp.desc())
        messages = db.paginate(query, page=page,
                               per_page=app.config['POSTS_PER_PAGE'], error_out=False)
        next_url = url_for('messages', page=messages.next_num) if messages.has_next else None
        prev_url = url_for('messages', page=messages.prev_num) if messages.has_prev else None
        return render_template('messages.html', messages=messages.items,
                               next_url=next_url, prev_url=prev_url)

    @app.route('/notifications')
    def notifications():
        if 'user' not in session:
            return redirect(url_for('login'))
        current_user = get_current_user()
        since = request.args.get('since', 0.0, type=float)
        query = current_user.notifications.select().where(
            Notification.timestamp > since).order_by(Notification.timestamp.asc())
        notifications = db.session.scalars(query)
        return jsonify([{
            'name': n.name,
            'data': n.get_data(),
            'timestamp': n.timestamp
        } for n in notifications])

    @app.route('/send_message/<recipient>', methods=['GET', 'POST'])
    def send_message(recipient):
        if 'user' not in session:
            return redirect(url_for('login'))
        current_user = get_current_user()
        recipient_user = db.session.scalar(sa.select(User).where(User.username == recipient))
        if recipient_user is None:
            flash(_('User %(username)s not found.', username=recipient))
            return redirect(url_for('index'))
        form = MessageForm()
        if form.validate_on_submit():
            msg = Message(author=current_user, recipient=recipient_user, body=form.message.data)
            db.session.add(msg)
            db.session.commit()
            flash(_('Your message has been sent.'))
            return redirect(url_for('user', username=recipient))
        return render_template('send_message.html', title=_('Send Message'), form=form, recipient=recipient)