## n8n Webhook Workflows

This project actively leverages several n8n webhook workflows for core system functionalities including audio processing, transcript analysis, and task/calendar automation. Below is a breakdown of all the workflows used, what they do, their `curl` requests, and expected outputs.

### 1. Audio Transcription Workflow
**Purpose:** Takes an audio recording file (like an `.mp3`), processes it, and transcribes the meeting audio into text, separated by speakers.

**cURL Request:**
```bash
curl -X POST https://imworkflow.intermesh.net/webhook/transcribe-audio \
  -H "Content-Type: multipart/form-data" \
  -F "audio=@/path/to/your/recording.mp3"
```

**Expected Output:**
Returns an array containing a JSON object mapping speakers to their transcribed text.
```json
[
  {
    "Speaker 1": "Hello everyone, let's start the scrum session.",
    "Speaker 2": "Sure, I have updated the dashboard UI."
  }
]
```

### 2. AI Summarization Workflow
**Purpose:** Analyzes the raw transcribed text to systematically extract Minutes of Meeting (MOM), actionable tasks, and Google Calendar events.

**cURL Request:**
```bash
curl -X POST https://imworkflow.intermesh.net/webhook/AISummarization \
  -H "Content-Type: application/json" \
  -d '{
    "Speaker 1": "Hello everyone, let us schedule a meeting for tomorrow at 10 AM to discuss the UI.",
    "Speaker 2": "Okay, please create a Jira task for the login page bug."
  }'
```

**Expected Output:**
Returns an array with the extracted events, tasks, and summary.
```json
[
  {
    "calender": [
      {
        "title": "UI Discussion",
        "time": "Tomorrow at 10 AM"
      }
    ],
    "Task": [
      "Create Jira task for the login page bug"
    ],
    "MOM": [
      "Discussed UI enhancements and scheduling.",
      "Identified login page bug."
    ]
  }
]
```

### 3. Google Tools Integration Workflow
**Purpose:** Triggers external integrations using the processed meeting data to automatically schedule Calendar meetings, log tasks, and send MOM emails to all invited recipients without manual intervention.

**cURL Request:**
```bash
curl -X POST https://imworkflow.intermesh.net/webhook/google_tool_event \
  -H "Content-Type: application/json" \
  -d '{
    "recipients": ["user1@example.com", "user2@example.com"],
    "calender": [
      {
        "title": "UI Discussion",
        "time": "Tomorrow at 10 AM"
      }
    ],
    "Task": [
      "Create Jira task for the login page bug"
    ],
    "MOM": [
      "Discussed UI enhancements and scheduling.",
      "Identified login page bug."
    ]
  }'
```

**Expected Output:**
Returns a success status confirming the Google Workspace APIs have been orchestrated.
```json
{
  "success": true,
  "message": "Events logged and emails sent successfully."
}
```