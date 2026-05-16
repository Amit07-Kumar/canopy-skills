// Browser microphone → Sarvam near-real-time captions via n8n.
// Drop-in: include this on any page, call startCapture() to begin.
//
//   <pre id="caption-stream"></pre>
//   <button onclick="startCapture()">Start</button>
//   <button onclick="stopCapture()">Stop</button>
//   <script src="/utils/browser_mic_streamer.js"></script>

const N8N_BASE   = window.SARVAM_N8N_BASE   || 'https://imworkflow.intermesh.net';
const N8N_PATH   = window.SARVAM_N8N_PATH   || '/webhook/sarvam-realtime';
const CHUNK_MS   = window.SARVAM_CHUNK_MS   || 25000; // 25 s — leaves headroom under Sarvam's 30 s cap
const LANGUAGE   = window.SARVAM_LANGUAGE   || 'unknown';
const SESSION_ID = `meet-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

let mediaRecorder = null;
let chunkIndex    = 0;
let captureStream = null;

async function startCapture(speakerHint) {
  if (mediaRecorder && mediaRecorder.state === 'recording') return;
  captureStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true }
  });
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm';
  mediaRecorder = new MediaRecorder(captureStream, { mimeType });
  mediaRecorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size > 0) sendChunk(ev.data, speakerHint);
  };
  mediaRecorder.start(CHUNK_MS);
  console.log('[sarvam] capture started, session=', SESSION_ID);
}

function stopCapture() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
  if (captureStream) captureStream.getTracks().forEach(t => t.stop());
  console.log('[sarvam] capture stopped');
}

async function sendChunk(blob, speakerHint) {
  const fd = new FormData();
  fd.append('audio', blob, `chunk_${chunkIndex}.webm`);
  const headers = {
    'X-Session-Id':  SESSION_ID,
    'X-Chunk-Index': String(chunkIndex),
    'X-Language':    LANGUAGE
  };
  if (speakerHint) headers['X-Speaker'] = speakerHint;
  const ix = chunkIndex++;
  try {
    const res = await fetch(`${N8N_BASE}${N8N_PATH}`, { method: 'POST', headers, body: fd });
    const data = await res.json();
    onTranscriptChunk(data, ix);
  } catch (err) {
    console.error('[sarvam] chunk', ix, 'failed:', err);
    onTranscriptChunk({ error: { message: String(err) }, chunk_index: ix }, ix);
  }
}

function onTranscriptChunk(data, ix) {
  const target = document.getElementById('caption-stream');
  if (!target) {
    console.log('[sarvam]', data.line || data);
    return;
  }
  if (data.error) {
    target.textContent += `[chunk ${ix}: ${data.error.message || data.error}]\n`;
    return;
  }
  if (data.line) target.textContent += data.line + '\n';
}

// Expose for inline buttons
if (typeof window !== 'undefined') {
  window.startCapture = startCapture;
  window.stopCapture  = stopCapture;
}
