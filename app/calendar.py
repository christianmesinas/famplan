from flask import Blueprint, redirect, url_for, session, request, render_template, flash, current_app, jsonify
from app import db, oauth
from app.models import User, CalendarCredentials
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
        include_granted_scopes='true'
    )
    session['state'] = state  # Sla de 'state'-parameter op in de sessie om CSRF te voorkomen
    return redirect(authorization_url)

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
@calendar_auth_required  # Vereist dat de gebruiker is ingelogd en referenties heeft
def events():
    #Haal een lijst van evenementen op uit de Google Calendar van de gebruiker.
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    creds_dict = credentials_to_dict(creds)
    if not creds_dict:
        return redirect(url_for('calendar.authorize'))

    service = GoogleCalendarService.get_calendar_service(creds_dict)
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    # Stel de startdatum in (standaard nu)
    if start_date:
        start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        start_date = datetime.utcnow()
    # Stel de einddatum in (standaard 30 dagen vanaf start)
    if end_date:
        end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    else:
        end_date = start_date + timedelta(days=30)
    # Haal de evenementen op uit de Google Calendar
    events = GoogleCalendarService.get_events(
        service,
        time_min=start_date,
        time_max=end_date,
        max_results=100
    )
    # Formatteer de evenementen voor de JSON-respons
    formatted_events = []
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        formatted_events.append({
            'id': event['id'],
            'title': event['summary'],
            'start': start,
            'end': end,
            'description': event.get('description', ''),
            'location': event.get('location', '')
        })

    return jsonify(formatted_events)

@bp.route('/calendar/event', methods=['POST'])
@calendar_auth_required  # Vereist dat de gebruiker is ingelogd en referenties heeft
def create_event():
    #Maak een nieuw evenement aan in de Google Calendar van de gebruiker.
    current_user = get_current_user()
    creds = get_calendar_credentials(current_user.id)
    creds_dict = credentials_to_dict(creds)

    data = request.json
    service = GoogleCalendarService.get_calendar_service(creds_dict)

    # Datums omzetten
    start_datetime = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
    end_datetime = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))

    # Maak een nieuw evenement aan in de Google Calendar
    event = GoogleCalendarService.create_event(
        service,
        summary=data['title'],
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        description=data.get('description', ''),
        location=data.get('location', ''),
        attendees=data.get('attendees', [])
    )

    # Retourneer het aangemaakte evenement in JSON-formaat
    return jsonify({
        'id': event['id'],
        'title': event['summary'],
        'start': event['start']['dateTime'],
        'end': event['end']['dateTime']
    })

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