from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from flask import url_for, current_app
from google_auth_oauthlib.flow import Flow
import os
from datetime import datetime, timedelta


class GoogleCalendarService:
    @staticmethod
    def get_calendar_service(credentials_dict):
        credentials = Credentials.from_authorized_user_info(credentials_dict)
        return build('calendar', 'v3', credentials=credentials)

    @staticmethod
    def create_flow(redirect_uri=None):
        """ OAuth2 """
        client_config = {
            "web": {
                "client_id": current_app.config['GOOGLE_CLIENT_ID'],
                "client_secret": current_app.config['GOOGLE_CLIENT_SECRET'],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri or url_for('calendar.google_oauth2callback', _external=True)]  # Gebruik 'calendar.google_oauth2callback'
            }
        }

        scopes = ['https://www.googleapis.com/auth/calendar']
        flow = Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=redirect_uri or "http://localhost:5000/oauth2callback"
            )
        return flow

    @staticmethod
    def get_calendar_list(service):
        """lijst kalenders"""
        return service.calendarList().list().execute()

    @staticmethod
    def get_events(service, calendar_id='primary', time_min=None, time_max=None, max_results=10):
        """events"""
        if not time_min:
            time_min = datetime.utcnow()
        if not time_max:
            time_max = time_min + timedelta(days=30)

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat() + 'Z',
            timeMax=time_max.isoformat() + 'Z',
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        return events_result.get('items', [])

    @staticmethod
    def create_event(service, calendar_id='primary', summary='', start_datetime=None,
                     end_datetime=None, description='', location='', attendees=None):
        if not start_datetime:
            start_datetime = datetime.utcnow()
        if not end_datetime:
            end_datetime = start_datetime + timedelta(hours=1)

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

        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]

        return service.events().insert(calendarId=calendar_id, body=event).execute()

    @staticmethod
    def update_event(service, calendar_id, event_id, event_data):
        return service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event_data
        ).execute()

    @staticmethod
    def delete_event(service, calendar_id, event_id):
        return service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()

    @staticmethod
    def get_free_busy(service, time_min, time_max, calendars):
        body = {
            "timeMin": time_min.isoformat() + 'Z',
            "timeMax": time_max.isoformat() + 'Z',
            "items": [{"id": calendar} for calendar in calendars]
        }

        return service.freebusy().query(body=body).execute()