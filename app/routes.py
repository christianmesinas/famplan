import os
import secrets
import uuid
from zoneinfo import ZoneInfo

from flask import session, render_template, flash, redirect, url_for, request, jsonify, abort, send_from_directory, \
    current_app, Response
from urllib.parse import urlparse, urljoin
import sqlalchemy as sa
from werkzeug.utils import secure_filename

from app import db, oauth
from app.forms import (
    PostForm, EditProfileForm, EmptyForm, MessageForm,
    FamilyForm, InviteForm, JoinForm, EditFamilyForm
)
from app.models import (
    User, Post, Message, Notification,
    Family, Membership, FamilyInvite
)
import logging
from datetime import datetime, timezone, timedelta
from requests.exceptions import HTTPError

from flask_mail import Message as MailMessage
from app import mail

# Configureer logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_current_user():
    """
    Haal de momenteel ingelogde gebruiker op via Auth0-sub uit de sessie.
    Retourneert None als er geen geldige sessie is.
    """
    if 'user' not in session:
        logger.debug("No user in session")
        return None

    user_info = session['user'].get('userinfo', {})
    logger.debug(f"User info: {user_info}")

    sub = user_info.get('sub')
    if not sub:
        logger.error("No sub found in user info, cannot identify user")
        return None

    user = db.session.scalar(sa.select(User).where(User.sub == sub))
    if not user:
        logger.debug("User not found in database, should have been created in callback")
        return None

    logger.debug(f"Found user with sub: {sub}")
    return user

def register_routes(app):
    """
    Registreer alle routes op het Flask-app object.
    """

    @app.context_processor
    def inject_current_user():
        # Maak get_current_user beschikbaar in alle templates
        return dict(get_current_user=get_current_user)

    @app.before_request
    def before_request():
        # Update last_seen voor ingelogde gebruiker
        user = get_current_user()
        if user:
            user.last_seen = datetime.now(timezone.utc)
            db.session.commit()

    # ------------------------------------------------------------------
    # 1) CREATE A FAMILY
    # ------------------------------------------------------------------
    @app.route('/family/create', methods=['GET', 'POST'])
    def create_family():
        current_user = get_current_user()
        if not current_user:
            flash('Please log in to create a family.', 'warning')
            return redirect(url_for('login'))

        # Geeft families waar de gebruiker in zit
        families = (
            db.session.query(Family)
            .join(Membership)
            .filter(Membership.user_id == current_user.id)
            .all()
        )

        form = FamilyForm()
        if form.validate_on_submit():
            # Maak nieuwe Family en voeg creator toe als lid
            fam = Family(name=form.name.data)
            db.session.add(fam)
            db.session.flush()  # verkrijg fam.id zonder commit
            mem = Membership(user_id=current_user.id, family_id=fam.id)
            db.session.add(mem)
            db.session.commit()

            flash(f'Family "{fam.name}" created!', 'success')
            return redirect(url_for('invite_family', family_id=fam.id))

        return render_template('create_family.html', form=form, families=families)

    # ------------------------------------------------------------------
    # 2) GENERATE AN INVITE
    # ------------------------------------------------------------------
    @app.route('/family/<int:family_id>/invite', methods=['GET', 'POST'])
    def invite_family(family_id):
        current_user = get_current_user()
        fam = Family.query.get_or_404(family_id)

        # Alleen bestaande leden mogen uitnodigingen genereren of de naam aanpassen
        if not any(m.user_id == current_user.id for m in fam.memberships):
            abort(403)

        form = InviteForm()
        edit_form = EditFamilyForm()
        if request.method == 'GET':
            edit_form.name.data = fam.name

        # Familie naam aanpassen
        if edit_form.rename.data and edit_form.validate_on_submit():
            fam.name = edit_form.name.data
            db.session.commit()
            flash('Family name updated!', 'success')
            return redirect(url_for('invite_family', family_id=fam.id))

        if form.submit.data and form.validate_on_submit():
            # Maak een nieuwe token met 7 dagen geldigheid
            token   = secrets.token_urlsafe(16)
            expires = datetime.now(timezone.utc) + timedelta(days=7)
            invite  = FamilyInvite(
                family_id     = fam.id,
                token         = token,
                invited_email = form.invited_email.data or None,
                expires_at    = expires
            )
            db.session.add(invite)
            db.session.commit()
            flash('Invite created! Share the link below.', 'info')
            # stuur een email met de token
            if form.invited_email.data:
                join_url = url_for('join_family', token=invite.token, _external=True)
                msg = MailMessage(
                    subject=f"FamPlan: Invite to join “{fam.name}”",
                    recipients=[invite.invited_email],
                    body=render_template(
                        'email/family_invite.txt',
                        family=fam,
                        join_url=join_url,
                        expires_at=invite.expires_at
                    )
                )
                mail.send(msg)
                flash(f'Invite sent to {invite.invited_email}', 'success')

            else:
                flash('Invite created! No email address provided so no message sent.', 'info')

        # Toon de meest recente invite
        latest = (
            FamilyInvite.query
            .filter_by(family_id=fam.id)
            .order_by(FamilyInvite.created_at.desc())
            .first()
        )
        join_url = (
            url_for('join_family', token=latest.token, _external=True)
            if latest else None
        )

        return render_template(
            'invite_family.html',
            family     = fam,
            form       = form,
            edit_form  = edit_form,
            join_url   = join_url,
            expires_at = (latest.expires_at if latest else None)
        )

    # ------------------------------------------------------------------
    # 3) JOIN A FAMILY WITH A TOKEN
    # ------------------------------------------------------------------
    @app.route('/family/join/<token>', methods=['GET', 'POST'])
    def join_family(token):
        # Ensure the user is logged in
        current_user = get_current_user()
        if not current_user:
            # Remember where we were trying to go
            session['after_login'] = request.url
            flash('Please log in to join a family.', 'warning')
            return redirect(url_for('auth_login'))

        # Load the invite by token
        invite = FamilyInvite.query.filter_by(token=token).first()
        if not invite:
            flash('Invalid invite token.', 'danger')
            return redirect(url_for('create_family'))

        # Normalize and check expiration
        now = datetime.now(timezone.utc)
        exp = invite.expires_at
        if exp:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                flash('This invite has expired.', 'warning')
                return redirect(url_for('create_family'))

        # Check if invite was already used
        if invite.accepted:
            flash('This invite was already used.', 'warning')
            return redirect(url_for('create_family'))

        form = JoinForm(token=token)
        if form.validate_on_submit():
            # Prevent the same user joining twice
            already = db.session.scalar(
                sa.select(Membership)
                .where(
                    Membership.user_id == current_user.id,
                    Membership.family_id == invite.family_id
                )
            )
            if already:
                flash("You’re already a member of this family.", "warning")
                return redirect(url_for('invite_family', family_id=invite.family_id))

            # All clear—create the membership
            membership = Membership(
                user_id=current_user.id,
                family_id=invite.family_id
            )
            db.session.add(membership)

            # Mark the invite as used
            invite.accepted = True

            # Commit both in one transaction
            db.session.commit()

            flash(f'You have joined “{invite.family.name}”!', 'success')
            return redirect(url_for('calendar.index'))

        return render_template('join_family.html', form=form, invite=invite)

    # ------------------------------------------------------------------
    # 4) LEAVE A FAMILY GROUP
    # ------------------------------------------------------------------
    @app.route('/family/<int:family_id>/leave', methods=['POST'])
    def leave_family(family_id):
        # Only logged-in users may leave
        current_user = get_current_user()
        if not current_user:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))

        form = EmptyForm()
        if form.validate_on_submit():
            # Find their membership (if any)
            membership = db.session.scalar(
                sa.select(Membership)
                  .where(
                      Membership.user_id   == current_user.id,
                      Membership.family_id == family_id
                  )
            )
            if membership:
                db.session.delete(membership)
                db.session.commit()
                flash('You have left the family.', 'success')
            else:
                flash('You are not a member of that family.', 'warning')

        # Go back to the profile page (or wherever you like)
        return redirect(url_for('user', username=current_user.username))

    # ------------------------------------------------------------------
    # 5) EDIT A POST
    # ------------------------------------------------------------------

    @app.route('/post/<int:post_id>/edit', methods=['POST'])
    def edit_post(post_id):
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Not logged in'}), 403

        post = db.session.get(Post, post_id)
        if post is None or post.author != current_user:
            return jsonify({'error': 'Post not found or unauthorized'}), 404

        data = request.get_json()
        new_body = data.get('body')
        if not new_body:
            return jsonify({'error': 'Empty post'}), 400

        post.body = new_body
        db.session.commit()
        return jsonify({'message': 'Post updated', 'new_body': post.body})

    # ------------------------------------------------------------------
    # 6) DELETE A POST
    # ------------------------------------------------------------------

    @app.route('/post/<int:post_id>/delete', methods=['DELETE'])
    def delete_post(post_id):
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Not logged in'}), 403

        post = db.session.get(Post, post_id)
        if not post or post.author != current_user:
            return jsonify({'error': 'Unauthorized or post not found'}), 404

        db.session.delete(post)
        db.session.commit()
        return jsonify({'message': 'Post deleted'})

    # ------------------------------------------------------------------
    # Auth0 callback
    # ------------------------------------------------------------------
    @app.route('/callback')
    def callback():
        try:
            received_state = request.args.get('state')
            expected_state = session.get('auth0_state')
            if received_state != expected_state:
                logger.error(f"CSRF Warning: State mismatch. Received: {received_state}, Expected: {expected_state}")
                session.clear()
                return redirect(url_for('login', prompt='login'))

            token = oauth.auth0.authorize_access_token()
            session['user'] = token
            user_info = token['userinfo']
            sub = user_info.get('sub')
            if not sub:
                session.clear()
                return redirect(url_for('login', prompt='login'))

            email = user_info.get('email') or f"{sub.replace('|','_')}@noemail.example.com"

            user = db.session.scalar(sa.select(User).where(User.sub == sub))
            if not user:
                # email-conflictcontrole
                existing = db.session.scalar(sa.select(User).where(User.email == email))
                if existing:
                    session.clear()
                    flash('This email address is already in use by another account.', 'danger')
                    logout_url = (
                        f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                        f"federated&returnTo={url_for('login', _external=True, prompt='login')}"
                        f"&client_id={app.config['AUTH0_CLIENT_ID']}"
                    )
                    return redirect(logout_url)
                user = User(username=user_info.get('nickname','user'), email=email, sub=sub)
                db.session.add(user)
                db.session.commit()
            else:
                # update email indien veranderd
                if email and user.email != email:
                    existing = db.session.scalar(sa.select(User).where(User.email == email))
                    if existing and existing.sub != sub:
                        session.clear()
                        flash('This email address is already in use by another account.', 'danger')
                        logout_url = (
                            f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                            f"federated&returnTo={url_for('login', _external=True, prompt='login')}"
                            f"&client_id={app.config['AUTH0_CLIENT_ID']}"
                        )
                        return redirect(logout_url)
                    user.email = email
                    db.session.commit()

            # After successful login and user creation/update:
            session.pop('auth0_state', None)

            # Pull and clear the “after_login” URL
            next_url = session.pop('after_login', None)

            # Only allow safe redirects to the same host
            def is_safe_url(target):
                host_url = urlparse(request.host_url)
                target_url = urlparse(urljoin(request.host_url, target))
                return (
                        target_url.scheme in ('http', 'https') and
                        host_url.netloc == target_url.netloc
                )

            if next_url and is_safe_url(next_url):
                return redirect(next_url)

            return redirect(url_for('index'))


        except HTTPError as e:
            session.clear()
            logout_url = (
                f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                f"federated&returnTo={url_for('login', _external=True, prompt='login')}"
                f"&client_id={app.config['AUTH0_CLIENT_ID']}"
            )
            return redirect(logout_url)
        except Exception:
            session.clear()
            logout_url = (
                f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?"
                f"federated&returnTo={url_for('login', _external=True, prompt='login')}"
                f"&client_id={app.config['AUTH0_CLIENT_ID']}"
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
        return jsonify({'message': 'User created'}), 201


    @app.route('/', methods=['GET', 'POST'])
    @app.route('/index', methods=['GET', 'POST'])
    def index():
        # ——————————————————————————————————————————————————————————
        # 1) Authentication guard
        # ——————————————————————————————————————————————————————————
        if 'user' not in session or get_current_user() is None:
            session.clear()
            return render_template('landings.html')
        user = get_current_user()

        # ——————————————————————————————————————————————————————————
        # 2) Build conversations overview
        #    One entry per Family the user belongs to, plus its last Post
        # ——————————————————————————————————————————————————————————
        conversations = []
        for fam in user.families:
            last_post = db.session.scalar(
                sa.select(Post)
                .where(Post.family_id == fam.id)
                .order_by(Post.timestamp.desc())
                .limit(1)
            )
            conversations.append({
                'family': fam,
                'last_post': last_post
            })

        # ——————————————————————————————————————————————————————————
        # 3) If no family_id → show conversations list
        # ——————————————————————————————————————————————————————————
        family_id = request.args.get('family_id', type=int)
        if not family_id:
            return render_template('conversations.html',
                                   conversations=conversations)

        # ——————————————————————————————————————————————————————————
        # 4) Otherwise: Chat mode for a specific family
        #    Verify the family exists and the user is a member
        # ——————————————————————————————————————————————————————————
        current_family = db.session.get(Family, family_id)
        if not current_family:
            abort(404)
        # ensure membership
        if not any(m.family_id == family_id for m in user.memberships):
            abort(403)

        # ——————————————————————————————————————————————————————————
        # 5) PostForm handling
        # ——————————————————————————————————————————————————————————
        form = PostForm()
        form.family.choices = [(-1, 'Only Me')] + [
            (f.id, f.name) for f in user.families
        ]
        # ⬇️ Force the family field to the “current” chat
        form.family.data = current_family.id

        if form.validate_on_submit():
            selected = form.family.data
            fam_id = None if selected == -1 else selected
            p = Post(
                body=form.post.data,
                author=user,
                family_id=fam_id
            )
            db.session.add(p)
            db.session.commit()
            # after posting, stay in the same chat
            return redirect(url_for('index', family_id=family_id))

        # ——————————————————————————————————————————————————————————
        # 6) Paginate this family’s posts
        # ——————————————————————————————————————————————————————————
        page = request.args.get('page', 1, type=int)
        posts = db.paginate(
            Post.query.filter_by(family_id=family_id),
            page=page,
            per_page=app.config['POSTS_PER_PAGE'],
            error_out=False
        )

        # ——————————————————————————————————————————————————————————
        # 7) Render the chat template
        # ——————————————————————————————————————————————————————————

        local_tz = ZoneInfo('Europe/Amsterdam')
        for post in posts.items:
            # attach a new attribute for the template
            post.local_timestamp = post.timestamp.astimezone(local_tz)

        return render_template(
            'chat.html',
            conversations=conversations,
            current_family=current_family,
            form=form,
            posts=posts.items,
            next_url=url_for('index', family_id=family_id, page=posts.next_num)
            if posts.has_next else None,
            prev_url=url_for('index', family_id=family_id, page=posts.prev_num)
            if posts.has_prev else None
        )

    @app.route('/user/<username>')
    def user(username):
        if 'user' not in session:
            return redirect(url_for('login'))
        user = db.first_or_404(sa.select(User).where(User.username == username))
        page = request.args.get('page', 1, type=int)
        query = user.posts.select().order_by(Post.timestamp.desc())
        posts = db.paginate(
            query, page=page,
            per_page=app.config['POSTS_PER_PAGE'], error_out=False
        )
        next_url = url_for('user', username=user.username, page=posts.next_num) \
            if posts.has_next else None
        prev_url = url_for('user', username=user.username, page=posts.prev_num) \
            if posts.has_prev else None
        form = EmptyForm()
        return render_template(
            'user.html', user=user, posts=posts.items,
            next_url=next_url, prev_url=prev_url, form=form
        )

    @app.route('/edit_profile', methods=['GET', 'POST'])
    def edit_profile():
        if 'user' not in session:
            return redirect(url_for('login'))

        user = get_current_user()
        form = EditProfileForm(user.username)

        if form.validate_on_submit():
            user.username = form.username.data
            user.about_me = form.about_me.data

            # Verwerk de profielfoto als die is geüpload
            if form.profile_picture.data:
                file = form.profile_picture.data
                # Lees de binaire data
                image_data = file.read()
                # Sla de MIME-type op
                mime_type = file.mimetype
                # Sla de data op in de database
                user.profile_image_data = image_data
                user.profile_image_mime = mime_type


            db.session.commit()
            flash('Your changes have been saved.')
            return redirect(url_for('edit_profile'))

        elif request.method == 'GET':
            form.username.data = user.username
            form.about_me.data = user.about_me

        return render_template(
            'edit_profile.html', title='Edit Profile', form=form
        )

    @app.route('/profile_image/<int:user_id>')
    def get_profile_image(user_id):
        user = db.session.get(User, user_id)
        if user and user.profile_image_data:
            return Response(
                user.profile_image_data,
                mimetype=user.profile_image_mime
            )
        # Fallback naar een standaardafbeelding of Gravatar
        return redirect(user.avatar(128))

    @app.route('/follow/<username>', methods=['POST'])
    def follow(username):
        if 'user' not in session:
            return redirect(url_for('login'))
        form = EmptyForm()
        if form.validate_on_submit():
            user_to_follow = db.session.scalar(sa.select(User).where(User.username == username))
            current_user = get_current_user()
            if user_to_follow is None:
                flash(f'User {username} not found.')
                return redirect(url_for('index'))
            if user_to_follow == current_user:
                flash('You cannot follow yourself!')
                return redirect(url_for('user', username=username))
            current_user.follow(user_to_follow)
            db.session.commit()
            flash(f'You are following {username}!')
            return redirect(url_for('user', username=username))
        return redirect(url_for('index'))

    @app.route('/unfollow/<username>', methods=['POST'])
    def unfollow(username):
        if 'user' not in session:
            return redirect(url_for('login'))
        form = EmptyForm()
        if form.validate_on_submit():
            user_to_unfollow = db.session.scalar(sa.select(User).where(User.username == username))
            current_user = get_current_user()
            if user_to_unfollow is None:
                flash(f'User {username} not found.')
                return redirect(url_for('index'))
            if user_to_unfollow == current_user:
                flash('You cannot unfollow yourself!')
                return redirect(url_for('user', username=username))
            current_user.unfollow(user_to_unfollow)
            db.session.commit()
            flash(f'You are no longer following {username}.')
            return redirect(url_for('user', username=username))
        return redirect(url_for('index'))

    @app.route('/notifications')
    def notifications():
        if 'user' not in session:
            return redirect(url_for('login'))
        current_user = get_current_user()
        since = request.args.get('since', 0.0, type=float)
        query = current_user.notifications.select().where(
            Notification.timestamp > since
        ).order_by(Notification.timestamp.asc())
        notifications = db.session.scalars(query)
        return jsonify([
            {'name': n.name, 'data': n.get_data(), 'timestamp': n.timestamp}
            for n in notifications
        ])

    @app.route('/send_message/<recipient>', methods=['GET', 'POST'])
    def send_message(recipient):
        if 'user' not in session:
            return redirect(url_for('login'))
        current_user = get_current_user()
        recipient_user = db.session.scalar(sa.select(User).where(User.username == recipient))
        if recipient_user is None:
            flash(f'User {recipient} not found.')
            return redirect(url_for('index'))
        form = MessageForm()
        if form.validate_on_submit():
            msg = Message(
                author=current_user,
                recipient=recipient_user,
                body=form.message.data
            )
            db.session.add(msg)
            db.session.commit()
            flash('Your message has been sent.')
            return redirect(url_for('user', username=recipient))
        return render_template(
            'send_message.html',
            title='Send Message',
            form=form,
            recipient=recipient
        )

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(
            os.path.join(app.root_path, 'static'),
            'favicon.ico',
            mimetype='image/vnd.microsoft.icon'
        )

    @app.route('/auth/login')
    def auth_login():
        if 'user' in session:
            return redirect(url_for('index'))
        session['auth0_state'] = secrets.token_urlsafe(32)
        redirect_uri = url_for('callback', _external=True)
        return oauth.auth0.authorize_redirect(
            redirect_uri=redirect_uri,
            state=session['auth0_state'],
            prompt='select_account'
        )

    @app.route('/auth/register')
    def auth_register():
        if 'user' in session:
            return redirect(url_for('index'))
        session['auth0_state'] = secrets.token_urlsafe(32)
        redirect_uri = url_for('callback', _external=True)
        return oauth.auth0.authorize_redirect(
            redirect_uri=redirect_uri,
            state=session['auth0_state'],
            prompt='select_account',
            screen_hint='signup'
        )

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        return render_template('500.html'), 500
