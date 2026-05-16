// Canonical "Fan out calendar events" Code node body for the
// google_tool_event n8n workflow.
//
// Position: between the Webhook node and the "Create an event" Google
// Calendar node. Splits one inbound request (which contains an array of
// calendar items) into N items so the downstream node fires N times.
//
// Two critical contracts:
// 1. attendees is emitted as a comma-separated STRING — the n8n Google
//    Calendar node internally does attendees.split(','). Passing an array
//    breaks with `attendee.split is not a function`.
// 2. Empty-title events are filtered out — otherwise Google Calendar API
//    returns 400 Bad Request and we get the famous "," titled invite.

const body = $json.body || $json;
const calendars = Array.isArray(body.calender) ? body.calender
                : Array.isArray(body.calendar) ? body.calendar : [];
const tz = 'Asia/Kolkata';
const recipients = Array.isArray(body.recipients) ? body.recipients : [];

const items = calendars
  .filter(c => (c && (c.event_title || c.title) || '').toString().trim())
  .map(c => {
    const startDate = c.event_date || (c.start_datetime ? c.start_datetime.slice(0, 10) : '');
    const startTime = c.event_time
      || (c.start_datetime && c.start_datetime.includes('T')
            ? c.start_datetime.split('T')[1].slice(0, 5)
            : '10:00');
    const startISO = c.start_datetime || `${startDate}T${startTime}:00`;

    let endISO = c.end_datetime;
    if (!endISO) {
      const d = new Date(startISO);
      if (!isNaN(d.getTime())) {
        d.setHours(d.getHours() + 1);
        endISO = d.toISOString().slice(0, 19);
      } else {
        endISO = startISO;
      }
    }

    const emails = (Array.isArray(c.attendees) && c.attendees.length ? c.attendees
                  : Array.isArray(c.participants) && c.participants.length ? c.participants
                  : recipients)
      .map(em => typeof em === 'string' ? em : (em && em.email) || '')
      .filter(em => em);

    return {
      json: {
        summary: c.event_title || c.title,
        description: c.description || c.notes || '',
        startISO,
        endISO,
        attendees: emails.join(','),
      },
    };
  });

return items;
