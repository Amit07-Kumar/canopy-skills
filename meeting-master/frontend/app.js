/**
 * Meeting Master - AI Meeting Assistant
 * Main JavaScript Application
 * 
 * Handles recording, transcription, AI processing, and UI interactions
 */

// =============================================================================
// Configuration
// =============================================================================

const CONFIG = {
    API_BASE: '/api/v1',
    DESCOPE_PROJECT_ID: null,   // Loaded from server at runtime
    DESCOPE_FLOW_ID: null,      // Loaded from server at runtime
    MAX_FILE_SIZE: 100 * 1024 * 1024, // 100MB
    SUPPORTED_MIME_PREFIXES: ['audio/', 'video/'],
    SUPPORTED_EXTENSIONS: ['mp3', 'mpeg', 'wav', 'ogg', 'webm', 'm4a', 'mp4', 'aac', 'flac', 'opus'],
    RECORDING_SAMPLE_RATE: 44100,
    VISUALIZER_FFT_SIZE: 256,
    // Hard cap on background status polling: 12 minutes covers a real Sarvam
    // batch job (typically <3 min) plus n8n + Stage 2/3 dispatch comfortably.
    PROCESSING_POLL_MAX_MS: 12 * 60 * 1000,
    PROCESSING_POLL_INTERVAL_MS: 1500
};

const PORTAL_MODULES = {
    meetings: { directPort: '5098', directPath: '/', gatewayPath: '/' },
    brd: { directPort: '8025', directPath: '/', gatewayPath: '/brd/' }
};

const CANOPY_GATEWAY_PORT = '5080';

const INPUT_MODE_GUIDE = {
    record: {
        title: 'Live meetings',
        copy: 'Use Record when you want hands-free capture and automatic timing.'
    },
    upload: {
        title: 'Existing recordings',
        copy: 'Use Upload for Zoom exports, interviews, and voice notes you already have.'
    },
    paste: {
        title: 'Ready-made transcripts',
        copy: 'Use Paste when the transcript already exists and you just want notes, tasks, and follow-up outputs.'
    }
};

const QUICK_START_SAMPLE_TRANSCRIPT = [
    'Product Lead: We need to send the premium listing pitch today.',
    'Customer Success Owner: I will call the buyer tomorrow at 11 AM and share the update in the group.',
    'Engineering Lead: I will update the BRD by Friday with pricing objections and next-step owners.',
    'Operations Lead: I will send the finance approval note today and schedule a follow-up review for tomorrow at 3 PM.'
].join('\n');

const LOADING_FLOW_PRESETS = {
    basic: {
        eyebrow: 'Working on it',
        title: 'Please wait a moment',
        message: 'We are getting everything ready.',
        stages: [],
        words: []
    },
    meeting_audio: {
        eyebrow: 'Meeting in progress',
        title: 'Turning your recording into a clear meeting brief',
        message: 'Keep this tab open while we process the audio.',
        stages: [
            { key: 'uploading', label: 'Uploading' },
            { key: 'queued', label: 'Preparing' },
            { key: 'transcribing', label: 'Transcribing' },
            { key: 'summarizing', label: 'Finding insights' },
            { key: 'drafting_outputs', label: 'Drafting outputs' },
            { key: 'translating', label: 'Translating' },
            { key: 'dispatching', label: 'Dispatching' },
            { key: 'completed', label: 'Ready' }
        ],
        words: ['Uploading audio', 'Transcribing', 'Finding decisions', 'Building summary', 'Pulling tasks', 'Translating to English', 'Drafting email'],
        simulated: true,
        minProgress: 12,
        maxProgress: 90
    },
    meeting_text: {
        eyebrow: 'Meeting in progress',
        title: 'Turning your transcript into a clean follow-up',
        message: 'We are reading the discussion and pulling out what matters.',
        stages: [
            { key: 'reading_transcript', label: 'Reading transcript' },
            { key: 'summarizing', label: 'Finding insights' },
            { key: 'drafting_outputs', label: 'Drafting outputs' },
            { key: 'translating', label: 'Translating' },
            { key: 'dispatching', label: 'Dispatching' },
            { key: 'completed', label: 'Ready' }
        ],
        words: ['Reading transcript', 'Finding summary', 'Spotting actions', 'Building tasks', 'Translating to English', 'Drafting email'],
        simulated: true,
        minProgress: 18,
        maxProgress: 88
    },
    send_email: {
        eyebrow: 'Sending follow-up',
        title: 'Sending your MoM email',
        message: 'We are preparing the follow-up email and calling your workflow.',
        stages: [
            { key: 'preparing_email', label: 'Preparing' },
            { key: 'sending_email', label: 'Calling workflow' },
            { key: 'completed', label: 'Sent' }
        ],
        words: ['Checking recipients', 'Preparing message', 'Calling webhook', 'Sending update'],
        simulated: true,
        minProgress: 20,
        maxProgress: 84
    },
    generate_brd: {
        eyebrow: 'BRD generation',
        title: 'Drafting a Business Requirements Document in RequireWise',
        message: 'Long context BRD synthesis can take 2-3 minutes. Keep this tab open.',
        stages: [
            { key: 'packaging_context', label: 'Packaging context' },
            { key: 'calling_brd_agent', label: 'Calling RequireWise' },
            { key: 'rendering_brd', label: 'Rendering BRD' },
            { key: 'completed', label: 'Ready' }
        ],
        words: ['Packaging meeting context', 'Calling LLM', 'Structuring sections', 'Rendering markdown', 'Persisting BRD'],
        simulated: true,
        minProgress: 8,
        maxProgress: 92
    }
};

// Hard wall-clock cap on the BRD generate-brd round trip — matches the
// backend httpx timeout of 420s in api.py with a small client-side margin.
const BRD_GENERATE_CLIENT_TIMEOUT_MS = 430 * 1000;

// =============================================================================
// Application State
// =============================================================================

const State = {
    user: null,
    token: null,
    settings: null,
    kpiOverview: null,
    loadingFlow: null,
    loadingProgressTimer: null,
    loadingWordTimer: null,
    isProcessingMeeting: false,
    isSendingEmail: false,
    isRecording: false,
    recordingStartTime: null,
    mediaRecorder: null,
    audioChunks: [],
    audioContext: null,
    analyser: null,
    animationFrame: null,
    currentMeeting: null,
    meetings: [],
    currentPage: 1,
    totalPages: 1
};

// =============================================================================
// Main Application
// =============================================================================

const App = {
    // -------------------------------------------------------------------------
    // Initialization
    // -------------------------------------------------------------------------
    
    async init() {
        console.log('Meeting Master initializing...');
        this.initPortalShell();
        
        // Check for stored auth token
        const storedToken = localStorage.getItem('mm_token');
        if (storedToken) {
            State.token = storedToken;
            await this.loadUserProfile();
        }
        
        // Initialize Descope Auth
        await this.initDescopeAuth();
        
        // Setup event listeners
        this.setupEventListeners();
        this.renderHomeAttendees();
        this.updateCaptureGuide('record');
        await this.loadKpiOverview();
        this.updateDashboardInsights();
        this.refreshFirstRunGuide();
        // Surface filesearch readiness so the user knows the RAG layer works
        this.refreshFilesearchStatus();

        // Show appropriate screen
        this.updateUI();

        console.log('Meeting Master ready');
    },
    
    async initDescopeAuth() {
        // Fetch Descope config from backend
        try {
            const response = await fetch(`${CONFIG.API_BASE}/auth/config`);
            const authConfig = await response.json();

            if (!authConfig.descope_enabled) {
                console.log('Descope auth not configured');
                const container = document.getElementById('descope-widget-container');
                if (container) {
                    container.innerHTML = `<div class="oauth-unavailable">
                        <p>⚠️ Sign-In not configured</p>
                        <small>Use Guest Mode to continue</small>
                    </div>`;
                }
                return;
            }

            CONFIG.DESCOPE_PROJECT_ID = authConfig.descope_project_id;
            CONFIG.DESCOPE_FLOW_ID = authConfig.descope_flow_id;
        } catch (error) {
            console.warn('Could not fetch auth config:', error);
            return;
        }

        // Create Descope web component in the container
        const container = document.getElementById('descope-widget-container');
        if (!container) return;

        const descopeWc = document.createElement('descope-wc');
        descopeWc.setAttribute('project-id', CONFIG.DESCOPE_PROJECT_ID);
        descopeWc.setAttribute('flow-id', CONFIG.DESCOPE_FLOW_ID);
        descopeWc.setAttribute('theme', 'light');
        container.appendChild(descopeWc);

        // Listen for auth success
        descopeWc.addEventListener('success', (e) => {
            this.handleDescopeSuccess(e.detail);
        });
        descopeWc.addEventListener('error', (e) => {
            console.error('Descope error:', e.detail);
            this.showToast('error', 'Sign in failed', 'Authentication error');
        });
    },

    async handleDescopeSuccess(detail) {
        try {
            this.showLoading('Signing in...');

            // Descope returns sessionJwt in the detail
            const sessionJwt = detail?.sessionJwt;

            if (!sessionJwt) {
                throw new Error('No session token received');
            }

            // Exchange short-lived Descope JWT for long-lived app JWT (7 days)
            // This prevents logout-on-refresh since the app JWT doesn't expire quickly
            const res = await fetch(`${CONFIG.API_BASE}/auth/descope-login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sessionJwt }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Login exchange failed');
            }

            const data = await res.json();

            // Store long-lived app token (NOT the short-lived Descope JWT)
            State.token = data.access_token;
            localStorage.setItem('mm_token', data.access_token);
            // No need for refresh token — app JWT lasts 7 days
            localStorage.removeItem('mm_refresh_token');

            // Build user state from backend response
            const u = data.user || {};
            State.user = {
                user_id: u.user_id || '',
                name: u.name || 'User',
                email: u.email || '',
                picture_url: u.picture_url || null,
                is_guest: false,
            };

            this.hideLoading();
            this.updateUI();
            this.showToast('success', 'Welcome!', `Signed in as ${State.user.name}`);
        } catch (error) {
            this.hideLoading();
            this.showToast('error', 'Sign in failed', error.message);
        }
    },
    
    setupEventListeners() {
        // File upload
        const fileInput = document.getElementById('file-input');
        const dropzone = document.getElementById('dropzone');
        
        if (fileInput && dropzone) {
            dropzone.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => this.handleFileSelect(e.target.files[0]));
            
            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropzone.classList.add('dragover');
            });
            
            dropzone.addEventListener('dragleave', () => {
                dropzone.classList.remove('dragover');
            });
            
            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('dragover');
                const file = e.dataTransfer.files[0];
                if (file) this.handleFileSelect(file);
            });
        }
        
        // Close dropdowns on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.user-menu')) {
                const dropdown = document.getElementById('user-dropdown');
                if (dropdown) dropdown.classList.add('hidden');
            }
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + R to start/stop recording
            if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                e.preventDefault();
                this.toggleRecording();
            }
        });
    },

    initPortalShell() {
        const buildUrl = (moduleKey) => {
            const module = PORTAL_MODULES[moduleKey];
            if (!module) {
                return '#';
            }

            const { protocol, hostname, port, pathname } = window.location;
            const currentPort = port || (protocol === 'https:' ? '443' : '80');
            const isGateway = currentPort === CANOPY_GATEWAY_PORT || pathname.startsWith('/brd');

            if (isGateway) {
                return `${window.location.origin}${module.gatewayPath}`;
            }

            if (currentPort === module.directPort) {
                return module.directPath;
            }

            return `${protocol}//${hostname}:${module.directPort}${module.directPath}`;
        };

        const meetingsLink = document.getElementById('portal-link-meetings');
        const brdLink = document.getElementById('portal-link-brd');

        if (meetingsLink) {
            meetingsLink.href = buildUrl('meetings');
        }
        if (brdLink) {
            brdLink.href = buildUrl('brd');
        }
    },
    
    // -------------------------------------------------------------------------
    // Authentication
    // -------------------------------------------------------------------------
    
    // (Descope sign-in handled by handleDescopeSuccess above)

    async continueAsGuest() {
        this.showLoading('Setting up guest mode...');
        
        try {
            // Get guest token from backend
            const res = await fetch(`${CONFIG.API_BASE}/auth/guest`, {
                method: 'POST'
            });
            
            if (!res.ok) throw new Error('Failed to create guest session');
            
            const data = await res.json();
            
            // Save token (API returns 'access_token')
            State.token = data.access_token;
            localStorage.setItem('mm_token', data.access_token);
            
            // Load saved guest profile if available, otherwise use API response
            const savedProfile = JSON.parse(localStorage.getItem('mm_guest_profile') || '{}');
            State.user = { 
                user_id: data.user.user_id,
                name: savedProfile.name || data.user.name || 'Guest', 
                email: savedProfile.email || data.user.email || '', 
                isGuest: true 
            };
            
            // Load guest settings
            State.settings = this.normalizeWorkspaceSettings(
                JSON.parse(localStorage.getItem('mm_guest_settings') || '{}')
            );
            
            this.hideLoading();
            this.updateUI();
            this.showToast('success', 'Guest Mode', 'You can now record meetings. Data is saved locally.');
            
        } catch (error) {
            this.hideLoading();
            console.error('Guest mode error:', error);
            
            // Fallback to local-only guest mode
            const savedProfile = JSON.parse(localStorage.getItem('mm_guest_profile') || '{}');
            State.user = { 
                name: savedProfile.name || 'Guest', 
                email: savedProfile.email || '', 
                isGuest: true,
                localOnly: true
            };
            State.settings = this.normalizeWorkspaceSettings(
                JSON.parse(localStorage.getItem('mm_guest_settings') || '{}')
            );
            this.updateUI();
            this.showToast('warning', 'Limited Guest Mode', 'Working offline - some features may be unavailable');
        }
    },
    
    async loadUserProfile() {
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/auth/me`);
            if (res.ok) {
                State.user = await res.json();
                await this.loadSettings();
            } else {
                // Stale token — silently clear without toast
                this.clearAuth();
            }
        } catch (error) {
            console.warn('Session expired, returning to login');
            this.clearAuth();
        }
    },

    clearAuth() {
        // Silent auth reset (no toast) — used when stale token detected on load
        State.user = null;
        State.token = null;
        State.settings = null;
        localStorage.removeItem('mm_token');
        localStorage.removeItem('mm_refresh_token');
        this.updateUI();
    },
    
    logout() {
        State.user = null;
        State.token = null;
        State.settings = null;
        localStorage.removeItem('mm_token');
        localStorage.removeItem('mm_refresh_token');
        this.updateUI();
        this.showToast('info', 'Signed out', 'You have been signed out');
    },
    
    toggleUserMenu() {
        const dropdown = document.getElementById('user-dropdown');
        dropdown.classList.toggle('hidden');
    },
    
    // -------------------------------------------------------------------------
    // UI Updates
    // -------------------------------------------------------------------------
    
    updateUI() {
        const authScreen = document.getElementById('auth-screen');
        const mainScreen = document.getElementById('main-screen');
        
        if (State.user) {
            authScreen.classList.add('hidden');
            mainScreen.classList.remove('hidden');
            
            // Update user info
            const avatar = document.getElementById('user-avatar');
            const userName = document.getElementById('user-name');
            const userEmail = document.getElementById('user-email');
            
            if (avatar && State.user.picture) {
                avatar.src = State.user.picture;
            } else if (avatar) {
                avatar.src = `https://ui-avatars.com/api/?name=${encodeURIComponent(State.user.name)}&background=6366f1&color=fff`;
            }
            
            // The auth-disabled synthetic user is a backend bypass token,
            // not a real identity — never surface its placeholder name to
            // the UI. Treat it the same as "no name" so the input shows
            // its actual placeholder.
            const displayName = (State.user.name && State.user.name !== 'Auth Disabled')
                ? State.user.name
                : '';
            if (userName) userName.textContent = displayName || 'Guest';
            if (userEmail) userEmail.textContent = State.user.email || '';

            // Update home profile fields
            const homeProfileName = document.getElementById('home-profile-name');
            const homeProfileEmail = document.getElementById('home-profile-email');
            if (homeProfileName) homeProfileName.value = displayName;
            if (homeProfileEmail) homeProfileEmail.value = State.user.email || '';
            
        } else {
            authScreen.classList.remove('hidden');
            mainScreen.classList.add('hidden');
        }

        this.updateDashboardInsights();
        this.refreshFirstRunGuide();
    },
    
    switchInputTab(tab) {
        // Update tab buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        
        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `tab-${tab}`);
            content.classList.toggle('hidden', content.id !== `tab-${tab}`);
        });

        this.updateCaptureGuide(tab);
        this.updateDashboardInsights();
    },
    
    switchResultsTab(tab) {
        // Update tab buttons
        document.querySelectorAll('.results-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.results === tab);
        });
        
        // Update tab content
        document.querySelectorAll('.results-content').forEach(content => {
            content.classList.toggle('active', content.id === `results-${tab}`);
            content.classList.toggle('hidden', content.id !== `results-${tab}`);
        });
    },
    
    switchLang(lang) {
        // Update language tabs
        document.querySelectorAll('.lang-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === lang);
        });

        // Update transcript display — only two panes: English (translated)
        // and Native (raw transcript in the original language).
        const transcripts = {
            'en': document.getElementById('transcript-en'),
            'native': document.getElementById('transcript-native')
        };

        Object.entries(transcripts).forEach(([key, el]) => {
            if (el) el.classList.toggle('hidden', key !== lang);
        });
    },

    updateCaptureGuide(tab) {
        const guide = INPUT_MODE_GUIDE[tab] || INPUT_MODE_GUIDE.record;
        const title = document.getElementById('capture-note-title');
        const copy = document.getElementById('capture-note-copy');

        if (title) title.textContent = guide.title;
        if (copy) copy.textContent = guide.copy;

        if (tab === 'record') {
            this.setRecordHelp('Live recording needs browser microphone access and a configured speech-to-text provider. If recording is blocked, switch to Upload or Paste.');
        }

        this.refreshFirstRunGuide();
    },

    setRecordHelp(message, tone = 'info') {
        const help = document.getElementById('record-help');
        if (!help) {
            return;
        }

        help.textContent = message;
        help.classList.toggle('is-error', tone === 'error');
    },

    updateDashboardInsights() {
        const activeMode = document.getElementById('hero-active-mode');
        const attendeeCount = document.getElementById('hero-attendee-count');
        const meetingCount = document.getElementById('hero-meeting-count');
        const executionHealth = document.getElementById('hero-execution-health');
        const executionCopy = document.getElementById('hero-execution-copy');
        const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab || 'record';
        const savedMeetings = this.getSavedMeetingCount();
        const effectiveAttendees = this.getEffectiveAttendees();

        if (activeMode) {
            activeMode.textContent = activeTab.charAt(0).toUpperCase() + activeTab.slice(1);
        }

        if (attendeeCount) {
            attendeeCount.textContent = String(effectiveAttendees.length);
        }

        if (meetingCount) {
            meetingCount.textContent = String(savedMeetings);
        }

        if (executionHealth) {
            const value = State.kpiOverview?.execution_health_index;
            executionHealth.textContent = typeof value === 'number' ? `${Math.round(value)}` : '--';
        }

        if (executionCopy) {
            if (State.kpiOverview?.processed_meetings) {
                executionCopy.textContent = `${State.kpiOverview.processed_meetings} processed meetings, ${Math.round(State.kpiOverview.automation_coverage || 0)}% automation coverage.`;
            } else {
                executionCopy.textContent = 'Process meetings to start tracking business execution quality.';
            }
        }

        this.updateAutomationReadiness();
        this.refreshFirstRunGuide();
    },

    shouldShowFirstRunGuide() {
        const dismissed = localStorage.getItem('mm_first_run_dismissed') === 'true';
        const completed = localStorage.getItem('mm_first_run_completed') === 'true';
        return !dismissed && !completed && !State.currentMeeting && this.getSavedMeetingCount() === 0;
    },

    refreshFirstRunGuide() {
        const guide = document.getElementById('first-run-guide');
        const copy = document.getElementById('first-run-guide-copy');
        const primaryButton = document.getElementById('first-run-primary-btn');

        if (!guide || !copy || !primaryButton || !State.user) {
            return;
        }

        if (!this.shouldShowFirstRunGuide()) {
            guide.classList.add('hidden');
            return;
        }

        const hasEmail = Boolean(this.getQuickProfile().email);
        const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab || 'record';

        if (hasEmail) {
            primaryButton.textContent = 'Run the instant demo';
            copy.textContent = activeTab === 'record'
                ? 'You are ready to go. Record live or run the sample transcript to watch the MoM, calendar, BRD handoff, and KPI flow end to end.'
                : 'You are one click away from a full example. Run the sample meeting to see the MoM, calendar follow-ups, BRD handoff, and KPI score automatically.';
        } else {
            primaryButton.textContent = 'Add email and continue';
            copy.textContent = 'Set one email first so Meeting Master can auto-send the follow-up to you when the meeting is processed.';
        }

        guide.classList.remove('hidden');
    },

    dismissFirstRunGuide() {
        localStorage.setItem('mm_first_run_dismissed', 'true');
        this.refreshFirstRunGuide();
    },

    async prepareInstantDemo() {
        this.switchInputTab('paste');

        const textarea = document.getElementById('transcript-input');
        if (textarea && !textarea.value.trim()) {
            textarea.value = QUICK_START_SAMPLE_TRANSCRIPT;
        }

        const email = this.getQuickProfile().email;
        if (!email) {
            const emailField = document.getElementById('home-profile-email');
            emailField?.focus();
            this.showToast('info', 'Add your email', 'Enter one email and then press the instant demo button again to see the full automated flow.');
            this.refreshFirstRunGuide();
            return;
        }

        this.showToast('info', 'Starting demo', 'Running a sample meeting so you can review the MoM, calendar follow-ups, and KPI output immediately.');
        await this.processTranscript();
    },

    async loadKpiOverview() {
        if (State.user?.isGuest || State.user?.is_guest || !State.token) {
            State.kpiOverview = null;
            return;
        }

        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/kpis/overview`);
            if (!res.ok) {
                return;
            }
            State.kpiOverview = await res.json();
        } catch (error) {
            console.warn('Failed to load KPI overview:', error);
        }
    },

    getSavedMeetingCount() {
        if (State.user?.isGuest || State.user?.is_guest) {
            return JSON.parse(localStorage.getItem('mm_guest_meetings') || '[]').length;
        }

        return Array.isArray(State.meetings) ? State.meetings.length : 0;
    },
    
    // -------------------------------------------------------------------------
    // Recording
    // -------------------------------------------------------------------------
    
    async toggleRecording() {
        if (State.isRecording) {
            this.stopRecording();
        } else {
            await this.startRecording();
        }
    },
    
    async startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ 
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: CONFIG.RECORDING_SAMPLE_RATE
                }
            });
            
            State.mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm;codecs=opus'
            });
            
            State.audioChunks = [];
            
            State.mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) {
                    State.audioChunks.push(e.data);
                }
            };
            
            State.mediaRecorder.onstop = () => {
                const audioBlob = new Blob(State.audioChunks, { type: 'audio/webm' });
                this.processAudioBlob(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };
            
            State.mediaRecorder.start(1000); // Collect data every second
            State.isRecording = true;
            State.recordingStartTime = Date.now();
            
            // Setup audio visualization
            this.setupVisualizer(stream);
            
            // Update UI
            const recordBtn = document.getElementById('record-btn');
            const micIcon = document.getElementById('mic-icon');
            const stopIcon = document.getElementById('stop-icon');
            const recordStatus = document.getElementById('record-status');
            const recordingTimer = document.getElementById('recording-timer');
            const visualizer = document.getElementById('audio-visualizer');
            
            recordBtn.classList.add('recording');
            micIcon.classList.add('hidden');
            stopIcon.classList.remove('hidden');
            recordStatus.textContent = 'Recording... Tap to stop';
            recordingTimer.classList.remove('hidden');
            visualizer.classList.remove('hidden');
            this.setRecordHelp('Recording live audio now. When you stop, Meeting Master will transcribe it and build the summary, tasks, follow-up email, and KPI view.');
            
            // Start timer
            this.updateRecordingTimer();
            
        } catch (error) {
            console.error('Failed to start recording:', error);
            const recordStatus = document.getElementById('record-status');
            let detail = 'Could not access microphone.';

            if (error?.name === 'NotAllowedError') {
                detail = 'Microphone permission is blocked in the browser. Allow microphone access or switch to Upload/Paste.';
            } else if (error?.name === 'NotFoundError') {
                detail = 'No microphone device was found. Connect a microphone or use Upload/Paste.';
            } else if (error?.name === 'NotReadableError') {
                detail = 'The microphone is busy in another app. Close the other recording app and try again.';
            }

            if (recordStatus) {
                recordStatus.textContent = 'Microphone unavailable';
            }
            this.setRecordHelp(detail, 'error');
            this.showToast('error', 'Recording failed', detail);
        }
    },
    
    stopRecording() {
        if (State.mediaRecorder && State.isRecording) {
            State.mediaRecorder.stop();
            State.isRecording = false;
            
            // Stop visualizer
            if (State.animationFrame) {
                cancelAnimationFrame(State.animationFrame);
            }
            if (State.audioContext) {
                State.audioContext.close();
            }
            
            // Update UI
            const recordBtn = document.getElementById('record-btn');
            const micIcon = document.getElementById('mic-icon');
            const stopIcon = document.getElementById('stop-icon');
            const recordStatus = document.getElementById('record-status');
            const recordingTimer = document.getElementById('recording-timer');
            const visualizer = document.getElementById('audio-visualizer');
            
            recordBtn.classList.remove('recording');
            micIcon.classList.remove('hidden');
            stopIcon.classList.add('hidden');
            recordStatus.textContent = 'Processing recording...';
            this.setRecordHelp('Uploading the audio and preparing the transcript, action items, calendar follow-ups, and MoM draft.');
            recordingTimer.classList.add('hidden');
            visualizer.classList.add('hidden');
        }
    },
    
    updateRecordingTimer() {
        if (!State.isRecording) return;
        
        const elapsed = Math.floor((Date.now() - State.recordingStartTime) / 1000);
        const minutes = Math.floor(elapsed / 60).toString().padStart(2, '0');
        const seconds = (elapsed % 60).toString().padStart(2, '0');
        
        const timerDisplay = document.getElementById('timer-display');
        if (timerDisplay) {
            timerDisplay.textContent = `${minutes}:${seconds}`;
        }
        
        requestAnimationFrame(() => this.updateRecordingTimer());
    },
    
    setupVisualizer(stream) {
        State.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        State.analyser = State.audioContext.createAnalyser();
        
        const source = State.audioContext.createMediaStreamSource(stream);
        source.connect(State.analyser);
        
        State.analyser.fftSize = CONFIG.VISUALIZER_FFT_SIZE;
        const bufferLength = State.analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        
        const canvas = document.getElementById('visualizer-canvas');
        const ctx = canvas.getContext('2d');
        
        const draw = () => {
            if (!State.isRecording) return;
            
            State.animationFrame = requestAnimationFrame(draw);
            
            State.analyser.getByteFrequencyData(dataArray);
            
            ctx.fillStyle = '#f8fafc';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            
            const barWidth = (canvas.width / bufferLength) * 2.5;
            let x = 0;
            
            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * canvas.height;
                
                const gradient = ctx.createLinearGradient(0, canvas.height, 0, canvas.height - barHeight);
                gradient.addColorStop(0, '#6366f1');
                gradient.addColorStop(1, '#a5b4fc');
                
                ctx.fillStyle = gradient;
                ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
                
                x += barWidth + 1;
            }
        };
        
        draw();
    },
    
    // -------------------------------------------------------------------------
    // File Handling
    // -------------------------------------------------------------------------
    
    handleFileSelect(file) {
        if (!file) return;

        const mime = String(file.type || '').toLowerCase();
        const name = String(file.name || '').toLowerCase();
        const ext = name.includes('.') ? name.split('.').pop() : '';

        const mimeOk = mime && CONFIG.SUPPORTED_MIME_PREFIXES.some(prefix => mime.startsWith(prefix));
        const extOk = ext && CONFIG.SUPPORTED_EXTENSIONS.includes(ext);

        if (!mimeOk && !extOk) {
            this.showToast('error', 'Unsupported format', 'Please upload an audio or video file (mp3, wav, m4a, webm, mp4, etc.)');
            return;
        }

        if (file.size > CONFIG.MAX_FILE_SIZE) {
            this.showToast('error', 'File too large', 'Maximum file size is 100MB');
            return;
        }

        this.processAudioBlob(file);
    },
    
    async processAudioBlob(blob) {
        if (State.isProcessingMeeting) {
            this.showToast('info', 'Already processing', 'Please wait for the current meeting analysis to finish');
            return;
        }

        State.isProcessingMeeting = true;
        this.showProgressFlow('meeting_audio', {
            stageKey: 'uploading',
            message: 'Uploading the file and preparing the meeting workspace.'
        });
        
        try {
            const formData = new FormData();
            formData.append('audio', blob, 'recording.webm');
            
            // Add team members as speaker hints
            if (State.settings?.team_members) {
                const speakerHints = State.settings.team_members.map(m => m.name);
                formData.append('speaker_hints', JSON.stringify(speakerHints));
            }
            
            // Add attendees from home screen or fall back to the saved profile email
            const attendeeEmails = this.getAttendeeEmails();
            if (attendeeEmails.length > 0) {
                formData.append('attendee_emails', JSON.stringify(attendeeEmails));
            }
            
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/upload`, {
                method: 'POST',
                body: formData
            });
            
            if (!res.ok) throw new Error('Upload failed');
            
            const meeting = await res.json();
            State.currentMeeting = meeting;
            this.updateLoadingProgress({
                progress: 18,
                stageKey: 'queued',
                message: 'Upload complete. Starting meeting analysis.'
            });
            
            // Poll for processing status
            await this.pollProcessingStatus(meeting.meeting_id);
            
        } catch (error) {
            State.isProcessingMeeting = false;
            this.hideLoading();
            this.showToast('error', 'Processing failed', error.message);
            
            // Reset UI
            const recordStatus = document.getElementById('record-status');
            if (recordStatus) recordStatus.textContent = 'Tap to start recording';
        }
    },
    
    async pollProcessingStatus(meetingId, startedAt) {
        const pollStartedAt = startedAt || Date.now();

        try {
            // Hard wall-clock cap so the loading overlay never hangs forever
            // if the backend goes silent (n8n stuck job, network drop, etc).
            if (Date.now() - pollStartedAt > CONFIG.PROCESSING_POLL_MAX_MS) {
                throw new Error('Processing timed out. Open the meeting from history once it completes, or retry the upload.');
            }

            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/${meetingId}/status`);

            if (!res.ok) throw new Error('Failed to check status');

            const data = await res.json();
            const currentStatus = data.status;

            if (currentStatus === 'completed') {
                this.updateLoadingProgress({
                    progress: 100,
                    stageKey: 'completed',
                    message: data.message || 'Your meeting is ready to review.'
                });

                // Fetch full meeting data
                const meetingRes = await this.authFetch(`${CONFIG.API_BASE}/meetings/${meetingId}`);
                const meeting = await meetingRes.json();

                State.currentMeeting = meeting;
                State.isProcessingMeeting = false;
                this.hideLoading();
                this.displayResults(meeting);
                this.showToast('success', 'Processing complete!', 'Your meeting has been analyzed');

            } else if (currentStatus === 'failed') {
                throw new Error(data.error || data.message || 'Processing failed');

            } else {
                this.updateLoadingProgress({
                    progress: data.progress,
                    stageKey: data.stage,
                    message: data.message
                });

                // Still processing, poll again with the same wall-clock anchor
                setTimeout(
                    () => this.pollProcessingStatus(meetingId, pollStartedAt),
                    CONFIG.PROCESSING_POLL_INTERVAL_MS
                );
            }

        } catch (error) {
            State.isProcessingMeeting = false;
            this.hideLoading();
            this.showToast('error', 'Processing failed', error.message);
        }
    },
    
    // -------------------------------------------------------------------------
    // Transcript Processing
    // -------------------------------------------------------------------------
    
    async processTranscript() {
        if (State.isProcessingMeeting) {
            this.showToast('info', 'Already processing', 'Please wait for the current meeting analysis to finish');
            return;
        }

        const textarea = document.getElementById('transcript-input');
        const transcript = textarea.value.trim();
        
        if (!transcript) {
            this.showToast('warning', 'Empty transcript', 'Please enter some text to process');
            return;
        }
        
        State.isProcessingMeeting = true;
        this.showProgressFlow('meeting_text', {
            stageKey: 'reading_transcript',
            message: 'Reading the transcript and preparing the meeting summary.'
        });
        
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/process-text`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    transcript: transcript,
                    speaker_hints: State.settings?.team_members?.map(m => m.name) || [],
                    attendee_emails: this.getAttendeeEmails(),
                    participants: this.getParticipantNames()
                })
            });
            
            if (!res.ok) throw new Error('Processing failed');
            
            const meeting = await res.json();
            State.currentMeeting = meeting;
            
            this.updateLoadingProgress({
                progress: 100,
                stageKey: 'completed',
                message: 'Your transcript is ready to review.'
            });
            this.hideLoading();
            this.displayResults(meeting);
            this.showToast('success', 'Analysis complete!', 'Your transcript has been processed');
            localStorage.setItem('mm_first_run_completed', 'true');
            this.refreshFirstRunGuide();
            
        } catch (error) {
            State.isProcessingMeeting = false;
            this.hideLoading();
            this.showToast('error', 'Processing failed', error.message);
            return;
        }

        State.isProcessingMeeting = false;
    },
    
    // -------------------------------------------------------------------------
    // Display Results
    // -------------------------------------------------------------------------
    
    displayResults(meeting) {
        const resultsSection = document.getElementById('results-section');
        resultsSection.classList.remove('hidden');
        
        // Meeting metadata
        const meetingDate = document.getElementById('meeting-date');
        const meetingDuration = document.getElementById('meeting-duration');
        
        if (meetingDate && meeting.created_at) {
            meetingDate.textContent = new Date(meeting.created_at).toLocaleDateString();
        }
        if (meetingDuration && meeting.duration_seconds) {
            const mins = Math.floor(meeting.duration_seconds / 60);
            const secs = meeting.duration_seconds % 60;
            meetingDuration.textContent = `${mins}m ${secs}s`;
        }
        
        this.renderSummary(meeting.summary, meeting);

        // Transcripts — two panes only: English (LLM-translated) and Native
        // (raw transcript exactly as captured, regardless of language).
        const englishText = (meeting.transcript_en || '').trim();
        const rawText = (meeting.raw_transcript || meeting.transcript_hi || meeting.transcript_hinglish || '').trim();
        const isNative = this.looksNonEnglish(rawText);

        const enEl = document.getElementById('transcript-en');
        const nativeEl = document.getElementById('transcript-native');
        const nativeTabBtn = document.getElementById('lang-tab-native');
        const translationNote = document.getElementById('transcript-translation-note');

        if (enEl) {
            const englishValue = englishText
                || (!isNative ? rawText : '')
                || (enEl.dataset.emptyText || 'English translation not available yet.');
            enEl.textContent = englishValue;
            enEl.classList.toggle('is-empty', !englishText && (isNative || !rawText));
        }

        if (nativeEl) {
            // Only show the Native tab when the source is non-English.
            const nativeValue = isNative ? rawText : '';
            nativeEl.textContent = nativeValue || (nativeEl.dataset.emptyText || 'Native transcript not available.');
            nativeEl.classList.toggle('is-empty', !nativeValue);
        }

        if (nativeTabBtn) {
            nativeTabBtn.style.display = isNative ? '' : 'none';
        }

        if (translationNote) {
            translationNote.style.display = isNative ? '' : 'none';
        }

        // Default the active tab back to English on every render.
        this.switchLang('en');
        
        // Tasks
        this.renderTasks(meeting.tasks || []);
        
        // Calendar events
        this.renderCalendarEvents(meeting.calendar_events || []);
        
        // Email — build a rich, professional MoM body locally so the user
        // always sees a complete launch-style email (subject + sections +
        // owners + dates + tasks + calendar + next steps), regardless of how
        // terse AISummarization's stock body was. The user can freely edit.
        if (meeting.mail) {
            const recipients = this.getAttendeeChipEmails();
            const fallbackRecipients = (recipients && recipients.length)
                ? recipients
                : (meeting.mail.to?.length ? meeting.mail.to : this.getAttendeeEmails());

            const professionalSubject = this.buildMomSubject(meeting);
            const professionalBody = this.buildMomBody(meeting, fallbackRecipients);

            const subjectEl = document.getElementById('email-subject');
            const toChipsContainer = document.getElementById('email-recipient-chips');
            const editEl = document.getElementById('email-content');
            const previewEl = document.getElementById('email-content-preview');

            if (subjectEl) subjectEl.value = professionalSubject;
            if (toChipsContainer) this.renderRecipientChips(fallbackRecipients);
            if (editEl) {
                editEl.innerText = professionalBody;
                editEl.contentEditable = 'true';
                editEl.setAttribute('spellcheck', 'true');
            }
            if (previewEl) previewEl.innerHTML = this.renderMarkdownToHtml(professionalBody);

            // Default the user lands on the EDIT view now — explicit user
            // ask: "I should be able to freely modify whatever I want".
            this.setMomView('source');
        }

        // Update badge counts
        document.getElementById('task-count').textContent = (meeting.tasks || []).length;
        document.getElementById('calendar-count').textContent = (meeting.calendar_events || []).length;
        this.updateResultsOverview(meeting);
        this.updateMeetingActionStrip(meeting);
        this.renderMeetingKpis(meeting);
        this.updateAutomationReadiness(meeting);
        this.updateDashboardInsights();
        this.refreshFirstRunGuide();

        // When processing finishes, take the user STRAIGHT to the Follow-ups
        // & Email tab — that's the next action they want to perform, not
        // re-read the transcript.
        this.switchResultsTab('calendar-email');

        // Scroll to results
        resultsSection.scrollIntoView({ behavior: 'smooth' });
    },

    updateResultsOverview(meeting) {
        const summaryStatus = document.getElementById('overview-summary-status');
        const summaryCopy = document.getElementById('overview-summary-copy');
        const taskTotal = document.getElementById('overview-task-total');
        const calendarTotal = document.getElementById('overview-calendar-total');
        const emailStatus = document.getElementById('overview-email-status');
        const structuredSummary = this.extractStructuredSummary(meeting.summary);

        if (summaryStatus) {
            summaryStatus.textContent = meeting.summary
                ? structuredSummary ? 'Structured brief' : 'Narrative brief'
                : 'Waiting';
        }

        if (summaryCopy) {
            summaryCopy.textContent = meeting.summary
                ? 'A concise recap is ready for quick review.'
                : 'Process a meeting to generate the brief.';
        }

        if (taskTotal) {
            taskTotal.textContent = String((meeting.tasks || []).length);
        }

        if (calendarTotal) {
            calendarTotal.textContent = String((meeting.calendar_events || []).length);
        }

        if (emailStatus) {
            emailStatus.textContent = meeting.automation?.dispatch_success ? 'Auto-sent' : meeting.mail?.sent ? 'Sent' : meeting.mail?.body ? 'Ready' : 'Draft';
        }
    },

    updateMeetingActionStrip(meeting) {
        const strip = document.getElementById('meeting-action-strip');
        const copy = document.getElementById('meeting-action-copy');
        const primaryButton = document.getElementById('meeting-primary-action-btn');

        if (!strip || !copy || !primaryButton) {
            return;
        }

        const recipients = meeting?.mail?.to?.length ? meeting.mail.to : this.getAttendeeEmails();
        const eventCount = Number(meeting?.calendar_events?.length || 0);
        const taskCount = Number(meeting?.tasks?.length || 0);
        const executionHealth = Number(meeting?.kpis?.execution_health_index || 0);

        if (!meeting) {
            strip.classList.add('hidden');
            return;
        }

        if (meeting.automation?.dispatch_success || meeting.mail?.sent) {
            primaryButton.textContent = 'Review Sent MoM';
            copy.textContent = `${taskCount} ${taskCount === 1 ? 'action' : 'actions'}, ${eventCount} ${eventCount === 1 ? 'suggested follow-up hold' : 'suggested follow-up holds'}, and an Execution Health score of ${Math.round(executionHealth || 0)} are ready. The MoM email has already been sent.`;
        } else if (recipients.length > 0) {
            primaryButton.textContent = 'Send MoM Email';
            copy.textContent = `${recipients.length} recipient${recipients.length === 1 ? '' : 's'} ready. Send the MoM email now, review ${eventCount} follow-up ${eventCount === 1 ? 'hold' : 'holds'}, and use the KPI snapshot to spot execution risk quickly.`;
        } else {
            primaryButton.textContent = 'Open Email Draft';
            copy.textContent = 'Your summary is ready. Add your email once in the setup card and Canopy can handle the MoM email flow without extra steps next time.';
        }

        strip.classList.remove('hidden');
    },

    renderMeetingKpis(meeting) {
        const panel = document.getElementById('meeting-kpi-panel');
        const score = document.getElementById('meeting-kpi-score');
        const completeness = document.getElementById('kpi-context-completeness');
        const leakage = document.getElementById('kpi-action-leakage');
        const ownership = document.getElementById('kpi-ownership-coverage');
        const automation = document.getElementById('kpi-automation-status');
        const automationCopy = document.getElementById('kpi-automation-copy');
        const missing = document.getElementById('meeting-kpi-missing');
        const kpis = meeting?.kpis;

        if (!panel || !score || !completeness || !leakage || !ownership || !automation || !automationCopy || !missing) {
            return;
        }

        if (!kpis) {
            panel.classList.add('hidden');
            return;
        }

        score.textContent = `${Math.round(Number(kpis.execution_health_index || 0))}`;
        completeness.textContent = this.formatPercent(kpis.context_completeness_score);
        leakage.textContent = this.formatPercent(kpis.action_leakage_rate);
        ownership.textContent = this.formatPercent(kpis.ownership_coverage);

        if (meeting?.automation?.dispatch_success) {
            automation.textContent = 'Auto-sent';
            automationCopy.textContent = `${(meeting.automation.recipients || []).length} recipients received the meeting output automatically.`;
        } else if (kpis.email_ready) {
            automation.textContent = 'Ready';
            automationCopy.textContent = 'Email is ready, but dispatch still needs recipients or confirmation.';
        } else {
            automation.textContent = 'Needs attention';
            automationCopy.textContent = 'The workflow still needs missing fields before it can auto-dispatch.';
        }

        if (Array.isArray(kpis.missing_fields) && kpis.missing_fields.length) {
            missing.innerHTML = kpis.missing_fields
                .map(field => `<span class="meeting-kpi-chip">Missing: ${this.escapeHtml(field.replace(/_/g, ' '))}</span>`)
                .join('');
        } else {
            missing.innerHTML = '<span class="meeting-kpi-chip success">All critical execution fields captured</span>';
        }

        missing.classList.remove('hidden');
        panel.classList.remove('hidden');
    },

    formatPercent(value) {
        const numeric = Number(value);
        if (Number.isNaN(numeric)) {
            return '--';
        }
        return `${Math.round(numeric)}%`;
    },

    async refreshFilesearchStatus() {
        const el = document.getElementById('filesearch-status-text');
        if (!el) return;
        el.textContent = 'Checking connection…';
        try {
            const res = await fetch(`${CONFIG.API_BASE}/filesearch/status`);
            const data = await res.json();
            if (data.success && data.configured) {
                const docs = data.documents_count ?? '?';
                const storeName = data.store?.displayName || data.store?.storeName || 'connected';
                el.textContent = `Connected to ${storeName} — ${docs} document${docs === 1 ? '' : 's'} indexed.`;
            } else if (!data.configured) {
                el.textContent = 'File search not configured on the server. Set FILE_SEARCH_API_BASE.';
            } else {
                el.textContent = `Upstream error: ${data.error || 'unknown'}`;
            }
        } catch (e) {
            el.textContent = `Status check failed: ${e.message}`;
        }
    },

    async ingestFilesearchText() {
        const titleEl = document.getElementById('filesearch-ingest-title');
        const bodyEl = document.getElementById('filesearch-ingest-body');
        const statusEl = document.getElementById('filesearch-status-text');
        const title = (titleEl?.value || '').trim();
        const content = (bodyEl?.value || '').trim();
        if (!title || !content) {
            this.showToast('warning', 'Missing fields', 'Both title and content are required.');
            return;
        }
        if (statusEl) statusEl.textContent = 'Ingesting…';
        try {
            const res = await fetch(`${CONFIG.API_BASE}/filesearch/ingest-text`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, content, source: 'meeting-master-ui' })
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.detail || data.error || 'Ingest failed');
            }
            this.showToast('success', 'Ingested', `Saved as ${data.filename || title}.`);
            if (bodyEl) bodyEl.value = '';
            if (titleEl) titleEl.value = '';
            await this.refreshFilesearchStatus();
        } catch (e) {
            this.showToast('error', 'Ingest failed', e.message);
            if (statusEl) statusEl.textContent = `Ingest failed: ${e.message}`;
        }
    },

    async ingestFilesearchFile(event) {
        const input = event?.target;
        const file = input?.files?.[0];
        if (!file) return;
        const statusEl = document.getElementById('filesearch-status-text');
        if (statusEl) statusEl.textContent = `Uploading ${file.name}…`;
        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch(`${CONFIG.API_BASE}/filesearch/ingest-file`, {
                method: 'POST',
                body: fd
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.detail || data.error || 'Upload failed');
            }
            this.showToast('success', 'Uploaded', `${file.name} indexed.`);
            if (input) input.value = '';
            await this.refreshFilesearchStatus();
        } catch (e) {
            this.showToast('error', 'Upload failed', e.message);
            if (statusEl) statusEl.textContent = `Upload failed: ${e.message}`;
        }
    },

    async searchFilesearch() {
        const qEl = document.getElementById('filesearch-query');
        const resultEl = document.getElementById('filesearch-result');
        const query = (qEl?.value || '').trim();
        if (!query) {
            this.showToast('warning', 'Empty query', 'Type something to search for.');
            return;
        }
        if (resultEl) resultEl.textContent = 'Searching…';
        try {
            const res = await fetch(`${CONFIG.API_BASE}/filesearch/search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query })
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || 'Search failed');
            }
            const answer = data.answer || data.response || data.summary || data.text || '';
            const hits = Array.isArray(data.sources) ? data.sources : (Array.isArray(data.hits) ? data.hits : []);
            if (resultEl) {
                const answerHtml = answer
                    ? `<div style="white-space:pre-wrap;color:var(--gray-800);">${this.escapeHtml(answer)}</div>`
                    : '<em>(no direct answer returned)</em>';
                const hitsHtml = hits.length
                    ? `<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--gray-600);">Sources: ${hits.length}</div>`
                    : '';
                resultEl.innerHTML = answerHtml + hitsHtml;
            }
        } catch (e) {
            this.showToast('error', 'Search failed', e.message);
            if (resultEl) resultEl.textContent = `Error: ${e.message}`;
        }
    },

    buildMomSubject(meeting) {
        // Strip generic "AI daily scrum summary may 16 2026" garbage and
        // produce a clear, scannable subject: "MoM • <Project Title> • <Date>"
        const date = meeting?.created_at ? new Date(meeting.created_at) : new Date();
        const dateStr = date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });

        const title = (meeting?.title || '').trim();
        const summary = this.extractStructuredSummary(meeting?.summary);
        const topicCandidate = summary?.topic
            || (meeting?.mail?.subject?.replace(/^MoM:\s*/i, '').split(' - ')[0])
            || meeting?.summary?.split(/[.;\n]/)?.[0]
            || 'Meeting follow-up';
        const cleanedTopic = String(topicCandidate || '').trim().replace(/^["'`]|["'`]$/g, '');

        const baseTitle = title && title.length > 4
            ? title
            : cleanedTopic;

        return `MoM • ${baseTitle.slice(0, 80)} • ${dateStr}`;
    },

    buildMomBody(meeting, recipients) {
        // Build a launch-mail-style professional MoM. Includes everything
        // the recipient needs in one read: header, agenda, decisions, action
        // items with owners + dates, calendar holds, BRD context, next steps.
        const date = meeting?.created_at ? new Date(meeting.created_at) : new Date();
        const dateStr = date.toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' });
        const title = (meeting?.title || 'Meeting').trim();
        const tasks = Array.isArray(meeting?.tasks) ? meeting.tasks : [];
        const events = Array.isArray(meeting?.calendar_events) ? meeting.calendar_events : [];
        const attendees = Array.isArray(meeting?.attendees) ? meeting.attendees : [];
        const kpis = meeting?.kpis || {};
        const automation = meeting?.automation || {};
        const structured = this.extractStructuredSummary(meeting?.summary);

        const attendeeBlock = attendees.length
            ? attendees
                .map(a => {
                    const name = (a?.name || a?.speaker_id || '').trim();
                    const email = (a?.email || '').trim();
                    return email ? `- **${name || email}** (${email})` : (name ? `- **${name}**` : null);
                })
                .filter(Boolean)
                .join('\n')
            : '- _(none captured)_';

        const recipientLine = (recipients && recipients.length)
            ? `**To:** ${recipients.join(', ')}`
            : '';

        const decisionBlock = structured?.decisions
            ? `\n\n## Decisions\n${structured.decisions}`
            : '';

        const topicLine = structured?.topic
            ? `**Topic:** ${structured.topic}\n\n`
            : '';

        const discussion = (structured?.discussion_summary
            || structured?.summary
            || meeting?.summary
            || '_Meeting recap pending review._').toString().trim();

        const tasksTable = tasks.length
            ? [
                '| # | Action Item | Owner | Category | Priority | Due |',
                '|---|---|---|---|---|---|',
                ...tasks.map((t, i) => {
                    const ownerCandidate = t.assignee
                        || (attendees.find(a => a.name && (t.description || '').includes(a.name)) || {}).name
                        || '_TBD_';
                    return `| ${i + 1} | **${(t.title || 'Untitled').trim()}** | ${ownerCandidate} | ${t.category || 'OPS'} | ${t.priority || 'MEDIUM'} | ${t.due_date || '_TBD_'} |`;
                }),
            ].join('\n')
            : '_No action items captured._';

        const calendarBlock = events.length
            ? events
                .map((e, i) => {
                    const start = e.start_datetime || '';
                    const startPretty = start
                        ? new Date(start).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
                        : '_TBD_';
                    return `${i + 1}. **${(e.title || 'Follow-up').trim()}** — ${startPretty}\n   ${e.description || ''}`.trim();
                })
                .join('\n\n')
            : '_No calendar holds scheduled._';

        const kpiBlock = kpis && Object.keys(kpis).length
            ? [
                `- **Execution Health Index:** ${Math.round(kpis.execution_health_index || 0)} / 100`,
                `- **Context Completeness:** ${Math.round(kpis.context_completeness_score || 0)}%`,
                `- **Action Leakage:** ${Math.round(kpis.action_leakage_rate || 0)}%`,
                `- **Ownership Coverage:** ${Math.round(kpis.ownership_coverage || 0)}%`,
                `- **Auto-dispatch:** ${automation.dispatch_success ? 'Email + Calendar sent automatically' : 'Pending'}`,
            ].join('\n')
            : '_KPIs pending._';

        return `# Minutes of Meeting — ${title}

**Date:** ${dateStr}
${recipientLine}
${topicLine}---

## Attendees
${attendeeBlock}

---

## Discussion
${discussion}${decisionBlock}

---

## Action Items
${tasksTable}

---

## Calendar Holds
${calendarBlock}

---

## Execution Snapshot
${kpiBlock}

---

## Next Steps
1. Confirm action item owners and deadlines by replying to this email.
2. Calendar holds above will be sent as Google Calendar invites — accept or reschedule.
3. If a BRD is needed for this initiative, click **Generate BRD** in the workspace — it pulls this conversation context into a structured BRD draft in RequireWise.

---

_Auto-generated by Canopy Meeting Workspace. Edit anything in this draft before sending — the email body is fully editable._
`;
    },

    getAttendeeChipEmails() {
        // Collect all email addresses from the chip-input pill list
        const container = document.getElementById('email-recipient-chips');
        if (!container) return [];
        return Array.from(container.querySelectorAll('.email-chip'))
            .map(el => (el.dataset.email || '').trim())
            .filter(em => em);
    },

    renderRecipientChips(emails) {
        const container = document.getElementById('email-recipient-chips');
        if (!container) return;
        container.innerHTML = '';
        const seen = new Set();
        (emails || []).forEach(em => {
            const e = String(em || '').trim();
            if (!e || seen.has(e.toLowerCase())) return;
            seen.add(e.toLowerCase());
            const chip = document.createElement('span');
            chip.className = 'email-chip';
            chip.dataset.email = e;
            chip.innerHTML = `${this.escapeHtml(e)}<button type="button" class="email-chip-remove" aria-label="Remove ${this.escapeHtml(e)}">×</button>`;
            chip.querySelector('.email-chip-remove').addEventListener('click', () => {
                chip.remove();
            });
            container.appendChild(chip);
        });
    },

    addRecipientFromInput(event) {
        if (event.key !== 'Enter' && event.key !== ',' && event.key !== 'Tab') return;
        event.preventDefault();
        const input = event.target;
        const raw = (input.value || '').trim().replace(/,$/, '').trim();
        if (!raw) return;
        // Accept single email per Enter; bulk paste comma/space separated also OK.
        const candidates = raw.split(/[\s,;]+/).filter(Boolean);
        const validEmails = candidates.filter(e => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e));
        if (validEmails.length === 0) {
            this.showToast('warning', 'Not an email', `"${raw}" is not a valid email`);
            return;
        }
        const existing = this.getAttendeeChipEmails();
        this.renderRecipientChips([...existing, ...validEmails]);
        input.value = '';
    },

    setMomView(view) {
        const preview = document.getElementById('email-content-preview');
        const edit = document.getElementById('email-content');
        const previewBtn = document.getElementById('mom-view-preview');
        const sourceBtn = document.getElementById('mom-view-source');
        if (!preview || !edit) return;

        if (view === 'source') {
            preview.classList.add('hidden');
            edit.classList.remove('hidden');
            previewBtn?.classList.remove('is-active');
            sourceBtn?.classList.add('is-active');
        } else {
            // Re-render the preview from whatever is currently in the editor
            const text = edit.innerText || edit.textContent || '';
            preview.innerHTML = this.renderMarkdownToHtml(text);
            preview.classList.remove('hidden');
            edit.classList.add('hidden');
            previewBtn?.classList.add('is-active');
            sourceBtn?.classList.remove('is-active');
        }
    },

    looksNonEnglish(text) {
        if (!text) return false;
        const sample = String(text).slice(0, 2000);
        let nonAscii = 0;
        for (let i = 0; i < sample.length; i++) {
            if (sample.charCodeAt(i) > 127) nonAscii++;
        }
        return nonAscii >= Math.max(8, Math.floor(sample.length * 0.03));
    },

    renderMarkdownToHtml(md) {
        // Minimal, safe Markdown -> HTML converter for the MoM email body
        // and other server-supplied text. Escapes HTML first, then upgrades
        // headings, bold, italics, lists, horizontal rules, and paragraphs.
        // Not a full CommonMark implementation — just enough to make the MoM
        // body readable without a heavy dependency.
        if (!md) return '';
        const escape = (s) => String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        const lines = String(md).replace(/\r\n/g, '\n').split('\n');
        const out = [];
        let inUl = false;
        let inOl = false;
        let para = [];

        const flushPara = () => {
            if (para.length) {
                let text = escape(para.join(' ')).trim();
                text = text
                    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
                if (text) out.push(`<p>${text}</p>`);
                para = [];
            }
        };
        const closeLists = () => {
            if (inUl) { out.push('</ul>'); inUl = false; }
            if (inOl) { out.push('</ol>'); inOl = false; }
        };

        for (const rawLine of lines) {
            const line = rawLine.trimEnd();
            if (!line.trim()) { flushPara(); closeLists(); continue; }
            // Horizontal rule
            if (/^---+\s*$/.test(line)) { flushPara(); closeLists(); out.push('<hr/>'); continue; }
            // Headings (#, ##, ###, ####)
            const headingMatch = /^(#{1,4})\s+(.+)$/.exec(line);
            if (headingMatch) {
                flushPara(); closeLists();
                const level = headingMatch[1].length;
                let text = escape(headingMatch[2]).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
                out.push(`<h${level}>${text}</h${level}>`);
                continue;
            }
            // Ordered list
            const olMatch = /^\s*\d+\.\s+(.+)$/.exec(line);
            if (olMatch) {
                flushPara();
                if (inUl) { out.push('</ul>'); inUl = false; }
                if (!inOl) { out.push('<ol>'); inOl = true; }
                let text = escape(olMatch[1]).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
                out.push(`<li>${text}</li>`);
                continue;
            }
            // Unordered list
            const ulMatch = /^\s*[-*]\s+(.+)$/.exec(line);
            if (ulMatch) {
                flushPara();
                if (inOl) { out.push('</ol>'); inOl = false; }
                if (!inUl) { out.push('<ul>'); inUl = true; }
                let text = escape(ulMatch[1]).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
                out.push(`<li>${text}</li>`);
                continue;
            }
            // Default: accumulate into a paragraph
            closeLists();
            para.push(line);
        }
        flushPara();
        closeLists();
        return out.join('\n');
    },

    renderSummary(summary, meeting) {
        const summaryContainer = document.getElementById('meeting-summary-container');
        const summaryText = document.getElementById('meeting-summary-text');
        const summaryHighlight = document.getElementById('meeting-summary-highlight');
        const summaryTags = document.getElementById('summary-tags');

        if (!summary || !summaryContainer || !summaryText || !summaryHighlight || !summaryTags) {
            summaryContainer?.classList.add('hidden');
            return;
        }

        const structured = this.extractStructuredSummary(summary);
        const taskCount = (meeting.tasks || []).length;
        const eventCount = (meeting.calendar_events || []).length;

        summaryTags.innerHTML = [
            `<span class="summary-tag">${taskCount} ${taskCount === 1 ? 'task' : 'tasks'}</span>`,
            `<span class="summary-tag">${eventCount} ${eventCount === 1 ? 'event' : 'events'}</span>`,
            `<span class="summary-tag">${meeting.mail?.sent ? 'email sent' : meeting.mail?.body ? 'email ready' : 'email draft'}</span>`
        ].join('');

        if (structured) {
            const topic = structured.topic || structured.title || 'Main takeaway captured';
            const discussion = structured.discussion_summary || structured.summary || structured.overview || '';
            const decisions = structured.decisions || structured.next_steps || '';
            const owner = structured.owner || structured.owners || '';

            summaryHighlight.innerHTML = `
                <div class="summary-spotlight">
                    <span class="summary-spotlight-label">Main topic</span>
                    <strong>${this.escapeHtml(topic)}</strong>
                </div>
            `;

            summaryText.innerHTML = [
                discussion ? `
                    <div class="summary-block">
                        <h4>Discussion</h4>
                        ${this.renderSummaryParagraphs(discussion)}
                    </div>
                ` : '',
                decisions ? `
                    <div class="summary-block">
                        <h4>Decisions and next steps</h4>
                        ${this.renderSummaryParagraphs(decisions)}
                    </div>
                ` : '',
                owner ? `
                    <div class="summary-block">
                        <h4>Owner</h4>
                        ${this.renderSummaryParagraphs(owner)}
                    </div>
                ` : ''
            ].filter(Boolean).join('');
        } else {
            summaryHighlight.innerHTML = `
                <div class="summary-spotlight">
                    <span class="summary-spotlight-label">Quick takeaway</span>
                    <strong>${taskCount} ${taskCount === 1 ? 'task' : 'tasks'} and ${eventCount} ${eventCount === 1 ? 'calendar suggestion' : 'calendar suggestions'} came out of this meeting.</strong>
                </div>
            `;

            summaryText.innerHTML = this.renderSummaryParagraphs(summary);
        }

        summaryContainer.classList.remove('hidden');
    },

    renderSummaryParagraphs(text) {
        return String(text)
            .split(/\n+/)
            .map(line => line.trim())
            .filter(Boolean)
            .map(line => `<p>${this.escapeHtml(line)}</p>`)
            .join('');
    },

    extractStructuredSummary(summary) {
        if (!summary) return null;

        if (typeof summary === 'object') {
            return summary;
        }

        const text = String(summary).trim();
        if (!text.startsWith('{')) {
            return null;
        }

        try {
            return JSON.parse(text);
        } catch (error) {
            const keys = ['topic', 'title', 'discussion_summary', 'summary', 'overview', 'decisions', 'next_steps', 'owner', 'owners'];
            const parsed = {};

            keys.forEach((key) => {
                const patterns = [
                    new RegExp(`['"]${key}['"]\\s*:\\s*"([\\s\\S]*?)"(?=\\s*,\\s*['"][a-zA-Z_]+['"]\\s*:|\\s*}$)`, 'i'),
                    new RegExp(`['"]${key}['"]\\s*:\\s*'([\\s\\S]*?)'(?=\\s*,\\s*['"][a-zA-Z_]+['"]\\s*:|\\s*}$)`, 'i')
                ];

                for (const pattern of patterns) {
                    const match = text.match(pattern);
                    if (match?.[1]) {
                        parsed[key] = match[1].trim();
                        break;
                    }
                }
            });

            return Object.keys(parsed).length ? parsed : null;
        }
    },
    
    renderTasks(tasks) {
        const tasksList = document.getElementById('tasks-list');
        tasksList.innerHTML = '';
        
        if (tasks.length === 0) {
            tasksList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">✓</div>
                    <h4>No tasks identified yet</h4>
                    <p>If the meeting includes owners or deadlines, they will appear here for review.</p>
                </div>
            `;
            return;
        }
        
        tasks.forEach((task, index) => {
            const priorityClass = task.priority ? `priority-${task.priority.toLowerCase()}` : '';
            const dueDate = task.due_date ? new Date(task.due_date).toLocaleDateString() : 'No deadline';
            
            const taskEl = document.createElement('div');
            taskEl.className = `task-item ${priorityClass}`;
            taskEl.innerHTML = `
                <input type="checkbox" class="task-checkbox" ${task.completed ? 'checked' : ''}>
                <div class="task-content">
                    <div class="task-title" contenteditable="true">${this.escapeHtml(task.title)}</div>
                    <div class="task-meta">
                        <span>👤 ${this.escapeHtml(task.assignee || 'Unassigned')}</span>
                        <span>📅 ${dueDate}</span>
                        ${task.priority ? `<span>🏷️ ${task.priority}</span>` : ''}
                    </div>
                </div>
                <div class="task-actions">
                    <button class="btn-icon" onclick="App.editTask(${index})" title="Edit">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                    </button>
                    <button class="btn-icon" onclick="App.deleteTask(${index})" title="Delete">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                    </button>
                </div>
            `;
            tasksList.appendChild(taskEl);
        });
    },
    
    renderCalendarEvents(events) {
        const calendarList = document.getElementById('calendar-events');
        calendarList.innerHTML = '';
        
        if (events.length === 0) {
            calendarList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📅</div>
                    <h4>No calendar events identified</h4>
                    <p>Scheduling suggestions from the meeting will appear here when dates or follow-ups are mentioned.</p>
                </div>
            `;
            return;
        }
        
        events.forEach((event, index) => {
            const startDate = event.start_datetime ? new Date(event.start_datetime) : null;
            const endDate = event.end_datetime ? new Date(event.end_datetime) : null;
            
            const month = startDate ? startDate.toLocaleDateString('en', { month: 'short' }) : '---';
            const day = startDate ? startDate.getDate() : '--';
            const time = startDate ? startDate.toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' }) : '--:--';
            const endTime = endDate ? endDate.toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' }) : '--:--';
            
            const eventEl = document.createElement('div');
            eventEl.className = 'calendar-event';
            eventEl.innerHTML = `
                <div class="event-date">
                    <span class="month">${month}</span>
                    <span class="day">${day}</span>
                </div>
                <div class="event-content">
                    <div class="event-title" contenteditable="true">${this.escapeHtml(event.title)}</div>
                    <div class="event-time">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <circle cx="12" cy="12" r="10"/>
                            <polyline points="12,6 12,12 16,14"/>
                        </svg>
                        ${time} - ${endTime}
                    </div>
                    ${event.attendees?.length ? `
                        <div class="event-attendees">
                            ${event.attendees.slice(0, 3).map(a => `
                                <div class="event-attendee" title="${this.escapeHtml(a)}">${a.charAt(0).toUpperCase()}</div>
                            `).join('')}
                            ${event.attendees.length > 3 ? `<div class="event-attendee">+${event.attendees.length - 3}</div>` : ''}
                        </div>
                    ` : ''}
                </div>
            `;
            calendarList.appendChild(eventEl);
        });
    },
    
    // -------------------------------------------------------------------------
    // Task Actions
    // -------------------------------------------------------------------------
    
    addTask() {
        if (!State.currentMeeting) return;
        
        if (!State.currentMeeting.tasks) {
            State.currentMeeting.tasks = [];
        }
        
        State.currentMeeting.tasks.push({
            title: 'New task',
            assignee: '',
            due_date: null,
            priority: 'Medium',
            completed: false
        });
        
        this.renderTasks(State.currentMeeting.tasks);
        document.getElementById('task-count').textContent = State.currentMeeting.tasks.length;
    },
    
    editTask(index) {
        // Task editing is handled inline via contenteditable
        // This function can be expanded for a modal editor if needed
    },
    
    deleteTask(index) {
        if (!State.currentMeeting?.tasks) return;
        
        State.currentMeeting.tasks.splice(index, 1);
        this.renderTasks(State.currentMeeting.tasks);
        document.getElementById('task-count').textContent = State.currentMeeting.tasks.length;
    },
    
    addEvent() {
        if (!State.currentMeeting) return;
        
        if (!State.currentMeeting.calendar_events) {
            State.currentMeeting.calendar_events = [];
        }
        
        const now = new Date();
        State.currentMeeting.calendar_events.push({
            title: 'New event',
            start_datetime: now.toISOString(),
            end_datetime: new Date(now.getTime() + 60 * 60 * 1000).toISOString(),
            attendees: []
        });
        
        this.renderCalendarEvents(State.currentMeeting.calendar_events);
        document.getElementById('calendar-count').textContent = State.currentMeeting.calendar_events.length;
    },
    
    // -------------------------------------------------------------------------
    // Email Actions
    // -------------------------------------------------------------------------
    
    copyEmail() {
        const subject = document.getElementById('email-subject').value;
        const body = document.getElementById('email-content').innerText;
        
        const emailText = `Subject: ${subject}\n\n${body}`;
        navigator.clipboard.writeText(emailText)
            .then(() => this.showToast('success', 'Copied!', 'Email content copied to clipboard'))
            .catch(() => this.showToast('error', 'Copy failed', 'Could not copy to clipboard'));
    },
    
    async sendEmail() {
        if (State.isSendingEmail) {
            return;
        }

        if (!State.currentMeeting?.meeting_id) {
            this.showToast('warning', 'Meeting missing', 'Process or open a meeting before sending email');
            return;
        }

        this.collectEditedData();

        const subject = document.getElementById('email-subject').value.trim();
        const recipientEmails = this.getAttendeeChipEmails();
        const to = recipientEmails.join(', ');
        const body = document.getElementById('email-content').innerText.trim();
        const cc = Array.isArray(State.currentMeeting?.mail?.cc) ? State.currentMeeting.mail.cc : [];

        if (!subject) {
            this.showToast('warning', 'Subject required', 'Please enter an email subject');
            return;
        }

        if (!recipientEmails.length) {
            this.showToast('warning', 'Recipient required', 'Add at least one email recipient as a chip (Enter to add).');
            return;
        }

        if (!body) {
            this.showToast('warning', 'Body required', 'Please enter email content before sending');
            return;
        }

        State.isSendingEmail = true;
        const sendButton = document.getElementById('send-email-btn');
        if (sendButton) {
            sendButton.disabled = true;
        }
        this.showProgressFlow('send_email', {
            stageKey: 'preparing_email',
            message: 'Preparing the MoM email and checking the recipient list.'
        });

        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/${State.currentMeeting.meeting_id}/send-email`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ subject, to, body, cc })
            });

            this.updateLoadingProgress({
                progress: 72,
                stageKey: 'sending_email',
                message: 'Calling your email delivery workflow.'
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || data.message || 'Failed to trigger email webhook');
            }

            State.currentMeeting.mail = {
                ...(State.currentMeeting.mail || {}),
                subject,
                to: to.split(',').map(email => email.trim()).filter(Boolean),
                cc,
                body,
                sent: true,
                sent_at: new Date().toISOString()
            };
            await this.refreshCurrentMeetingState();
            this.updateLoadingProgress({
                progress: 100,
                stageKey: 'completed',
                message: 'Your meeting email has been sent.'
            });
            this.showToast('success', 'Email sent', data.message || 'Workflow webhook triggered successfully');
        } catch (error) {
            this.showToast('error', 'Send failed', error.message);
        } finally {
            State.isSendingEmail = false;
            if (sendButton) {
                sendButton.disabled = false;
            }
            this.hideLoading();
        }
    },

    async refreshCurrentMeetingState() {
        if (!State.currentMeeting?.meeting_id) {
            return;
        }

        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/${State.currentMeeting.meeting_id}`);
            if (!res.ok) {
                return;
            }
            const meeting = await res.json();
            State.currentMeeting = meeting;
            await this.loadKpiOverview();
            this.displayResults(meeting);
        } catch (error) {
            console.warn('Failed to refresh current meeting:', error);
        }
    },

    openResultView(tab) {
        this.switchResultsTab(tab);

        const section = document.getElementById(`results-${tab}`);
        if (section) {
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    },

    async runPrimaryMeetingAction() {
        if (!State.currentMeeting) {
            return;
        }

        const recipients = this.getAttendeeChipEmails();
        const alreadySent = State.currentMeeting.automation?.dispatch_success || State.currentMeeting.mail?.sent;

        this.openResultView('calendar-email');

        if (alreadySent) {
            this.showToast('info', 'MoM already sent', 'The meeting update has already been delivered.');
            return;
        }

        if (!recipients.length) {
            this.showToast('warning', 'Recipient needed', 'Add at least one recipient as a chip and try again.');
            return;
        }

        await this.sendEmail();
    },
    
    // -------------------------------------------------------------------------
    // Transcript Actions
    // -------------------------------------------------------------------------
    
    copyTranscript() {
        const activeTranscript = document.querySelector('.transcript-text:not(.hidden)');
        if (activeTranscript) {
            navigator.clipboard.writeText(activeTranscript.textContent)
                .then(() => this.showToast('success', 'Copied!', 'Transcript copied to clipboard'))
                .catch(() => this.showToast('error', 'Copy failed', 'Could not copy to clipboard'));
        }
    },
    
    downloadTranscript() {
        const activeTranscript = document.querySelector('.transcript-text:not(.hidden)');
        if (activeTranscript) {
            const blob = new Blob([activeTranscript.textContent], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `meeting-transcript-${new Date().toISOString().split('T')[0]}.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    },
    
    // -------------------------------------------------------------------------
    // Meeting Save & History
    // -------------------------------------------------------------------------
    
    async saveMeeting() {
        if (!State.currentMeeting) return;
        
        const title = document.getElementById('meeting-title').value || 
            `Meeting ${new Date().toLocaleDateString()}`;
        
        State.currentMeeting.title = title;
        
        // Collect edited data from UI
        this.collectEditedData();
        
        if (State.user?.isGuest) {
            // Save to localStorage for guests
            const savedMeetings = JSON.parse(localStorage.getItem('mm_guest_meetings') || '[]');
            savedMeetings.unshift(State.currentMeeting);
            localStorage.setItem('mm_guest_meetings', JSON.stringify(savedMeetings.slice(0, 10)));
            this.updateDashboardInsights();
            this.showToast('success', 'Meeting saved!', 'Saved to browser (guest mode)');
            return;
        }
        
        this.showLoading('Saving meeting...');
        
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/${State.currentMeeting.meeting_id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(State.currentMeeting)
            });
            
            if (!res.ok) throw new Error('Save failed');
            
            this.hideLoading();
            this.updateDashboardInsights();
            this.showToast('success', 'Meeting saved!', 'Your meeting has been saved');
            
        } catch (error) {
            this.hideLoading();
            this.showToast('error', 'Save failed', error.message);
        }
    },

    async generateBrdFromMeeting() {
        if (!State.currentMeeting?.meeting_id) {
            this.showToast('warning', 'Meeting missing', 'Process or open a meeting before generating a BRD');
            return;
        }

        const meetingTitle = document.getElementById('meeting-title')?.value?.trim();
        this.showProgressFlow('generate_brd', {
            stageKey: 'packaging_context',
            message: 'Bundling meeting transcript, tasks, KPIs and recipients to send to RequireWise.'
        });

        // Surface that we have moved past "packaging" into the actual LLM call
        // — the simulated bar progresses on its own, but this resets the stage
        // chip so the user sees the right active step.
        const stageTimer = setTimeout(() => {
            this.updateLoadingProgress({
                stageKey: 'calling_brd_agent',
                message: 'RequireWise is drafting the BRD. Long-context generation can take ~2 minutes.'
            });
        }, 4000);

        const controller = new AbortController();
        const abortTimer = setTimeout(() => controller.abort(), BRD_GENERATE_CLIENT_TIMEOUT_MS);

        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/${State.currentMeeting.meeting_id}/generate-brd`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: meetingTitle || State.currentMeeting.title || '' }),
                signal: controller.signal
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || data.message || 'Failed to generate BRD');
            }

            this.updateLoadingProgress({
                progress: 100,
                stageKey: 'completed',
                message: 'BRD persisted in RequireWise.'
            });

            this.hideLoading();
            this.showToast('success', 'BRD generated', `RequireWise created ${data.data?.filename || 'a new BRD'} from this meeting context`);
        } catch (error) {
            this.hideLoading();
            const friendly = error?.name === 'AbortError'
                ? 'BRD generation took too long. Open RequireWise to check if the draft was saved, or retry.'
                : error.message;
            this.showToast('error', 'BRD generation failed', friendly);
        } finally {
            clearTimeout(stageTimer);
            clearTimeout(abortTimer);
        }
    },
    
    collectEditedData() {
        // Collect edited task titles
        const taskTitles = document.querySelectorAll('.task-title[contenteditable]');
        taskTitles.forEach((el, index) => {
            if (State.currentMeeting.tasks[index]) {
                State.currentMeeting.tasks[index].title = el.textContent;
            }
        });
        
        // Collect edited event titles
        const eventTitles = document.querySelectorAll('.event-title[contenteditable]');
        eventTitles.forEach((el, index) => {
            if (State.currentMeeting.calendar_events[index]) {
                State.currentMeeting.calendar_events[index].title = el.textContent;
            }
        });
        
        // Collect email content — read recipients from the chip list and
        // also propagate them onto every calendar event so calendar invites
        // include the same people as the MoM email.
        const recipientEmails = this.getAttendeeChipEmails();
        State.currentMeeting.mail = {
            subject: document.getElementById('email-subject').value,
            to: recipientEmails,
            body: document.getElementById('email-content').innerText
        };
        if (Array.isArray(State.currentMeeting.calendar_events)) {
            State.currentMeeting.calendar_events.forEach(ev => {
                if (ev && typeof ev === 'object') {
                    ev.attendees = recipientEmails.map(em => ({ email: em }));
                }
            });
        }
    },
    
    async openHistory() {
        const modal = document.getElementById('history-modal');
        modal.classList.remove('hidden');
        
        await this.loadMeetings();
    },
    
    closeHistory() {
        const modal = document.getElementById('history-modal');
        modal.classList.add('hidden');
    },
    
    async loadMeetings(page = 1) {
        if (State.user?.isGuest) {
            const savedMeetings = JSON.parse(localStorage.getItem('mm_guest_meetings') || '[]');
            this.renderHistory(savedMeetings);
            this.updateDashboardInsights();
            return;
        }
        
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings?page=${page}&page_size=10`);
            
            if (!res.ok) throw new Error('Failed to load meetings');
            
            const data = await res.json();
            State.meetings = data.meetings;
            State.currentPage = page;
            State.totalPages = data.total_pages;
            
            await this.loadKpiOverview();
            this.renderHistory(data.meetings);
            this.renderPagination(data.total_pages, page);
            this.updateDashboardInsights();
            
        } catch (error) {
            this.showToast('error', 'Load failed', error.message);
        }
    },
    
    renderHistory(meetings) {
        const historyList = document.getElementById('history-list');
        historyList.innerHTML = '';
        
        if (meetings.length === 0) {
            historyList.innerHTML = '<p class="text-muted text-center">No saved meetings yet</p>';
            return;
        }
        
        meetings.forEach(meeting => {
            const date = new Date(meeting.created_at || meeting.date);
            const month = date.toLocaleDateString('en', { month: 'short' });
            const day = date.getDate();
            
            const historyEl = document.createElement('div');
            historyEl.className = 'history-item';
            historyEl.onclick = () => this.loadMeetingFromHistory(meeting.meeting_id);
            historyEl.innerHTML = `
                <div class="history-date">
                    <span class="day">${day}</span>
                    <span class="month">${month}</span>
                </div>
                <div class="history-info">
                    <div class="history-title">${this.escapeHtml(meeting.title || 'Untitled Meeting')}</div>
                    <div class="history-meta">
                        <span>✅ ${meeting.task_count || meeting.tasks?.length || 0} tasks</span>
                        <span>📅 ${meeting.calendar_count || meeting.calendar_events?.length || 0} events</span>
                        <span>📈 ${meeting.kpis?.execution_health_index ? Math.round(meeting.kpis.execution_health_index) : '--'} EHI</span>
                    </div>
                </div>
            `;
            historyList.appendChild(historyEl);
        });
    },
    
    renderPagination(totalPages, currentPage) {
        const pagination = document.getElementById('history-pagination');
        pagination.innerHTML = '';
        
        if (totalPages <= 1) return;
        
        for (let i = 1; i <= totalPages; i++) {
            const btn = document.createElement('button');
            btn.textContent = i;
            btn.className = i === currentPage ? 'active' : '';
            btn.onclick = () => this.loadMeetings(i);
            pagination.appendChild(btn);
        }
    },
    
    searchHistory() {
        const query = document.getElementById('history-search').value.toLowerCase();
        const items = document.querySelectorAll('.history-item');
        
        items.forEach(item => {
            const title = item.querySelector('.history-title').textContent.toLowerCase();
            item.style.display = title.includes(query) ? 'flex' : 'none';
        });
    },
    
    async loadMeetingFromHistory(meetingId) {
        if (State.user?.isGuest) {
            const savedMeetings = JSON.parse(localStorage.getItem('mm_guest_meetings') || '[]');
            const meeting = savedMeetings.find(m => m.meeting_id === meetingId);
            if (meeting) {
                State.currentMeeting = meeting;
                this.displayResults(meeting);
                this.closeHistory();
            }
            return;
        }
        
        this.showLoading('Loading meeting...');
        
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/meetings/${meetingId}`);
            
            if (!res.ok) throw new Error('Failed to load meeting');
            
            const meeting = await res.json();
            State.currentMeeting = meeting;
            
            this.hideLoading();
            this.displayResults(meeting);
            this.closeHistory();
            
        } catch (error) {
            this.hideLoading();
            this.showToast('error', 'Load failed', error.message);
        }
    },
    
    // -------------------------------------------------------------------------
    // Settings
    // -------------------------------------------------------------------------
    
    openSettings() {
        const modal = document.getElementById('settings-modal');
        modal.classList.remove('hidden');
        
        this.populateSettings();
    },
    
    closeSettings() {
        const modal = document.getElementById('settings-modal');
        modal.classList.add('hidden');
    },

    normalizeWorkspaceSettings(settings = {}) {
        const teamMembers = Array.isArray(settings.team_members)
            ? settings.team_members
                .filter(member => member && typeof member === 'object')
                .map(member => ({
                    name: String(member.name || '').trim(),
                    email: String(member.email || '').trim()
                }))
                .filter(member => member.name)
            : [];

        return {
            profile_name: String(settings.profile_name || '').trim(),
            profile_email: String(settings.profile_email || '').trim(),
            default_language: String(settings.default_language || 'en'),
            speaker_diarization: settings.speaker_diarization !== false,
            team_members: teamMembers
        };
    },
    
    async loadSettings() {
        if (State.user?.isGuest) {
            State.settings = this.normalizeWorkspaceSettings(
                JSON.parse(localStorage.getItem('mm_guest_settings') || '{}')
            );
            return;
        }
        
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/settings`);
            if (res.ok) {
                State.settings = this.normalizeWorkspaceSettings(await res.json());
            }
        } catch (error) {
            console.error('Failed to load settings:', error);
        }
    },
    
    populateSettings() {
        const settings = this.normalizeWorkspaceSettings(State.settings || {});
        State.settings = settings;
        
        // User Profile (from State.user or settings)
        const profileName = State.user?.name || settings.profile_name || '';
        const profileEmail = State.user?.email || settings.profile_email || '';
        document.getElementById('user-profile-name').value = profileName;
        document.getElementById('user-profile-email').value = profileEmail;
        
        // Team members
        this.renderTeamMembers(settings.team_members || []);
        
        // Transcription settings
        if (settings.default_language) {
            document.getElementById('default-language').value = settings.default_language;
        }
        document.getElementById('speaker-diarization').checked = settings.speaker_diarization !== false;
    },

    saveQuickProfile() {
        const name = document.getElementById('home-profile-name').value.trim();
        const email = document.getElementById('home-profile-email').value.trim();
        
        // Update State
        State.user = State.user || {};
        State.user.name = name || State.user.name;
        State.user.email = email || State.user.email;
        
        // Also update settings modal inputs
        const settingsName = document.getElementById('user-profile-name');
        const settingsEmail = document.getElementById('user-profile-email');
        if (settingsName) settingsName.value = name;
        if (settingsEmail) settingsEmail.value = email;

        State.settings = this.normalizeWorkspaceSettings({
            ...(State.settings || {}),
            profile_name: name,
            profile_email: email
        });
        
        // Save for guest users
        if (State.user?.isGuest) {
            localStorage.setItem('mm_guest_profile', JSON.stringify({ name, email }));
            localStorage.setItem('mm_guest_settings', JSON.stringify(State.settings));
        }
        
        // Update header display
        const userNameEl = document.getElementById('user-name');
        if (userNameEl) userNameEl.textContent = name || 'Guest';

        this.renderHomeAttendees();
        this.updateAutomationReadiness();
    },

    getQuickProfile() {
        const nameInput = document.getElementById('home-profile-name');
        const emailInput = document.getElementById('home-profile-email');

        return {
            name: String(nameInput?.value || State.user?.name || State.settings?.profile_name || '').trim(),
            email: String(emailInput?.value || State.user?.email || State.settings?.profile_email || '').trim()
        };
    },

    getDefaultRecipientAttendee() {
        const profile = this.getQuickProfile();
        if (!profile.name && !profile.email) {
            return null;
        }

        return {
            name: profile.name || profile.email,
            email: profile.email || ''
        };
    },

    getEffectiveAttendees() {
        const normalized = [];
        const seen = new Set();

        const pushAttendee = (attendee) => {
            if (!attendee) {
                return;
            }

            const name = String(attendee.name || '').trim();
            const email = String(attendee.email || '').trim();
            if (!name && !email) {
                return;
            }

            const dedupeKey = `${name.toLowerCase()}|${email.toLowerCase()}`;
            if (seen.has(dedupeKey)) {
                return;
            }

            seen.add(dedupeKey);
            normalized.push({
                name: name || email,
                email: email || ''
            });
        };

        this.homeAttendees.forEach(pushAttendee);

        if (normalized.length === 0) {
            pushAttendee(this.getDefaultRecipientAttendee());
        }

        return normalized;
    },

    getParticipantNames() {
        return this.getEffectiveAttendees().map(attendee => attendee.name).filter(Boolean);
    },
    
    // Home screen attendees management
    homeAttendees: [],
    
    addHomeAttendee() {
        const nameInput = document.getElementById('home-attendee-name');
        const emailInput = document.getElementById('home-attendee-email');
        
        const name = nameInput.value.trim();
        const email = emailInput.value.trim();
        
        if (!name && !email) {
            this.showToast('warning', 'Enter details', 'Please enter name or email');
            return;
        }
        
        this.homeAttendees.push({ name: name || email, email: email || '' });
        this.renderHomeAttendees();
        
        nameInput.value = '';
        emailInput.value = '';
    },
    
    removeHomeAttendee(index) {
        this.homeAttendees.splice(index, 1);
        this.renderHomeAttendees();
    },
    
    renderHomeAttendees() {
        const list = document.getElementById('home-attendees-list');
        if (!list) {
            this.updateDashboardInsights();
            return;
        }

        const fallbackAttendee = this.getDefaultRecipientAttendee();
        
        if (this.homeAttendees.length === 0) {
            if (fallbackAttendee?.email) {
                list.innerHTML = `
                    <div class="attendee-chip attendee-chip-default">
                        <span>${this.escapeHtml(fallbackAttendee.name)} <small>(${this.escapeHtml(fallbackAttendee.email)})</small></span>
                        <span class="attendee-chip-badge">Used as default</span>
                    </div>
                `;
            } else {
                list.innerHTML = '<p class="text-muted">No attendees added yet</p>';
            }
            this.updateDashboardInsights();
            return;
        }
        
        list.innerHTML = this.homeAttendees.map((att, i) => `
            <div class="attendee-chip">
                <span>${att.name}${att.email ? ` <small>(${att.email})</small>` : ''}</span>
                <button class="chip-remove" onclick="App.removeHomeAttendee(${i})" title="Remove">&times;</button>
            </div>
        `).join('');

        this.updateDashboardInsights();
    },
    
    getAttendeeEmails() {
        return this.getEffectiveAttendees().map(a => a.email).filter(e => e);
    },

    updateAutomationReadiness(meeting = State.currentMeeting) {
        const recipientEl = document.getElementById('automation-default-recipient');
        const emailStatusEl = document.getElementById('automation-email-status');
        const calendarStatusEl = document.getElementById('automation-calendar-status');
        const kpiStatusEl = document.getElementById('automation-kpi-status');
        const copyEl = document.getElementById('automation-readiness-copy');
        const recipients = this.getAttendeeEmails();
        const primaryRecipient = recipients[0] || '';
        const eventCount = Number(meeting?.calendar_events?.length || 0);
        const taskCount = Number(meeting?.tasks?.length || 0);
        const executionHealth = Number(meeting?.kpis?.execution_health_index || State.kpiOverview?.execution_health_index || 0);

        if (recipientEl) {
            recipientEl.textContent = primaryRecipient || 'Not set';
        }

        if (emailStatusEl) {
            if (meeting?.automation?.dispatch_success || meeting?.mail?.sent) {
                emailStatusEl.textContent = 'Auto-sent after analysis';
            } else if (primaryRecipient) {
                emailStatusEl.textContent = 'Ready to send to you';
            } else {
                emailStatusEl.textContent = 'Needs your email';
            }
        }

        if (calendarStatusEl) {
            calendarStatusEl.textContent = eventCount > 0
                ? `${eventCount} follow-up ${eventCount === 1 ? 'event' : 'events'} ready`
                : 'Auto-detects meeting dates';
        }

        if (kpiStatusEl) {
            kpiStatusEl.textContent = executionHealth > 0
                ? `Execution Health ${Math.round(executionHealth)}`
                : 'Shown after every meeting';
        }

        if (copyEl) {
            if (meeting?.automation?.dispatch_success) {
                copyEl.textContent = `${(meeting.automation.recipients || []).length} recipients already received the MoM. ${taskCount} tracked ${taskCount === 1 ? 'action' : 'actions'} and business KPIs are ready below.`;
            } else if (primaryRecipient) {
                copyEl.textContent = 'Add attendees when you have them, but if you do nothing else Meeting Master will use your saved email as the default MoM destination.';
            } else {
                copyEl.textContent = 'Add your email once and Meeting Master will use it as the default follow-up destination when no attendee list is added.';
            }
        }
    },
    
    renderTeamMembers(members) {
        const teamList = document.getElementById('team-list');
        teamList.innerHTML = '';
        
        if (members.length === 0) {
            teamList.innerHTML = '<p class="text-muted">No team members added</p>';
            return;
        }
        
        members.forEach((member, index) => {
            const memberEl = document.createElement('div');
            memberEl.className = 'team-member';
            memberEl.innerHTML = `
                <div class="team-member-info">
                    <div class="team-member-name">${this.escapeHtml(member.name)}</div>
                    <div class="team-member-email">${this.escapeHtml(member.email || '')}</div>
                </div>
                <button class="btn-icon" onclick="App.removeTeamMember(${index})" title="Remove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/>
                        <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            `;
            teamList.appendChild(memberEl);
        });
    },
    
    addTeamMember() {
        const nameInput = document.getElementById('new-member-name');
        const emailInput = document.getElementById('new-member-email');
        
        const name = nameInput.value.trim();
        const email = emailInput.value.trim();
        
        if (!name) {
            this.showToast('warning', 'Name required', 'Please enter a name');
            return;
        }
        
        State.settings = this.normalizeWorkspaceSettings(State.settings);
        
        State.settings.team_members.push({ name, email });
        
        this.renderTeamMembers(State.settings.team_members);
        
        nameInput.value = '';
        emailInput.value = '';
    },
    
    removeTeamMember(index) {
        if (State.settings?.team_members) {
            State.settings.team_members.splice(index, 1);
            this.renderTeamMembers(State.settings.team_members);
        }
    },
    
    async saveSettings() {
        // Collect settings from UI
        const settings = this.normalizeWorkspaceSettings({
            profile_name: document.getElementById('user-profile-name').value.trim(),
            profile_email: document.getElementById('user-profile-email').value.trim(),
            default_language: document.getElementById('default-language').value,
            speaker_diarization: document.getElementById('speaker-diarization').checked,
            team_members: State.settings?.team_members || []
        });
        
        // Update State.user if profile changed
        if (settings.profile_name) {
            State.user = State.user || {};
            State.user.name = settings.profile_name;
            State.user.email = settings.profile_email;
        }
        
        if (State.user?.isGuest) {
            localStorage.setItem('mm_guest_settings', JSON.stringify(settings));
            // Also save profile separately for guest users
            localStorage.setItem('mm_guest_profile', JSON.stringify({
                name: settings.profile_name,
                email: settings.profile_email
            }));
            State.settings = settings;
            this.closeSettings();
            this.showToast('success', 'Settings saved', 'Your settings have been saved locally');
            return;
        }
        
        this.showLoading('Saving settings...');
        
        try {
            const res = await this.authFetch(`${CONFIG.API_BASE}/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            
            if (!res.ok) throw new Error('Save failed');
            
            State.settings = settings;
            
            this.hideLoading();
            this.closeSettings();
            this.showToast('success', 'Settings saved', 'Your settings have been updated');
            
        } catch (error) {
            this.hideLoading();
            this.showToast('error', 'Save failed', error.message);
        }
    },
    
    // -------------------------------------------------------------------------
    // Utilities
    // -------------------------------------------------------------------------
    
    async authFetch(url, options = {}) {
        const headers = {
            ...options.headers
        };
        
        if (State.token) {
            headers['Authorization'] = `Bearer ${State.token}`;
        }
        
        let response = await fetch(url, { ...options, headers });

        // On 401, attempt token refresh before giving up
        if (response.status === 401) {
            const refreshJwt = localStorage.getItem('mm_refresh_token');
            if (refreshJwt) {
                try {
                    const refreshRes = await fetch(`${CONFIG.API_BASE}/auth/refresh`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ refreshJwt })
                    });
                    if (refreshRes.ok) {
                        const data = await refreshRes.json();
                        if (data.sessionJwt) {
                            State.token = data.sessionJwt;
                            localStorage.setItem('mm_token', data.sessionJwt);
                            headers['Authorization'] = `Bearer ${data.sessionJwt}`;
                            // Retry the original request with new token
                            response = await fetch(url, { ...options, headers });
                        }
                    }
                } catch (e) {
                    console.warn('Token refresh failed:', e);
                }
            }
        }

        return response;
    },
    
    getLoadingElements() {
        const overlay = document.getElementById('loading-overlay');
        if (!overlay) {
            return {};
        }

        return {
            overlay,
            loader: overlay.querySelector('.loader'),
            eyebrow: document.getElementById('loading-eyebrow'),
            title: document.getElementById('loading-title'),
            text: document.getElementById('loading-text'),
            shell: document.getElementById('loading-progress-shell'),
            fill: document.getElementById('loading-progress-fill'),
            label: document.getElementById('loading-progress-label'),
            value: document.getElementById('loading-progress-value'),
            stageList: document.getElementById('loading-stage-list'),
            words: document.getElementById('loading-floating-words')
        };
    },

    clearLoadingTimers() {
        if (State.loadingProgressTimer) {
            clearInterval(State.loadingProgressTimer);
            State.loadingProgressTimer = null;
        }

        if (State.loadingWordTimer) {
            clearInterval(State.loadingWordTimer);
            State.loadingWordTimer = null;
        }
    },

    renderLoadingStages(stages = []) {
        const { stageList } = this.getLoadingElements();
        if (!stageList) {
            return;
        }

        if (!stages.length) {
            stageList.innerHTML = '';
            return;
        }

        stageList.innerHTML = stages.map((stage) => `
            <div class="loading-stage is-pending" data-stage-key="${this.escapeHtml(stage.key)}">
                <span class="loading-stage-dot"></span>
                <span>${this.escapeHtml(stage.label)}</span>
            </div>
        `).join('');
    },

    showProgressFlow(flowKey = 'basic', options = {}) {
        const elements = this.getLoadingElements();
        if (!elements.overlay) {
            return;
        }

        this.clearLoadingTimers();

        const preset = LOADING_FLOW_PRESETS[flowKey] || LOADING_FLOW_PRESETS.basic;
        State.loadingFlow = {
            key: flowKey,
            config: preset,
            progress: 0,
            stageKey: null
        };

        if (elements.loader) {
            elements.loader.classList.remove('hidden');
        }
        if (elements.eyebrow) {
            elements.eyebrow.textContent = options.eyebrow || preset.eyebrow || LOADING_FLOW_PRESETS.basic.eyebrow;
        }
        if (elements.title) {
            elements.title.textContent = options.title || preset.title || LOADING_FLOW_PRESETS.basic.title;
        }
        if (elements.text) {
            elements.text.textContent = options.message || preset.message || LOADING_FLOW_PRESETS.basic.message;
        }
        if (elements.shell) {
            elements.shell.classList.toggle('hidden', !(preset.stages || []).length);
        }

        this.renderLoadingStages(preset.stages || []);
        elements.overlay.classList.remove('hidden');

        if (elements.words) {
            const words = preset.words || [];
            if (words.length) {
                let wordIndex = 0;
                elements.words.textContent = words[wordIndex];
                elements.words.classList.remove('hidden');

                State.loadingWordTimer = setInterval(() => {
                    wordIndex = (wordIndex + 1) % words.length;
                    elements.words.textContent = words[wordIndex];
                }, 1600);
            } else {
                elements.words.textContent = '';
                elements.words.classList.add('hidden');
            }
        }

        const initialProgress = typeof options.progress === 'number'
            ? options.progress
            : (typeof preset.minProgress === 'number' ? preset.minProgress : 0);
        const initialStageKey = options.stageKey || preset.stages?.[0]?.key || null;

        this.updateLoadingProgress({
            progress: initialProgress,
            stageKey: initialStageKey,
            message: options.message || preset.message
        });

        if (preset.simulated) {
            State.loadingProgressTimer = setInterval(() => {
                const activeFlow = State.loadingFlow;
                if (!activeFlow || activeFlow.key !== flowKey) {
                    return;
                }

                const maxProgress = typeof preset.maxProgress === 'number' ? preset.maxProgress : 90;
                if (activeFlow.progress >= maxProgress) {
                    return;
                }

                const increment = activeFlow.progress < 50 ? 3 : 1;
                this.updateLoadingProgress({
                    progress: Math.min(maxProgress, activeFlow.progress + increment)
                });
            }, 900);
        }
    },

    updateLoadingProgress({ progress, stageKey, message } = {}) {
        const elements = this.getLoadingElements();
        if (!elements.overlay) {
            return;
        }

        const activeFlow = State.loadingFlow || {
            key: 'basic',
            config: LOADING_FLOW_PRESETS.basic,
            progress: 0,
            stageKey: null
        };
        State.loadingFlow = activeFlow;

        if (typeof progress === 'number' && Number.isFinite(progress)) {
            // Progress is monotonic — never let a stale backend poll or a
            // smaller simulated tick drag the bar backwards. The exception
            // is when a brand-new flow starts (no prior progress) or when
            // the caller explicitly resets to 0 to reuse the overlay.
            const nextValue = Math.max(0, Math.min(100, Math.round(progress)));
            const prevValue = typeof activeFlow.progress === 'number' ? activeFlow.progress : 0;
            activeFlow.progress = nextValue === 0 ? 0 : Math.max(prevValue, nextValue);
        }
        if (stageKey) {
            activeFlow.stageKey = stageKey;
        }
        if (message && elements.text) {
            elements.text.textContent = message;
        }

        const stages = activeFlow.config.stages || [];
        const activeStage = stages.find((stage) => stage.key === activeFlow.stageKey) || stages[0] || null;
        const activeIndex = activeStage ? stages.findIndex((stage) => stage.key === activeStage.key) : -1;

        if (elements.shell) {
            elements.shell.classList.toggle('hidden', !stages.length);
        }
        if (elements.fill) {
            elements.fill.style.width = `${activeFlow.progress}%`;
        }
        if (elements.value) {
            elements.value.textContent = `${activeFlow.progress}%`;
        }
        if (elements.label) {
            elements.label.textContent = activeStage?.label || 'Working';
        }

        if (elements.stageList) {
            const stageNodes = elements.stageList.querySelectorAll('.loading-stage');
            stageNodes.forEach((node, index) => {
                const nodeKey = node.dataset.stageKey || '';
                const isComplete = activeFlow.progress >= 100 || (activeIndex >= 0 && index < activeIndex);
                const isActive = activeFlow.progress < 100 && (
                    nodeKey === activeFlow.stageKey ||
                    (!activeFlow.stageKey && index === 0) ||
                    (!nodeKey && index === activeIndex)
                );

                node.classList.toggle('is-complete', isComplete);
                node.classList.toggle('is-active', isActive);
                node.classList.toggle('is-pending', !isComplete && !isActive);
            });
        }

        if (activeFlow.progress >= 100 || activeFlow.stageKey === 'completed') {
            this.clearLoadingTimers();
        }
    },

    showLoading(message = 'Loading...') {
        const elements = this.getLoadingElements();
        if (!elements.overlay) {
            return;
        }

        this.clearLoadingTimers();
        State.loadingFlow = null;

        if (elements.loader) {
            elements.loader.classList.remove('hidden');
        }
        if (elements.eyebrow) {
            elements.eyebrow.textContent = LOADING_FLOW_PRESETS.basic.eyebrow;
        }
        if (elements.title) {
            elements.title.textContent = LOADING_FLOW_PRESETS.basic.title;
        }
        if (elements.text) {
            elements.text.textContent = message;
        }
        if (elements.shell) {
            elements.shell.classList.add('hidden');
        }
        if (elements.fill) {
            elements.fill.style.width = '0%';
        }
        if (elements.label) {
            elements.label.textContent = 'Starting';
        }
        if (elements.value) {
            elements.value.textContent = '0%';
        }
        if (elements.stageList) {
            elements.stageList.innerHTML = '';
        }
        if (elements.words) {
            elements.words.textContent = '';
            elements.words.classList.add('hidden');
        }

        elements.overlay.classList.remove('hidden');
    },
    
    hideLoading() {
        const elements = this.getLoadingElements();
        if (!elements.overlay) {
            return;
        }

        this.clearLoadingTimers();
        State.loadingFlow = null;

        if (elements.shell) {
            elements.shell.classList.add('hidden');
        }
        if (elements.fill) {
            elements.fill.style.width = '0%';
        }
        if (elements.label) {
            elements.label.textContent = 'Starting';
        }
        if (elements.value) {
            elements.value.textContent = '0%';
        }
        if (elements.stageList) {
            elements.stageList.innerHTML = '';
        }
        if (elements.words) {
            elements.words.textContent = '';
            elements.words.classList.add('hidden');
        }

        elements.overlay.classList.add('hidden');
    },
    
    showToast(type, title, message) {
        const container = document.getElementById('toast-container');
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };
        
        toast.innerHTML = `
            <div class="toast-icon">${icons[type]}</div>
            <div class="toast-content">
                <div class="toast-title">${this.escapeHtml(title)}</div>
                <div class="toast-message">${this.escapeHtml(message)}</div>
            </div>
        `;
        
        container.appendChild(toast);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    },
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// =============================================================================
// Initialize on DOM ready
// =============================================================================

document.addEventListener('DOMContentLoaded', () => App.init());

// Register Service Worker for PWA
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('Service Worker registered'))
            .catch(err => console.log('Service Worker registration failed:', err));
    });
}
