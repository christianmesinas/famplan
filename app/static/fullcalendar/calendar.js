document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM fully loaded'); // Debugregel
    console.log('FullCalendar available:', typeof FullCalendar !== 'undefined'); // Debugregel
    var calendarEl = document.getElementById('calendar');
    console.log('Calendar element:', calendarEl); // Debugregel
    if (!calendarEl) {
        console.error('Calendar element not found!');
        return;
    }
    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        height: 650,
        selectable: true,
        editable: true,
        events: "{{ url_for('calendar.events') }}",
        select: function(info) {
            openCreateModal(info.start, info.end);
        },
        eventClick: function(info) {
            openEditModal(info.event);
        },
        eventDrop: function(info) {
            updateEvent(info.event);
        },
        eventResize: function(info) {
            updateEvent(info.event);
        }
    });
    console.log('Calendar initialized:', calendar); // Debugregel
    calendar.render();
    console.log('Calendar rendered'); // Debugregel

    document.getElementById('create-event-btn').addEventListener('click', function() {
        console.log('Create Event button clicked'); // Debugregel
        const now = new Date();
        const oneHourLater = new Date(now.getTime() + 60 * 60 * 1000);
        openCreateModal(now, oneHourLater);
    });

    document.getElementById('saveEventBtn').addEventListener('click', function() {
        saveEvent();
    });

    document.getElementById('deleteEventBtn').addEventListener('click', function() {
        deleteEvent();
    });

    function openCreateModal(start, end) {
        console.log('Opening create modal'); // Debugregel
        document.getElementById('eventForm').reset();
        document.getElementById('eventId').value = '';
        document.getElementById('eventModalLabel').textContent = 'Create Event';

        document.getElementById('eventStart').value = formatDatetimeForInput(start);
        document.getElementById('eventEnd').value = formatDatetimeForInput(end);

        document.getElementById('deleteEventBtn').style.display = 'none';

        var modal = new bootstrap.Modal(document.getElementById('eventModal'));
        modal.show();
    }

    function openEditModal(event) {
        console.log('Opening edit modal'); // Debugregel
        document.getElementById('eventForm').reset();
        document.getElementById('eventModalLabel').textContent = 'Edit Event';

        document.getElementById('eventId').value = event.id;
        document.getElementById('eventTitle').value = event.title;
        document.getElementById('eventStart').value = formatDatetimeForInput(event.start);
        document.getElementById('eventEnd').value = formatDatetimeForInput(event.end || new Date(event.start.getTime() + 60 * 60 * 1000));
        document.getElementById('eventDescription').value = event.extendedProps.description || '';
        document.getElementById('eventLocation').value = event.extendedProps.location || '';

        document.getElementById('deleteEventBtn').style.display = 'block';

        var modal = new bootstrap.Modal(document.getElementById('eventModal'));
        modal.show();
    }

    function saveEvent() {
        console.log('Saving event'); // Debugregel
        const eventId = document.getElementById('eventId').value;
        const eventData = {
            title: document.getElementById('eventTitle').value,
            start: new Date(document.getElementById('eventStart').value).toISOString(),
            end: new Date(document.getElementById('eventEnd').value).toISOString(),
            description: document.getElementById('eventDescription').value,
            location: document.getElementById('eventLocation').value,
            attendees: document.getElementById('eventAttendees').value.split(',').map(email => email.trim()).filter(email => email)
        };

        if (eventId) {
            fetch(`{{ url_for('calendar.update_event', event_id='') }}${eventId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(eventData)
            })
            .then(response => response.json())
            .then(data => {
                bootstrap.Modal.getInstance(document.getElementById('eventModal')).hide();
                calendar.refetchEvents();
            })
            .catch(error => console.error('Error updating event:', error));
        } else {
            fetch("{{ url_for('calendar.create_event') }}", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(eventData)
            })
            .then(response => response.json())
            .then(data => {
                bootstrap.Modal.getInstance(document.getElementById('eventModal')).hide();
                calendar.refetchEvents();
            })
            .catch(error => console.error('Error creating event:', error));
        }
    }

    function deleteEvent() {
        console.log('Deleting event'); // Debugregel
        const eventId = document.getElementById('eventId').value;

        if (!eventId) return;

        if (confirm('Are you sure you want to delete this event?')) {
            fetch(`{{ url_for('calendar.delete_event', event_id='') }}${eventId}`, {
                method: 'DELETE'
            })
            .then(response => response.json())
            .then(data => {
                bootstrap.Modal.getInstance(document.getElementById('eventModal')).hide();
                calendar.refetchEvents();
            })
            .catch(error => console.error('Error deleting event:', error));
        }
    }

    function updateEvent(event) {
        console.log('Updating event'); // Debugregel
        const eventData = {
            title: event.title,
            start: event.start.toISOString(),
            end: (event.end || new Date(event.start.getTime() + 60 * 60 * 1000)).toISOString()
        };

        fetch(`{{ url_for('calendar.update_event', event_id='') }}${event.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(eventData)
        })
        .then(response => response.json())
        .catch(error => console.error('Error updating event:', error));
    }

    function formatDatetimeForInput(date) {
        if (!date) return '';

        const d = new Date(date);
        return d.getFullYear() + '-' +
               padZero(d.getMonth() + 1) + '-' +
               padZero(d.getDate()) + 'T' +
               padZero(d.getHours()) + ':' +
               padZero(d.getMinutes());
    }

    function padZero(num) {
        return num.toString().padStart(2, '0');
    }
});