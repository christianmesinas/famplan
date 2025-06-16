from flask import Blueprint, redirect, url_for, session, request, render_template, flash, current_app, jsonify
from app import db, oauth
from app.models import User, CalendarCredentials, Membership, Family
from app.calendar_service import GoogleCalendarService
import sqlalchemy as sa
from datetime import datetime, timedelta
import json
from functools import wraps
import logging

logger = logging

# Maak een Blueprint voor kalendergerelateerde routes
bp = Blueprint('calendar', __name__)

# Helperfuncties voor credentialbeheer
def get_calendar_credentials(user_id):
    # Zoek de referenties in de database op basis van de gebruikers-ID
    return db.session.scalar(
        sa.select(CalendarCredentials).where(CalendarCredentials.user_id == user_id)
    )

# Helperfunctie om referenties om te zetten naar een dictionary
def credentials_to_dict(creds):
    logger = logging.getLogger(__name__)
    logger.debug("Omzetten van referenties naar dictionary")
    if not creds:
        logger.warning("Geen referenties gevonden")
        return None
    # Maak een dictionary met de referentiegegevens
    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': json.loads(creds.scopes),
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }

# Decorators
def login_required(f):
    @wraps(f)
    # Behoud de metadata van de originele functie
    def decorated_function(*args, **kwargs):
        logger = logging.getLogger(__name__)
        if 'user' not in session:
            logger.warning("Geen gebruiker in sessie, redirect naar login")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def calendar_auth_required(f):
    @wraps(f)
    # Behoud de metadata van de originele functie
    def decorated_function(*args, **kwargs):
        logger = logging.getLogger(__name__)
        current_user = get_current_user()
        if not current_user:
            logger.warning("Geen huidige gebruiker, redirect naar login")
            return redirect(url_for('login'))

        creds = get_calendar_credentials(current_user.id)
        if not creds:
            logger.warning("Geen kalenderreferenties, redirect naar autorisatie")
            return redirect(url_for('calendar.authorize'))

        return f(*args, **kwargs)
    return decorated_function

# Hulpfunction om de huidige gebruiker op te halen
def get_current_user():
    logger = logging.getLogger(__name__)
    user_info = session.get('user', {}).get('userinfo', {})
    current_app.logger.debug(f"User info: {user_info}")
    if not user_info:
        return None
    sub = user_info.get('sub')
    if not sub:
        current_app.logger.error("No sub found in user info, cannot retrieve user")
        return None
    user = db.session.scalar(sa.select(User).where(User.sub == sub))
    if user:
        current_app.logger.debug(f"Found user with sub: {sub}")
    else:
        current_app.logger.debug("User not found in database, should have been created in callback")
    return user

# Routes
@bp.route('/calendar')
@login_required  # Vereist dat de gebruiker is ingelogd
def index():
    #Als de gebruiker nog geen Google Calendar-referenties heeft, wordt een connect-pagina getoond.
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    if not creds:
        logger.info("Geen kalenderreferenties, tonen van connect-pagina")
        flash('A Google account is required to use the calendar functionality. Please connect your Google Calendar.', 'info')
        return render_template('calendar/connect.html')
    logger.debug("Kalenderreferenties gevonden, tonen van kalenderpagina")
    return render_template('calendar/index.html')

@bp.route('/calendar/authorize')
@login_required  # Vereist dat de gebruiker is ingelogd
def authorize():
    flow = GoogleCalendarService.create_flow()
    # Maak een OAuth2-flow aan
    # Genereer een autorisatie-URL met specifieke parameters
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes=False
    )
    session['state'] = state  # Sla de 'state'-parameter op in de sessie om CSRF te voorkomen
    return redirect(authorization_url)

@bp.route('/create_event', methods=['POST'])
@calendar_auth_required
def create_event():
    logger = logging.getLogger(__name__)
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    creds_dict = credentials_to_dict(creds)
    if not creds_dict:
        logger.warning("Geen referenties voor huidige gebruiker")
        return jsonify({'error': 'Google Calendar niet geautoriseerd'}), 401

    data = request.get_json()
    if not data or not all(k in data for k in ['title', 'start', 'end']):
        logger.warning("Ongeldige evenementgegevens ontvangen")
        return jsonify({'error': 'Ongeldige gegevens'}), 400

    try:
        service = GoogleCalendarService.get_calendar_service(creds_dict)
        event = GoogleCalendarService.create_event(
            service,
            calendar_id='primary',
            summary=data['title'],
            start_datetime=data['start'],
            end_datetime=data['end'],
            description=data.get('description', ''),
            location=data.get('location', ''),
            attendees=data.get('attendees', [])  # Inclusief familieleden en extra genodigden
        )
        logger.info(f"Evenement aangemaakt met ID: {event.get('id')}")
        return jsonify({
            'id': event['id'],
            'title': event['summary'],
            'start': event['start'].get('dateTime', event['start'].get('date')),
            'end': event['end'].get('dateTime', event['end'].get('date')),
            'description': event.get('description', ''),
            'location': event.get('location', ''),
            'attendees': [attendee['email'] for attendee in event.get('attendees', [])]
        }), 201
    except Exception as e:
        logger.error(f"Fout bij aanmaken evenement: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/family_members')
@login_required
def family_members():
    from app import db
    logger = logging.getLogger(__name__)
    current_user = get_current_user()

    try:
        # Haal alle familieleden op uit gedeelde families
        members = db.session.scalars(
            sa.select(User)
            .join(Membership)
            .where(
                Membership.family_id.in_(
                    sa.select(Membership.family_id).where(Membership.user_id == current_user.id)
                ),
                Membership.user_id != current_user.id  # Exclusief huidige gebruiker
            )
        ).all()

        # Maak een lijst van familieleden met gebruikersnaam en e-mail
        family_members = [
            {'username': member.username, 'email': member.email}
            for member in members
        ]
        logger.debug(f"Ophalen familieleden: {len(family_members)} leden gevonden")
        return jsonify(family_members)
    except Exception as e:
        logger.error(f"Fout bij ophalen familieleden: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/oauth2callback')
def google_oauth2callback():
    #Haalt de referenties op, slaat ze op in de database, en stuurt de gebruiker terug naar de kalenderpagina.
    if 'state' not in session:
        return redirect(url_for('calendar.index'))

    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))

    flow = GoogleCalendarService.create_flow()
    # Haal de referenties op van Google na autorisatie
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    # Maak een dictionary met de referentiegegevens
    creds_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': json.dumps(credentials.scopes),
        'expiry': credentials.expiry
    }

    creds = get_calendar_credentials(current_user.id)
    if creds:
        for key, value in creds_data.items():
            setattr(creds, key, value)
    else:
        creds = CalendarCredentials(user_id=current_user.id, **creds_data)
        db.session.add(creds)

    db.session.commit()
    flash('Google Calendar connected successfully!')
    return redirect(url_for('calendar.index'))

@bp.route('/calendar/events')
@calendar_auth_required
def events():
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    creds_dict = credentials_to_dict(creds)
    if not creds_dict:
        return redirect(url_for('calendar.authorize'))

    service = GoogleCalendarService.get_calendar_service(creds_dict)
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    family_id = request.args.get('family_id')  # Optionele parameter voor specifieke familie

    if start_date:
        start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        start_date = datetime.utcnow()
    if end_date:
        end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    else:
        end_date = start_date + timedelta(days=30)

    # Haal evenementen van de huidige gebruiker op
    user_events = GoogleCalendarService.get_events(
        service,
        time_min=start_date,
        time_max=end_date,
        max_results=100
    )

    # Haal familieleden op uit de geselecteerde familie(s)
    family_events = []
    query = sa.select(Family).join(Membership).where(Membership.user_id == current_user.id)
    if family_id:
        query = query.where(Family.id == int(family_id))

    families = db.session.scalars(query).all()

    for family in families:
        # Haal alle leden van de familie op (exclusief de huidige gebruiker)
        members = db.session.scalars(
            sa.select(User)
            .join(Membership)
            .where(Membership.family_id == family.id, Membership.user_id != current_user.id)
        ).all()

        for member in members:
            member_creds = db.session.scalar(
                sa.select(CalendarCredentials).where(CalendarCredentials.user_id == member.id)
            )
            if member_creds:
                member_creds_dict = credentials_to_dict(member_creds)
                if member_creds_dict:
                    try:
                        member_service = GoogleCalendarService.get_calendar_service(member_creds_dict)
                        events = GoogleCalendarService.get_events(
                            member_service,
                            time_min=start_date,
                            time_max=end_date,
                            max_results=100
                        )
                        # Voeg metadata toe om de gebruiker en familie te identificeren
                        for event in events:
                            event['creator_id'] = member.id
                            event['creator_username'] = member.username
                            event['family_member_name'] = member.username
                            event['family_name'] = family.name
                            family_events.append(event)
                    except Exception as e:
                        current_app.logger.error(
                            f"Fout bij ophalen evenementen voor familielid {member.username} in familie {family.name}: {e}")
                        continue

    # Combineer en formatteer evenementen
    all_events = user_events + family_events
    formatted_events = []
    for event in all_events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        formatted_events.append({
            # Standard calendar fields
            'id': event['id'],
            'title': event['summary'],
            'start': start,
            'end': end,
            'description': event.get('description', ''),
            'location': event.get('location', ''),

            # Custom props for your JS hooks
            'extendedProps': {
                'userId':            event.get('creator_id', current_user.id),
                'userName':          event.get('creator_username', current_user.username),
                'familyMemberName':  event.get('family_member_name'),
                'familyName':        event.get('family_name')
            }
        })

    return jsonify(formatted_events)


@bp.route('/calendar/event/<event_id>', methods=['PUT'])
@calendar_auth_required  # Vereist dat de gebruiker is ingelogd en referenties heeft
def update_event(event_id):
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    creds_dict = credentials_to_dict(creds)

    data = request.json
    service = GoogleCalendarService.get_calendar_service(creds_dict)

    event = service.events().get(calendarId='primary', eventId=event_id).execute()

    # Update velden
    if 'title' in data:
        event['summary'] = data['title']
    if 'description' in data:
        event['description'] = data['description']
    if 'location' in data:
        event['location'] = data['location']
    if 'start' in data:
        start_datetime = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        event['start'] = {
            'dateTime': start_datetime.isoformat(),
            'timeZone': 'UTC'
        }
    if 'end' in data:
        end_datetime = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
        event['end'] = {
            'dateTime': end_datetime.isoformat(),
            'timeZone': 'UTC'
        }
    if 'attendees' in data:
        event['attendees'] = [{'email': email} for email in data['attendees']]

    # Update event
    updated_event = GoogleCalendarService.update_event(
        service,
        'primary',
        event_id,
        event
    )

    return jsonify({
        'id': updated_event['id'],
        'title': updated_event['summary'],
        'start': updated_event['start']['dateTime'],
        'end': updated_event['end']['dateTime']
    })

@bp.route('/calendar/event/<event_id>', methods=['DELETE'])
@calendar_auth_required
def delete_event(event_id):
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    creds_dict = credentials_to_dict(creds)
    service = GoogleCalendarService.get_calendar_service(creds_dict)
    GoogleCalendarService.delete_event(service, 'primary', event_id)

    return jsonify({'success': True})