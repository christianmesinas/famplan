from flask import Blueprint, redirect, url_for, session, request, render_template, flash, current_app, jsonify
from app import db
from app.models import User, CalendarCredentials
from app.calendar_service import GoogleCalendarService
import sqlalchemy as sa
from datetime import datetime, timedelta
import json
from functools import wraps

bp = Blueprint('calendar', __name__)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def calendar_auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_current_user()
        if not current_user:
            return redirect(url_for('login'))

        creds = db.session.scalar(sa.select(CalendarCredentials).where(
            CalendarCredentials.user_id == current_user.id))

        if not creds:
            return redirect(url_for('calendar.authorize'))

        return f(*args, **kwargs)

    return decorated_function


def get_current_user():
    if 'user' in session:
        user_info = session['user']['userinfo']
        return db.session.scalar(sa.select(User).where(User.email == user_info['email']))
    return None


@bp.route('/calendar')
@login_required
def index():
    current_user = get_current_user()
    creds = db.session.scalar(sa.select(CalendarCredentials).where(
        CalendarCredentials.user_id == current_user.id))
    if not creds:
        return render_template('calendar/connect.html')
    return render_template('calendar/index.html')


@bp.route('/calendar/authorize')
@login_required
def authorize():
    flow = GoogleCalendarService.create_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true'
    )

    session['state'] = state
    return redirect(authorization_url)


@bp.route('/oauth2callback')
def google_oauth2callback():
    if 'state' not in session:
        return redirect(url_for('calendar.index'))

    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))

    flow = GoogleCalendarService.create_flow()
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    creds_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': json.dumps(credentials.scopes),
        'expiry': credentials.expiry
    }

    creds = db.session.scalar(sa.select(CalendarCredentials).where(
        CalendarCredentials.user_id == current_user.id))

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
    creds = db.session.scalar(sa.select(CalendarCredentials).where(
        CalendarCredentials.user_id == current_user.id))
    if not creds:
        return redirect(url_for('calendar.authorize'))
    creds_dict = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': json.loads(creds.scopes),
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }
    service = GoogleCalendarService.get_calendar_service(creds_dict)
    start_date = request.args.get('start')
    end_date = request.args.get('end')

    if start_date:
        start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        start_date = datetime.utcnow()

    if end_date:
        end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    else:
        end_date = start_date + timedelta(days=30)

    events = GoogleCalendarService.get_events(
        service,
        time_min=start_date,
        time_max=end_date,
        max_results=100
    )

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
@calendar_auth_required
def create_event():
    current_user = get_current_user()
    creds = db.session.scalar(sa.select(CalendarCredentials).where(
        CalendarCredentials.user_id == current_user.id))

    data = request.json

    creds_dict = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': json.loads(creds.scopes),
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }

    service = GoogleCalendarService.get_calendar_service(creds_dict)

    # datums
    start_datetime = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
    end_datetime = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))

    event = GoogleCalendarService.create_event(
        service,
        summary=data['title'],
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        description=data.get('description', ''),
        location=data.get('location', ''),
        attendees=data.get('attendees', [])
    )

    return jsonify({
        'id': event['id'],
        'title': event['summary'],
        'start': event['start']['dateTime'],
        'end': event['end']['dateTime']
    })


@bp.route('/calendar/event/<event_id>', methods=['PUT'])
@calendar_auth_required
def update_event(event_id):
    current_user = get_current_user()
    creds = db.session.scalar(sa.select(CalendarCredentials).where(
        CalendarCredentials.user_id == current_user.id))

    data = request.json

    creds_dict = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': json.loads(creds.scopes),
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }

    service = GoogleCalendarService.get_calendar_service(creds_dict)

    event = service.events().get(calendarId='primary', eventId=event_id).execute()

    # Update fields
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
    creds = db.session.scalar(sa.select(CalendarCredentials).where(
        CalendarCredentials.user_id == current_user.id))

    # credentials dictionary
    creds_dict = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': json.loads(creds.scopes),
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }

    # haal kalender
    service = GoogleCalendarService.get_calendar_service(creds_dict)

    # verwijder
    GoogleCalendarService.delete_event(service, 'primary', event_id)

    return jsonify({'success': True})