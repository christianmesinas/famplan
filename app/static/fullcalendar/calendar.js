// Read the logged-in user’s ID from the meta tag (or null if not present)
const userIdMeta = document.querySelector('meta[name="current-user-id"]');
window.CURRENT_USER_ID = userIdMeta && userIdMeta.content
  ? Number(userIdMeta.content)
  : null;

let calendar;

function initializeCalendar() {
    const calendarEl = document.getElementById('calendar');
    const eventsUrl = calendarEl.dataset.eventsUrl;
    const createEventUrl = calendarEl.dataset.eventUrl;
    const updateEventUrlTemplate = calendarEl.dataset.updateUrl;
    const deleteEventUrlTemplate = calendarEl.dataset.deleteUrl;
    const familyMembersUrl = calendarEl.dataset.familyMembersUrl;
    const familySelect = document.getElementById('family-select');

    // Laad familieleden voor het formulier
    loadFamilyMembers(familyMembersUrl);

   calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        locale: 'nl', // Toegevoegd: Nederlandse locale voor 24-uursnotatie en NL-taal
        timeZone: 'Europe/Amsterdam', // Toegevoegd: Tijdzone voor CEST
        slotLabelFormat: { // Toegevoegd: 24-uursnotatie voor tijdlabels in week/dag-weergaven
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        },
        eventTimeFormat: { // Toegevoegd: 24-uursnotatie voor evenementtijden
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        },
        events: function(fetchInfo, successCallback, failureCallback) {
            const url = eventsUrl + (familySelect.value ? `?family_id=${familySelect.value}` : '');
            console.log('Fetching events from:', url);
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    console.log('Received events:', data);
                    // Verwerk titels om voorvoegsels te verwijderen
                    data.forEach(event => {
                        if (event.title) {
                            event.title = event.title.replace(/^(.*?): /, '');
                        }
                    });
                    successCallback(data);
                })
                .catch(error => {
                    console.error('Error fetching events:', error);
                    failureCallback(error);
                });
        },
       // render title on top, meta (time • user) below
        eventContent: function(arg) {
            let titleEl = document.createElement('div');
            titleEl.classList.add('fc-event-title');
            titleEl.innerText = arg.event.title;

            let metaEl = document.createElement('div');
            metaEl.classList.add('fc-event-meta');
            const timeText = arg.timeText;
            const isMe = arg.event.extendedProps.userId === window.CURRENT_USER_ID;
            const userName = isMe ? '(me)' : arg.event.extendedProps.userName;
            metaEl.innerText = `${timeText} • ${userName}`;

            return { domNodes: [ titleEl, metaEl ] };
        },

        editable: true,
        selectable: true,
        eventDidMount: function(info) {
            // Color
            const accent = info.event.extendedProps.familyMemberName
                ? stringToColor(info.event.extendedProps.familyMemberName)
                : '#3788d8';
            info.el.style.backgroundColor = accent;
            info.el.style.borderColor = accent;

            // Clear
            info.el.innerHTML = '';

            // Container
            const container = document.createElement('div');

            // Title
            const title = document.createElement('div');
            title.classList.add('fc-event-title');
            title.innerText = info.event.title;
            container.appendChild(title);

            // Meta (start–end + who)
            const meta = document.createElement('div');
            meta.classList.add('fc-event-meta');
            const pad = n => String(n).padStart(2,'0');
            const s = info.event.start, e = info.event.end;
            const when = `${pad(s.getHours())}:${pad(s.getMinutes())}` +
                         (e ? `–${pad(e.getHours())}:${pad(e.getMinutes())}` : '');
            const isMe = info.event.extendedProps.userId === window.CURRENT_USER_ID;
            const who  = isMe ? '(me)' : (info.event.extendedProps.userName || '');
            meta.innerText = [when, who].filter(Boolean).join(' ');
            container.appendChild(meta);

            // Append
            info.el.appendChild(container);
        },


        eventClick: function(info) {
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
            if (!info.event.extendedProps.family_member_name) {
                updateEvent(info.event, updateEventUrlTemplate.replace('EVENT_ID', info.event.id));
            } else {
                info.revert();
                alert('Dit evenement is van een familielid en kan niet worden bewerkt.');
            }
        },
        eventResize: function(info) {
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

function loadFamilyMembers(url) {
    fetch(url)
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('eventFamilyMembers');
            select.innerHTML = ''; // Leeg de lijst
            data.forEach(member => {
                const option = document.createElement('option');
                option.value = member.email;
                option.textContent = member.username;
                select.appendChild(option);
            });
        })
        .catch(error => {
            console.error('Fout bij laden familieleden:', error);
        });
}

function openEventModal(event, createOrUpdateUrl, deleteUrl, startStr, endStr) {
    const modal = new bootstrap.Modal(document.getElementById('eventModal'));
    const form = document.getElementById('eventForm');
    const title = document.getElementById('eventTitle');
    const start = document.getElementById('eventStart');
    const end = document.getElementById('eventEnd');
    const description = document.getElementById('eventDescription');
    const location = document.getElementById('eventLocation');
    const familyMembers = document.getElementById('eventFamilyMembers');
    const attendees = document.getElementById('eventAttendees');
    const eventIdInput = document.getElementById('eventId');
    const deleteBtn = document.getElementById('deleteEventBtn');
    const modalTitle = document.getElementById('eventModalLabel');
    const saveBtn = document.getElementById('saveEventBtn');

    form.reset();
    eventIdInput.value = '';
    familyMembers.selectedOptions = []; // Reset geselecteerde familieleden

    if (event) {
        modalTitle.textContent = 'Edit Event';
        eventIdInput.value = event.id;
        title.value = event.title.replace(/^(.*?): /, '');
        start.value = event.start.toISOString().slice(0, 16);
        end.value = event.end ? event.end.toISOString().slice(0, 16) : '';
        description.value = event.extendedProps.description || '';
        location.value = event.extendedProps.location || '';
        attendees.value = event.extendedProps.attendees ? event.extendedProps.attendees.join(', ') : '';
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
    const familyMembers = Array.from(document.getElementById('eventFamilyMembers').selectedOptions).map(option => option.value);
    const extraAttendees = document.getElementById('eventAttendees').value.split(',').map(email => email.trim()).filter(email => email);

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
        attendees: [...familyMembers, ...extraAttendees]
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

function stringToColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    let color = '#';
    for (let i = 0; i < 3; i++) {
        const value = (hash >> (i * 8)) & 0xFF;
        color += ('00' + value.toString(16)).substr(-2);
    }
    return color;
}

function refreshCalendar(eventsUrl) {
    calendar.setOption('events', eventsUrl);
    calendar.refetchEvents();
}

document.addEventListener('DOMContentLoaded', function() {
    initializeCalendar();
    document.getElementById('create-event-btn').addEventListener('click', function() {
        openEventModal(null, document.getElementById('calendar').dataset.eventUrl);
    });
    const familySelect = document.getElementById('family-select');
    familySelect.addEventListener('change', function() {
        const baseEventsUrl = document.getElementById('calendar').dataset.eventsUrl;
        const eventsUrl = this.value ? `${baseEventsUrl}?family_id=${this.value}` : baseEventsUrl;
        refreshCalendar(eventsUrl);
    });
});

window.refreshCalendar = refreshCalendar;