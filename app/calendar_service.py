from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from flask import url_for, current_app
from google_auth_oauthlib.flow import Flow
from datetime import datetime, timedelta

# Klasse om interacties met de Google Calendar API te beheren
class GoogleCalendarService:
    # Statische methode om een Google Calendar-service te initialiseren
    @staticmethod
    def get_calendar_service(credentials_dict):
        # Converteer de referenties naar een Credentials-object
        credentials = Credentials.from_authorized_user_info(credentials_dict)
        # Maak een Google Calendar-service (versie 'v3') met de referenties
        return build('calendar', 'v3', credentials=credentials)

    # Statische methode om een OAuth2-flow te maken voor authenticatie
    @staticmethod
    def create_flow(redirect_uri=None):
        # Definieer de clientconfiguratie voor OAuth2
        client_config = {
            "web": {
                "client_id": current_app.config['GOOGLE_CLIENT_ID'],
                "client_secret": current_app.config['GOOGLE_CLIENT_SECRET'],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri or url_for('calendar.google_oauth2callback', _external=True)]  # Gebruik 'calendar.google_oauth2callback'
            }
        }
        # Definieer de scopes (toegangsniveau) die nodig zijn voor de Google Calendar API
        scopes = ['https://www.googleapis.com/auth/calendar']
        # Maak een OAuth2-flow aan met de clientconfiguratie en scopes
        flow = Flow.from_client_config(
            client_config,
            scopes=scopes,
            # Gebruik de opgegeven redirect URI of een standaardwaarde
            redirect_uri=redirect_uri or "http://localhost:5000/oauth2callback"
            )
        return flow

    # Statische methode om een lijst van kalenders op te halen
    @staticmethod
    def get_calendar_list(service):
        return service.calendarList().list().execute()

    # Statische methode om evenementen op te halen uit een kalender
    @staticmethod
    def get_events(service, calendar_id='primary', time_min=None, time_max=None, max_results=10):
        # Stel de starttijd in op nu als deze niet is opgegeven
        if not time_min:
            time_min = datetime.utcnow()
        # Stel de eindtijd in op 30 dagen vanaf de starttijd als deze niet is opgegeven
        if not time_max:
            time_max = time_min + timedelta(days=30)

        # Haal evenementen op uit de kalender met de opgegeven parameters
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat() + 'Z',
            timeMax=time_max.isoformat() + 'Z',
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        # Retourneer de lijst van evenementen (of een lege lijst als er geen zijn)
        return events_result.get('items', [])

    # Statische methode om een nieuw evenement aan te maken
    @staticmethod
    def create_event(service, calendar_id='primary', summary='', start_datetime=None,
                     end_datetime=None, description='', location='', attendees=None):
        # Stel de starttijd in op nu als deze niet is opgegeven
        if not start_datetime:
            start_datetime = datetime.utcnow()
        if not end_datetime:
            end_datetime = start_datetime + timedelta(hours=1)

        # Maak een evenementobject aan met de opgegeven gegevens
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_datetime.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_datetime.isoformat(),
                'timeZone': 'UTC',
            }
        }
        # Voeg genodigden toe als deze zijn opgegeven
        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]
        # Voeg het evenement toe aan de kalender en retourneer het resultaat
        return service.events().insert(calendarId=calendar_id, body=event).execute()

    # Statische methode om een bestaand evenement te updaten
    @staticmethod
    def update_event(service, calendar_id, event_id, event_data):
        # Werk het evenement bij met de nieuwe gegevens
        return service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event_data
        ).execute()

    # Statische methode om een evenement te verwijderen
    @staticmethod
    def delete_event(service, calendar_id, event_id):
        # Verwijder het evenement uit de kalender
        return service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()

    # Statische methode om vrije/beschikbare tijden op te halen
    @staticmethod
    def get_free_busy(service, time_min, time_max, calendars):
        body = {
            "timeMin": time_min.isoformat() + 'Z',
            "timeMax": time_max.isoformat() + 'Z',
            "items": [{"id": calendar} for calendar in calendars]
        }

        return service.freebusy().query(body=body).execute()