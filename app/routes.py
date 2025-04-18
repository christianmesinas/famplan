from flask import session, render_template, flash, redirect, url_for, request, g, current_app, jsonify
from flask_babel import _, get_locale
import sqlalchemy as sa
from app import db, oauth
from app.forms import PostForm, EditProfileForm, EmptyForm, MessageForm
from app.models import User, Post, Message, Notification, CalendarCredentials
from app.calendar_service import GoogleCalendarService
from langdetect import detect, LangDetectException
from datetime import datetime, timezone
import logging
import secrets
from requests.exceptions import HTTPError



logging.basicConfig(level=logging.DEBUG)


def get_current_user():
    if 'user' not in session:
        current_app.logger.debug("No user in session")
        return None

    user_info = session['user'].get('userinfo', {})
    current_app.logger.debug(f"User info: {user_info}")

    # sub als unieke identifier
    sub = user_info.get('sub')
    if not sub:
        current_app.logger.error("No sub found in user info, cannot identify user")
        return None

    user = db.session.scalar(sa.select(User).where(User.sub == sub))
    if not user:
        current_app.logger.debug("User not found in database, should have been created in callback")
        return None

    current_app.logger.debug(f"Found user with sub: {sub}")
    return user

def register_routes(app):
    @app.context_processor
    def inject_current_user():
        return dict(get_current_user=get_current_user)

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
        session['auth0_state'] = secrets.token_urlsafe(32)
        redirect_uri = url_for('callback', _external=True)
        current_app.logger.debug(f"Generated redirect_uri: {redirect_uri}")
        prompt = request.args.get('prompt', 'select_account')
        return oauth.auth0.authorize_redirect(redirect_uri=redirect_uri, state=session['auth0_state'], prompt=prompt)
    @app.route('/callback')

    def callback():
        try:
            received_state = request.args.get('state')
            expected_state = session.get('auth0_state')
            if received_state != expected_state:
                current_app.logger.error(
                    f"CSRF Warning: State mismatch. Received: {received_state}, Expected: {expected_state}")
                session.clear()
                return redirect(url_for('login', prompt='login'))

            token = oauth.auth0.authorize_access_token()
            app.logger.debug(f"Token received: {token}")
            session['user'] = token
            user_info = token['userinfo']
            app.logger.debug(f"User info: {user_info}")
            sub = user_info.get('sub')
            if not sub:
                app.logger.error("No sub found in user info, cannot create user")
                session.clear()
                return redirect(url_for('login', prompt='login'))

            email = user_info.get('email')
            if not email:
                email = f"{sub.replace('|', '_')}@noemail.example.com"

            # Controleer eerst of een gebruiker bestaat op basis van sub
            user = db.session.scalar(sa.select(User).where(User.sub == sub))
            if not user:
                # Controleer of het e-mailadres al in gebruik is door een andere gebruiker
                existing_user_with_email = db.session.scalar(sa.select(User).where(User.email == email))
                if existing_user_with_email:
                    app.logger.error(
                        f"Email {email} already in use by another user with sub: {existing_user_with_email.sub}")
                    session.clear()
                    flash(
                        _('This email address is already in use by another account. Please log in with a different account.'),
                        'danger')
                    logout_url = (
                        f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                        f"federated&returnTo={url_for('login', _external=True, prompt='login')}&client_id={app.config['AUTH0_CLIENT_ID']}"
                    )
                    return redirect(logout_url)

                # Geen conflict, maak een nieuwe gebruiker aan
                user = User(
                    username=user_info.get('nickname', 'default_user'),
                    email=email,
                    sub=sub
                )
                db.session.add(user)
                db.session.commit()
                app.logger.debug(f"New user added with sub: {sub}")
            else:
                # Update het e-mailadres van de bestaande gebruiker, als het veranderd is
                if email and user.email != email:
                    # Controleer of het nieuwe e-mailadres al in gebruik is
                    existing_user_with_email = db.session.scalar(sa.select(User).where(User.email == email))
                    if existing_user_with_email and existing_user_with_email.sub != sub:
                        app.logger.error(
                            f"Email {email} already in use by another user with sub: {existing_user_with_email.sub}")
                        session.clear()
                        flash(
                            _('This email address is already in use by another account. Please log in with a different account.'),
                            'danger')
                        logout_url = (
                            f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                            f"federated&returnTo={url_for('login', _external=True, prompt='login')}&client_id={app.config['AUTH0_CLIENT_ID']}"
                        )
                        return redirect(logout_url)
                    user.email = email
                    db.session.commit()
                app.logger.debug(f"Existing user found with sub: {sub}")
            app.logger.debug(f"Session after callback: {session}")
            session.pop('auth0_state', None)
            return redirect(url_for('index'))
        except HTTPError as e:
            error_description = e.response.json().get('error_description', 'Unknown error') if e.response else str(e)
            app.logger.error(f"Error in callback: {str(e)}")
            session.clear()
            logout_url = (
                f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                f"federated&returnTo={url_for('login', _external=True, prompt='login')}&client_id={app.config['AUTH0_CLIENT_ID']}"
            )
            return redirect(logout_url)
        except Exception as e:
            app.logger.error(f"Unexpected error in callback: {str(e)}")
            session.clear()
            logout_url = (
                f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                f"federated&returnTo={url_for('login', _external=True, prompt='login')}&client_id={app.config['AUTH0_CLIENT_ID']}"
            )
            return redirect(logout_url)

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
                sub=f"manual|{data['email']}"
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


    @app.route('/favicon.ico')
    def favicon():
        return '', 204