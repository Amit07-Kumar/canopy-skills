// Canonical "Parse metadata" Code node for the transcribe-speakers workflow.
// Paste this verbatim into the second node of the workflow at
// https://imworkflow.intermesh.net/ (Transcribe Audio with Speaker Array).
//
// Two critical lines:
//   1. We use Object.entries($binary)[0] so any binary key works (audio,
//      audio0, data, file...). This prevents "No audio binary found" when
//      a client sends a different multipart field name.
//   2. The return statement re-emits the binary under the canonical key
//      `audio` so all downstream Sarvam HTTP Request nodes find it where
//      they expect.

const headers = $json.headers || {};
const query = $json.query || {};

const binaryEntries = Object.entries($binary || {});
const firstBinaryEntry = binaryEntries[0] || null;
const binary = firstBinaryEntry ? firstBinaryEntry[1] : null;
if (!binary) throw new Error('No audio binary found in request');

const ext = binary.fileExtension || 'webm';
const fileName = binary.fileName || `audio_${Date.now()}.${ext}`;

return [{
  json: {
    session_id: headers['x-session-id'] || query.session_id || `transcribe-${Date.now()}`,
    language_code: headers['x-language'] || query.language_code || 'unknown',
    model_name: headers['x-model'] || query.model || 'saaras:v3',
    with_timestamps: (headers['x-timestamps'] || query.with_timestamps || 'true') !== 'false',
    file_name: fileName,
  },
  binary: { audio: binary },
}];
