from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from flask import url_for, current_app
from google_auth_oauthlib.flow import Flow
from datetime import datetime, timedelta, timezone
import logging

# Klasse om interacties met de Google Calendar API te beheren
class GoogleCalendarService:
    # Statische methode om een Google Calendar-service te initialiseren
    @staticmethod
    def get_calendar_service(credentials_dict):
        logger = logging.getLogger(__name__)
        logger.debug("Initialiseren van Google Calendar-service met referenties")
        try:
            # Converteer de referenties naar een Credentials-object
            credentials = Credentials.from_authorized_user_info(credentials_dict)
            # Maak een Google Calendar-service (versie 'v3') met de referenties
            return build('calendar', 'v3', credentials=credentials)
        except Exception as e:
            logger.error(f"Fout bij het bouwen van de calendar-service: {e}")
            raise

    # Statische methode om een OAuth2-flow te maken voor authenticatie
    @staticmethod
    def create_flow(redirect_uri=None):
        logger = logging.getLogger(__name__)
        logger.debug("Aanmaken van OAuth2-flow voor authenticatie")
        # Definieer de clientconfiguratie voor OAuth2
        client_config = {
            "web": {
                "client_id": current_app.config['GOOGLE_CLIENT_ID'],
                "client_secret": current_app.config['GOOGLE_CLIENT_SECRET'],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri or url_for('calendar.google_oauth2callback', _external=True)]
            }
        }
        # Definieer de scopes (toegangsniveau) die nodig zijn voor de Google Calendar API
        scopes = [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/userinfo.profile',
            'https://www.googleapis.com/auth/userinfo.email',
            'openid'
        ]
        # Maak een OAuth2-flow aan met de clientconfiguratie en scopes
        flow = Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=redirect_uri or url_for('calendar.google_oauth2callback', _external=True)
        )
        return flow

    # Statische methode om een lijst van kalenders op te halen
    @staticmethod
    def get_calendar_list(service):
        logger = logging.getLogger(__name__)
        logger.debug("Ophalen van lijst met kalenders")
        try:
            return service.calendarList().list().execute()
        except Exception as e:
            logger.error(f"Fout bij het ophalen van kalenderlijst: {e}")
            raise

    # Statische methode om evenementen op te halen uit een kalender
    @staticmethod
    def get_events(service, calendar_id='primary', time_min=None, time_max=None, max_results=10):
        logger = logging.getLogger(__name__)
        logger.debug(f"Ophalen van evenementen voor kalender {calendar_id}, time_min: {time_min}, time_max: {time_max}")
        try:
            # Converteer time_min en time_max naar datetime indien strings
            if isinstance(time_min, str):
                try:
                    time_min = datetime.fromisoformat(time_min.rstrip('Z').replace('Z', '+00:00'))
                    logger.debug(f"Geconverteerde time_min: {time_min}")
                except ValueError as e:
                    logger.error(f"Ongeldig time_min formaat: {time_min}, fout: {e}")
                    raise ValueError(f"Ongeldig time_min formaat: {time_min}")
            if isinstance(time_max, str):
                try:
                    time_max = datetime.fromisoformat(time_max.rstrip('Z').replace('Z', '+00:00'))
                    logger.debug(f"Geconverteerde time_max: {time_max}")
                except ValueError as e:
                    logger.error(f"Ongeldig time_max formaat: {time_max}, fout: {e}")
                    raise ValueError(f"Ongeldig time_max formaat: {time_max}")

            # Stel standaard starttijd in op nu als niet opgegeven
            if not time_min:
                time_min = datetime.utcnow()
                logger.debug(f"Standaard time_min ingesteld op: {time_min}")
            # Stel standaard eindtijd in op 30 dagen vanaf start als niet opgegeven
            if not time_max:
                time_max = time_min + timedelta(days=30)
                logger.debug(f"Standaard time_max ingesteld op: {time_max}")

            # Haal evenementen op uit de kalender met de opgegeven parameters
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min.astimezone(timezone.utc).isoformat(),
                timeMax=time_max.astimezone(timezone.utc).isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            logger.info(f"{len(events)} evenementen opgehaald uit kalender {calendar_id}")
            logger.debug(f"Ruwe evenementen: {events}")
            return events
        except Exception as e:
            logger.error(f"Fout bij het ophalen van evenementen: {e}")
            raise

    # Statische methode om een nieuw evenement aan te maken
    @staticmethod
    def create_event(service, calendar_id='primary', summary='', start_datetime=None,
                     end_datetime=None, description='', location='', attendees=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Aanmaken van evenement: summary={summary}, start={start_datetime}, end={end_datetime}")
        try:
            # Converteer start_datetime en end_datetime indien strings
            if isinstance(start_datetime, str):
                start_datetime = datetime.fromisoformat(start_datetime.rstrip('Z').replace('Z', '+00:00'))
                logger.debug(f"Geconverteerde start_datetime: {start_datetime}")
            if isinstance(end_datetime, str):
                end_datetime = datetime.fromisoformat(end_datetime.rstrip('Z').replace('Z', '+00:00'))
                logger.debug(f"Geconverteerde end_datetime: {end_datetime}")

            # Stel standaard starttijd in op nu als niet opgegeven
            if not start_datetime:
                start_datetime = datetime.utcnow()
                logger.debug(f"Standaard start_datetime ingesteld op: {start_datetime}")
            # Stel standaard eindtijd in op 1 uur later als niet opgegeven
            if not end_datetime:
                end_datetime = start_datetime + timedelta(hours=1)
                logger.debug(f"Standaard end_datetime ingesteld op: {end_datetime}")

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
            created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
            logger.info(f"Evenement aangemaakt met ID: {created_event.get('id')}")
            return created_event
        except Exception as e:
            logger.error(f"Fout bij het aanmaken van evenement: {e}")
            raise

    # Statische methode om een bestaand evenement te updaten
    @staticmethod
    def update_event(service, calendar_id, event_id, event_data):
        logger = logging.getLogger(__name__)
        logger.debug(f"Updaten van evenement ID: {event_id}")
        try:
            # Update het evenement met de nieuwe gegevens
            updated_event = service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event_data
            ).execute()
            logger.info(f"Evenement bijgewerkt met ID: {event_id}")
            return updated_event
        except Exception as e:
            logger.error(f"Fout bij het updaten van evenement: {e}")
            raise

    # Statische methode om een evenement te verwijderen
    @staticmethod
    def delete_event(service, calendar_id, event_id):
        logger = logging.getLogger(__name__)
        logger.debug(f"Verwijderen van evenement ID: {event_id}")
        try:
            # Verwijder het evenement uit de kalender
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            logger.info(f"Evenement verwijderd met ID: {event_id}")
        except Exception as e:
            logger.error(f"Fout bij het verwijderen van evenement: {e}")
            raise

    # Statische methode om vrije/beschikbare tijden op te halen
    @staticmethod
    def get_free_busy(service, time_min, time_max, calendars):
        logger = logging.getLogger(__name__)
        logger.debug(f"Ophalen van vrije/beschikbare tijden voor kalenders: {calendars}")
        try:
            # Converteer time_min en time_max naar datetime indien strings
            if isinstance(time_min, str):
                time_min = datetime.fromisoformat(time_min.rstrip('Z').replace('Z', '+00:00'))
                logger.debug(f"Geconverteerde time_min: {time_min}")
            if isinstance(time_max, str):
                time_max = datetime.fromisoformat(time_max.rstrip('Z').replace('Z', '+00:00'))
                logger.debug(f"Geconverteerde time_max: {time_max}")

            # Maak een verzoek voor vrije/beschikbare tijden
            body = {
                "timeMin": time_min.astimezone(timezone.utc).isoformat(),
                "timeMax": time_max.astimezone(timezone.utc).isoformat(),
                "items": [{"id": calendar} for calendar in calendars]
            }
            result = service.freebusy().query(body=body).execute()
            logger.info("Vrije/beschikbare tijden opgehaald")
            return result
        except Exception as e:
            logger.error(f"Fout bij het ophalen van vrije/beschikbare tijden: {e}")
            raise