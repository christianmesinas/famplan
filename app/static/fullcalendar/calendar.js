// calendar.js
let calendar;

function initializeCalendar() {
    const calendarEl = document.getElementById('calendar');
    const eventsUrl = calendarEl.dataset.eventsUrl;
    const createEventUrl = calendarEl.dataset.eventUrl;
    const updateEventUrlTemplate = calendarEl.dataset.updateUrl;
    const deleteEventUrlTemplate = calendarEl.dataset.deleteUrl;

    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        events: eventsUrl,
        editable: true,
        selectable: true,
        eventDidMount: function(info) {
            // Kleurcodering voor familieleden
            if (info.event.extendedProps.family_member_name) {
                const colors = {
                    // Voorbeeld: statische kleuren per gebruikersnaam
                    // Je kunt een hash-functie toevoegen voor dynamische kleuren
                    'user1': '#ff0000',
                    'user2': '#00ff00'
                };
                info.el.style.backgroundColor = colors[info.event.extendedProps.family_member_name] || '#ff5733';
                info.el.style.borderColor = colors[info.event.extendedProps.family_member_name] || '#ff5733';
            } else {
                info.el.style.backgroundColor = '#3788d8'; // Eigen evenementen
                info.el.style.borderColor = '#3788d8';
            }
        },
        eventClick: function(info) {
            // Alleen eigen evenementen kunnen worden bewerkt
            if (!info.event.extendedProps.family_member_name) {
                openEventModal(info.event, updateEventUrlTemplate, deleteEventUrlTemplate);
            } else {
                alert('Dit evenement is van een familielid en kan niet worden bewerkt.');
            }
        },
        select: function(info) {
            openEventModal(null, createEventUrl, null, info.startStr, info.endStr);
        },
        eventDrop: function(info) {
            // Update evenement bij slepen
            if (!info.event.extendedProps.family_member_name) {
                updateEvent(info.event, updateEventUrlTemplate.replace('EVENT_ID', info.event.id));
            } else {
                info.revert();
                alert('Dit evenement is van een familielid en kan niet worden bewerkt.');
            }
        },
        eventResize: function(info) {
            // Update evenement bij wijzigen grootte
            if (!info.event.extendedProps.family_member_name) {
                updateEvent(info.event, updateEventUrlTemplate.replace('EVENT_ID', info.event.id));
            } else {
                info.revert();
                alert('Dit evenement is van een familielid en kan niet worden bewerkt.');
            }
        }
    });

    calendar.render();
}

function openEventModal(event, createOrUpdateUrl, deleteUrl, startStr, endStr) {
    const modal = new bootstrap.Modal(document.getElementById('eventModal'));
    const form = document.getElementById('eventForm');
    const title = document.getElementById('eventTitle');
    const start = document.getElementById('eventStart');
    const end = document.getElementById('eventEnd');
    const description = document.getElementById('eventDescription');
    const location = document.getElementById('eventLocation');
    const attendees = document.getElementById('eventAttendees');
    const eventIdInput = document.getElementById('eventId');
    const deleteBtn = document.getElementById('deleteEventBtn');
    const modalTitle = document.getElementById('eventModalLabel');
    const saveBtn = document.getElementById('saveEventBtn');

    // Reset form
    form.reset();
    eventIdInput.value = '';

    if (event) {
        // Bestaand evenement bewerken
        modalTitle.textContent = 'Edit Event';
        eventIdInput.value = event.id;
        title.value = event.title.replace(/^(.*?): /, ''); // Verwijder gebruikersnaam/familie-prefix
        start.value = event.start.toISOString().slice(0, 16);
        end.value = event.end ? event.end.toISOString().slice(0, 16) : '';
        description.value = event.extendedProps.description || '';
        location.value = event.extendedProps.location || '';
        attendees.value = event.extendedProps.attendees || '';
        deleteBtn.style.display = 'block';
        deleteBtn.onclick = function() {
            if (confirm('Weet je zeker dat je dit evenement wilt verwijderen?')) {
                deleteEvent(event.id, deleteUrl.replace('EVENT_ID', event.id));
                modal.hide();
            }
        };
        saveBtn.onclick = function() {
            saveEvent(form, createOrUpdateUrl.replace('EVENT_ID', event.id), modal);
        };
    } else {
        // Nieuw evenement aanmaken
        modalTitle.textContent = 'Create Event';
        start.value = startStr ? new Date(startStr).toISOString().slice(0, 16) : '';
        end.value = endStr ? new Date(endStr).toISOString().slice(0, 16) : '';
        deleteBtn.style.display = 'none';
        saveBtn.onclick = function() {
            saveEvent(form, createOrUpdateUrl, modal);
        };
    }

    modal.show();
}

function saveEvent(form, url, modal) {
    const eventId = document.getElementById('eventId').value;
    const title = document.getElementById('eventTitle').value;
    const start = document.getElementById('eventStart').value;
    const end = document.getElementById('eventEnd').value;
    const description = document.getElementById('eventDescription').value;
    const location = document.getElementById('eventLocation').value;
    const attendees = document.getElementById('eventAttendees').value.split(',').map(email => email.trim()).filter(email => email);

    if (!title || !start || !end) {
        alert('Vul alle verplichte velden in.');
        return;
    }

    const eventData = {
        title: title,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        description: description,
        location: location,
        attendees: attendees
    };

    fetch(url, {
        method: eventId ? 'PUT' : 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(eventData)
    })
    .then(response => response.json())
    .then(data => {
        calendar.refetchEvents();
        modal.hide();
    })
    .catch(error => {
        console.error('Fout bij opslaan evenement:', error);
        alert('Er is een fout opgetreden bij het opslaan van het evenement.');
    });
}

function updateEvent(event, url) {
    const eventData = {
        title: event.title.replace(/^(.*?): /, ''),
        start: event.start.toISOString(),
        end: event.end ? event.end.toISOString() : null,
        description: event.extendedProps.description || '',
        location: event.extendedProps.location || '',
        attendees: event.extendedProps.attendees || []
    };

    fetch(url, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(eventData)
    })
    .then(response => response.json())
    .then(data => {
        calendar.refetchEvents();
    })
    .catch(error => {
        console.error('Fout bij updaten evenement:', error);
        alert('Er is een fout opgetreden bij het updaten van het evenement.');
    });
}

function deleteEvent(eventId, url) {
    fetch(url, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        calendar.refetchEvents();
    })
    .catch(error => {
        console.error('Fout bij verwijderen evenement:', error);
        alert('Er is een fout opgetreden bij het verwijderen van het evenement.');
    });
}

function refreshCalendar(eventsUrl) {
    calendar.setOption('events', eventsUrl);
    calendar.refetchEvents();
}

// Initialiseer de kalender bij laden van de pagina
document.addEventListener('DOMContentLoaded', function() {
    initializeCalendar();
    document.getElementById('create-event-btn').addEventListener('click', function() {
        openEventModal(null, document.getElementById('calendar').dataset.eventUrl);
    });
});

// Maak refreshCalendar globaal beschikbaar voor index.html
window.refreshCalendar = refreshCalendar;