from flask import Blueprint, redirect, url_for, session, request, render_template, flash, current_app, jsonify
from app import db, oauth
from app.models import User, CalendarCredentials
from app.calendar_service import GoogleCalendarService
import sqlalchemy as sa
from datetime import datetime, timedelta
import json
from functools import wraps
import logging

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
    logger.debug(f"Gebruikersinfo: {user_info}")
    if not user_info:
        logger.warning("Geen gebruikersinfo in sessie")
        return None
    sub = user_info.get('sub')
    if not sub:
        logger.error("Geen 'sub' gevonden in gebruikersinfo, kan gebruiker niet ophalen")
        return None
    user = db.session.scalar(sa.select(User).where(User.sub == sub))
    if user:
        logger.debug(f"Gebruiker gevonden met sub: {sub}")
    else:
        logger.debug("Gebruiker niet gevonden in database, zou aangemaakt moeten zijn in callback")
    return user

# Routes
@bp.route('/calendar')
@login_required  # Vereist dat de gebruiker is ingelogd
def index():
    # Als de gebruiker nog geen Google Calendar-referenties heeft, wordt een connect-pagina getoond
    logger = logging.getLogger(__name__)
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
    logger = logging.getLogger(__name__)
    logger.debug("Starten van Google OAuth2-autorisatie")
    try:
        # Maak een OAuth2-flow aan
        flow = GoogleCalendarService.create_flow()
        # Genereer een autorisatie-URL met specifieke parameters
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent',
            include_granted_scopes='true'
        )
        session['state'] = state  # Sla de 'state'-parameter op in de sessie om CSRF te voorkomen
        logger.debug(f"Redirect naar autorisatie-URL: {authorization_url}")
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"Fout bij het starten van OAuth2-flow: {e}")
        flash('Fout bij het starten van Google Calendar-autorisatie.', 'error')
        return redirect(url_for('calendar.index'))

@bp.route('/oauth2callback')
def google_oauth2callback():
    # Haalt de referenties op, slaat ze op in de database, en stuurt de gebruiker terug naar de kalenderpagina
    logger = logging.getLogger(__name__)
    logger.debug("Afhandelen van Google OAuth2-callback")
    try:
        if 'state' not in session:
            logger.error("OAuth2-state ontbreekt in sessie")
            flash('Ongeldige autorisatiepoging.', 'error')
            return redirect(url_for('calendar.index'))

        current_user = get_current_user()
        if not current_user:
            logger.warning("Geen huidige gebruiker, redirect naar login")
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
            logger.debug("Bestaande referenties bijwerken")
            for key, value in creds_data.items():
                setattr(creds, key, value)
        else:
            logger.debug("Nieuwe referenties aanmaken")
            creds = CalendarCredentials(user_id=current_user.id, **creds_data)
            db.session.add(creds)

        db.session.commit()
        logger.info(f"Kalenderreferenties opgeslagen voor gebruiker ID: {current_user.id}")
        flash('Google Calendar succesvol verbonden!')
        return redirect(url_for('calendar.index'))
    except Exception as e:
        logger.error(f"Fout bij het afhandelen van OAuth2-callback: {e}")
        flash('Fout bij het verbinden van Google Calendar.', 'error')
        return redirect(url_for('calendar.index'))

@bp.route('/calendar/events')
@calendar_auth_required  # Vereist dat de gebruiker is ingelogd en referenties heeft
def events():
    # Haal een lijst van evenementen op uit de Google Calendar van de gebruiker
    logger = logging.getLogger(__name__)
    logger.debug("Ophalen van kalender-evenementen")
    try:
        current_user = get_current_user()
        creds = get_calendar_credentials(current_user.id)
        creds_dict = credentials_to_dict(creds)
        if not creds_dict:
            logger.error("Geen referenties beschikbaar, redirect naar autorisatie")
            return redirect(url_for('calendar.authorize'))

        service = GoogleCalendarService.get_calendar_service(creds_dict)
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        logger.debug(f"Startdatum: {start_date}, Einddatum: {end_date}")

        # Geef start_date en end_date direct door als strings
        events = GoogleCalendarService.get_events(
            service,
            time_min=start_date,
            time_max=end_date,
            max_results=100
        )
        logger.debug(f"{len(events)} evenementen opgehaald")

        # Formatteer de evenementen voor de JSON-respons
        formatted_events = []
        for event in events:
            try:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                if not start or not end:
                    logger.warning(f"Overslaan van evenement {event.get('id', 'onbekend')} met ontbrekende start/eind")
                    continue
                formatted_events.append({
                    'id': event.get('id', ''),
                    'title': event.get('summary', ''),
                    'start': start,
                    'end': end,
                    'description': event.get('description', ''),
                    'location': event.get('location', '')
                })
            except Exception as e:
                logger.error(f"Fout bij het formatteren van evenement {event.get('id', 'onbekend')}: {e}")
                continue

        logger.info(f"{len(formatted_events)} geformatteerde evenementen geretourneerd")
        return jsonify(formatted_events)
    except Exception as e:
        logger.error(f"Fout bij het ophalen van evenementen: {e}")
        return jsonify({'error': f'Fout bij het ophalen van evenementen: {str(e)}'}), 500

@bp.route('/calendar/event', methods=['POST'])
@calendar_auth_required  # Vereist dat de gebruiker is ingelogd en referenties heeft
def create_event():
    # Maak een nieuw evenement aan in de Google Calendar van de gebruiker
    logger = logging.getLogger(__name__)
    logger.debug("Aanmaken van nieuw kalender-evenement")
    try:
        current_user = get_current_user()
        creds = get_calendar_credentials(current_user.id)
        creds_dict = credentials_to_dict(creds)

        data = request.json
        if not data or 'title' not in data:
            logger.error("Titel is vereist voor het aanmaken van een evenement")
            return jsonify({'error': 'Titel is vereist'}), 400

        service = GoogleCalendarService.get_calendar_service(creds_dict)
        # Maak een nieuw evenement aan in de Google Calendar
        event = GoogleCalendarService.create_event(
            service,
            summary=data['title'],
            start_datetime=data['start'],
            end_datetime=data['end'],
            description=data.get('description', ''),
            location=data.get('location', ''),
            attendees=data.get('attendees', [])
        )
        logger.info(f"Evenement aangemaakt met ID: {event.get('id')}")

        # Retourneer het aangemaakte evenement in JSON-formaat
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        return jsonify({
            'id': event.get('id', ''),
            'title': event.get('summary', ''),
            'start': start,
            'end': end,
            'description': event.get('description', ''),
            'location': event.get('location', '')
        }), 201
    except Exception as e:
        logger.error(f"Fout bij het aanmaken van evenement: {e}")
        return jsonify({'error': f'Fout bij het aanmaken van evenement: {str(e)}'}), 500

@bp.route('/calendar/event/<event_id>', methods=['PUT'])
@calendar_auth_required  # Vereist dat de gebruiker is ingelogd en referenties heeft
def update_event(event_id):
    # Werk een bestaand evenement bij in de Google Calendar
    logger = logging.getLogger(__name__)
    logger.debug(f"Updaten van evenement ID: {event_id}")
    try:
        current_user = get_current_user()
        creds = get_calendar_credentials(current_user.id)
        creds_dict = credentials_to_dict(creds)

        data = request.json
        if not data or 'title' not in data:
            logger.error("Titel is vereist voor het updaten van een evenement")
            return jsonify({'error': 'Titel is vereist'}), 400

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
            event['start'] = {
                'dateTime': data['start'],
                'timeZone': 'UTC'
            }
        if 'end' in data:
            event['end'] = {
                'dateTime': data['end'],
                'timeZone': 'UTC'
            }
        if 'attendees' in data:
            event['attendees'] = [{'email': email} for email in data['attendees']]

        # Update evenement
        updated_event = GoogleCalendarService.update_event(
            service,
            'primary',
            event_id,
            event
        )
        logger.info(f"Evenement bijgewerkt met ID: {event_id}")

        # Retourneer het bijgewerkte evenement in JSON-formaat
        start = updated_event['start'].get('dateTime', updated_event['start'].get('date'))
        end = updated_event['end'].get('dateTime', updated_event['end'].get('date'))
        return jsonify({
            'id': updated_event.get('id', ''),
            'title': updated_event.get('summary', ''),
            'start': start,
            'end': end,
            'description': updated_event.get('description', ''),
            'location': updated_event.get('location', '')
        })
    except Exception as e:
        logger.error(f"Fout bij het updaten van evenement: {e}")
        return jsonify({'error': f'Fout bij het updaten van evenement: {str(e)}'}), 500

@bp.route('/calendar/event/<event_id>', methods=['DELETE'])
@calendar_auth_required
def delete_event(event_id):
    # Verwijder een evenement uit de Google Calendar
    logger = logging.getLogger(__name__)
    logger.debug(f"Verwijderen van evenement ID: {event_id}")
    try:
        current_user = get_current_user()
        creds = get_calendar_credentials(current_user.id)
        creds_dict = credentials_to_dict(creds)

        service = GoogleCalendarService.get_calendar_service(creds_dict)
        GoogleCalendarService.delete_event(service, 'primary', event_id)
        logger.info(f"Evenement verwijderd met ID: {event_id}")

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Fout bij het verwijderen van evenement: {e}")
        return jsonify({'error': f'Fout bij het verwijderen van evenement: {str(e)}'}), 500