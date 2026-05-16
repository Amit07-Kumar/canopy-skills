"""
Meeting Master - AI Processing Service

Handles all AI-related operations:
- Transcription (Sarvam AI, Groq Whisper, Deepgram)
- Translation (LLM)
- Task extraction (LLM)
- Calendar event generation (LLM)
- MoM composition (LLM)

Uses the unified AI Model Calling Library from /root/repo/ai-model-calling/
"""

import logging
import json
import os
import sys
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import httpx

# Add AI library to path (two possible locations: host dev and container)
for lib_path in ['/app/lib/ai-model-calling', '/root/repo/ai-model-calling']:
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

try:
    from ai_client import AIClient, AIConfig, AIProvider as AIClientProvider
    AI_LIBRARY_AVAILABLE = True
except ImportError:
    AI_LIBRARY_AVAILABLE = False

# Import STT library (same path)
try:
    from stt_client import STTClient, STTConfig, STTResult
    STT_LIBRARY_AVAILABLE = True
except ImportError:
    STT_LIBRARY_AVAILABLE = False

# Use relative imports when running as a package
try:
    from ..config import (
        OPENROUTER_API_KEY,
        OPENROUTER_BASE_URL,
        OPENROUTER_MODEL,
        DEEPGRAM_API_KEY,
        GROQ_API_KEY,
        SARVAM_API_KEY,
        DEFAULT_STT_PROVIDER,
    )
    from ..models import (
        AIProcessingResult,
        Attendee,
        Task,
        CalendarEvent,
        MailContent,
        TaskPriority,
        TaskCategory,
        CalendarEventType,
        ModelProvider,
    )
except ImportError:
    from config import (
        OPENROUTER_API_KEY,
        OPENROUTER_BASE_URL,
        OPENROUTER_MODEL,
        DEEPGRAM_API_KEY,
        GROQ_API_KEY,
        SARVAM_API_KEY,
        DEFAULT_STT_PROVIDER,
    )
    from models import (
        AIProcessingResult,
        Attendee,
        Task,
        CalendarEvent,
        MailContent,
        TaskPriority,
        TaskCategory,
        CalendarEventType,
        ModelProvider,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# AI Prompt Templates
# =============================================================================

SYSTEM_PROMPT = """You are Meeting Master AI, an expert meeting assistant specializing in:
- Accurate transcription of multilingual meetings (English, Hindi, Hinglish)
- Professional speaker identification and attribution
- Intelligent task extraction with realistic deadlines
- Calendar event generation from meeting context
- Professional Minutes of Meeting (MoM) composition

Your outputs must be:
1. STRUCTURED: Always return valid JSON matching the specified schema
2. ACTIONABLE: Tasks must have clear owners and deadlines
3. CONTEXTUAL: Infer deadlines from project context when not explicit
4. PROFESSIONAL: MoM should be formal yet readable
5. MULTILINGUAL: Support Hindi, English, and code-mixed Hinglish

CRITICAL: Return ONLY valid JSON, no markdown, no extra text."""


PROCESSING_PROMPT_TEMPLATE = """Process this meeting transcription and extract all information.

MEETING CONTEXT:
- Recording date: {date} (IMPORTANT: Use this as "TODAY" for all relative calculations like 'tomorrow', 'Friday', etc.)
- Duration: {duration}
- Uploader: {uploader}
- Known team members: {team_members}

RAW TRANSCRIPTION:
{transcription}

INSTRUCTIONS:
1. Clean up the transcription, identify speakers
2. Translate to English, Hindi (Devanagari), and Hinglish (English script)
3. Identify attendees from the conversation
4. Extract ALL tasks with intelligent deadline assignment:
   - Explicit deadline: Use mentioned date
   - "ASAP/urgent": Within 2 days
   - "end of week/sprint": Friday/sprint end
   - Default: Estimate based on complexity (simple: 3 days, medium: 1 week, complex: 2 weeks)
5. Generate calendar events for:
   - Mentioned future meetings
   - Task deadlines as reminders
6. Compose professional MoM email

Return a single JSON object with this EXACT structure:
{{
  "transcript_en": "Full meeting in clean English with speaker labels [Name]: ...",
  "transcript_hi": "पूरी मीटिंग हिंदी में speaker labels के साथ [नाम]: ...",
  "transcript_hinglish": "Poori meeting Hinglish mein English script mein [Name]: ...",
  "attendees": [
    {{
      "speaker_id": "SPEAKER_1",
      "name": "Paras or null if unknown",
      "email": "email@example.com or null",
      "identified": true/false,
      "hint": "How you identified this person"
    }}
  ],
  "tasks": [
    {{
      "id": "TASK_001",
      "title": "Short task title",
      "description": "Detailed description",
      "assignee": "Person name or ALL",
      "deadline": "YYYY-MM-DD",
      "deadline_source": "explicit/inferred - explanation",
      "priority": "LOW/MEDIUM/HIGH/CRITICAL",
      "category": "BUG/FEATURE/DOCUMENTATION/MEETING/OTHER",
      "dependencies": [],
      "context": "Where in meeting this was discussed"
    }}
  ],
  "calendar_events": [
    {{
      "id": "CAL_001",
      "title": "Event title",
      "description": "Event description",
      "start_datetime": "YYYY-MM-DDTHH:MM:SS",
      "end_datetime": "YYYY-MM-DDTHH:MM:SS",
      "attendees": ["email1@example.com"],
      "source": "explicit/inferred - explanation",
      "type": "MEETING/REMINDER/DEADLINE"
    }}
  ],
  "mail": {{
    "subject": "MoM: Meeting Title - Date",
    "to": ["attendee@example.com"],
    "cc": [],
    "body": "Full professional MoM email with markdown formatting"
  }},
  "summary": "2-3 sentence meeting summary",
  "tags": ["tag1", "tag2"],
  "sentiment": "positive/neutral/negative",
  "confidence": 0.85
}}

EXAMPLES OF DEADLINE INFERENCE:
- "Let's finish this by Friday" → deadline = next Friday
- "Can you do this urgently?" → deadline = today + 2 days
- "Before the client meeting next week" → deadline = day before client meeting
- "This sprint" → deadline = sprint end date (or Friday if unknown)
- No deadline mentioned, simple task → deadline = today + 3 days
- No deadline mentioned, complex task → deadline = today + 7-14 days

Return ONLY the JSON object, no other text."""


# =============================================================================
# AI Service Class
# =============================================================================

class AIService:
    """Service for AI-powered meeting processing
    
    Uses the unified AI Model Calling Library for all LLM operations.
    Supports multiple providers: OpenRouter, OpenAI, Gemini, Groq
    """
    
    def __init__(
        self,
        provider: ModelProvider = ModelProvider.OPENROUTER,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.provider = provider
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
        self.model = model or os.getenv("AI_MODEL", OPENROUTER_MODEL)
        
        # Initialize AI client if library is available
        if AI_LIBRARY_AVAILABLE and self.api_key:
            self._init_ai_client()
        else:
            self.ai_client = None
            logger.warning("AI library not available or no API key, using fallback")
    
    def _init_ai_client(self):
        """Initialize the AI client based on provider"""
        provider_map = {
            ModelProvider.OPENROUTER: "openrouter",
            ModelProvider.OPENAI: "openai",
            ModelProvider.GEMINI: "gemini",
            ModelProvider.GROQ: "groq",
        }
        
        provider_str = provider_map.get(self.provider, "openrouter")
        
        config = AIConfig(
            provider=provider_str,
            api_key=self.api_key,
            model=self.model,
            temperature=0.3,
            max_tokens=8000,
            timeout=120,
            extra_headers={
                "HTTP-Referer": "https://meeting.lehana.in",
                "X-Title": "Meeting Master"
            }
        )
        self.ai_client = AIClient(config)
        logger.info(f"AI client initialized: provider={provider_str}, model={self.model}")
    
    async def transcribe_audio(self, audio_path: str, language: str = "hi") -> Dict[str, Any]:
        """Transcribe audio file using the STT library
        
        Supports multiple providers via /root/repo/ai-model-calling/stt_client.py:
        - Sarvam AI (best for Hindi/Indian languages) - FREE
        - Groq Whisper (good for multilingual) - FREE
        - Deepgram (premium quality)
        - OpenAI Whisper
        
        Args:
            audio_path: Path to audio file
            language: Language code (hi=Hindi, en=English, auto=auto-detect)
            
        Returns:
            Dict with raw_text, language_detected, confidence, duration_seconds, provider
        """
        
        # Try using STT library first (best approach)
        if STT_LIBRARY_AVAILABLE:
            return await self._transcribe_with_stt_library(audio_path, language)
        
        # Fall back to legacy implementations
        logger.warning("STT library not available, using legacy transcription methods")
        
        deepgram_key = os.getenv("DEEPGRAM_API_KEY", DEEPGRAM_API_KEY)
        
        if deepgram_key and deepgram_key != "CONFIGURE_ME" and len(deepgram_key) > 20:
            return await self._transcribe_with_deepgram_legacy(audio_path)
        
        return await self._transcribe_with_groq(audio_path)
    
    async def _transcribe_with_stt_library(self, audio_path: str, language: str = "hi") -> Dict[str, Any]:
        """Transcribe using the unified STT library
        
        Provider priority:
        1. Sarvam AI (if SARVAM_API_KEY is set and language is Indian)
        2. Groq Whisper (if GROQ_API_KEY is set)
        3. Deepgram (if DEEPGRAM_API_KEY is set)
        4. Explicit configuration error when no provider is available
        """
        import asyncio
        
        # Get API keys from environment
        sarvam_key = os.getenv("SARVAM_API_KEY", SARVAM_API_KEY)
        groq_key = os.getenv("GROQ_API_KEY", GROQ_API_KEY)
        deepgram_key = os.getenv("DEEPGRAM_API_KEY", DEEPGRAM_API_KEY)
        default_provider = os.getenv("DEFAULT_STT_PROVIDER", DEFAULT_STT_PROVIDER)
        
        # Determine best provider
        selected_provider = None
        selected_key = None
        
        # Indian languages → prefer Sarvam
        indian_languages = ["hi", "hi-IN", "ta", "te", "kn", "ml", "mr", "gu", "bn", "pa", "or"]
        is_indian_language = language.lower() in indian_languages or language.lower().startswith("hi")
        
        # Check provider availability
        if default_provider == "sarvam" and sarvam_key and len(sarvam_key) > 10:
            selected_provider = "sarvam"
            selected_key = sarvam_key
        elif is_indian_language and sarvam_key and len(sarvam_key) > 10:
            selected_provider = "sarvam"
            selected_key = sarvam_key
        elif groq_key and len(groq_key) > 10:
            selected_provider = "groq"
            selected_key = groq_key
        elif deepgram_key and deepgram_key != "CONFIGURE_ME" and len(deepgram_key) > 20:
            selected_provider = "deepgram"
            selected_key = deepgram_key
        
        if not selected_provider:
            message = "No STT provider configured. Set SARVAM_API_KEY, GROQ_API_KEY, or DEEPGRAM_API_KEY before transcribing audio."
            logger.error(message)
            raise RuntimeError(message)
        
        logger.info(f"Using STT provider: {selected_provider} (language={language})")
        
        try:
            # Create STT config
            config = STTConfig.for_provider(
                provider=selected_provider,
                api_key=selected_key,
                language=language
            )
            
            # Create client and transcribe (sync call in async context)
            client = STTClient(config)
            
            # Run sync transcription in thread pool to not block
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: client.transcribe(audio_path, language=language)
            )
            
            logger.info(f"STT transcription complete: {len(result.text)} chars, {result.response_time_ms:.0f}ms")
            
            return {
                "raw_text": result.text,
                "language_detected": result.language,
                "confidence": result.confidence or 0.95,
                "duration_seconds": result.duration_seconds or 0,
                "provider": result.provider,
                "model": result.model
            }
            
        except Exception as e:
            logger.error(f"STT library transcription failed: {e}")
            raise RuntimeError(f"Speech-to-text transcription failed: {e}") from e
    
    async def _transcribe_with_deepgram_legacy(self, audio_path: str) -> Dict[str, Any]:
        """Legacy Deepgram transcription (kept for backward compatibility)"""
        deepgram_key = os.getenv("DEEPGRAM_API_KEY", DEEPGRAM_API_KEY)
        
        # Read audio file
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        
        # Call Deepgram API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                params={
                    "model": "nova-2",
                    "smart_format": "true",
                    "diarize": "true",
                    "punctuate": "true",
                    "language": "en-IN"  # Indian English with Hindi mixing
                },
                headers={
                    "Authorization": f"Token {deepgram_key}",
                    "Content-Type": "audio/webm"  # Adjust based on format
                },
                content=audio_data,
                timeout=120.0
            )
        
        if response.status_code != 200:
            logger.error(f"Deepgram error: {response.text}")
            raise Exception(f"Transcription failed: {response.status_code}")
        
        result = response.json()
        
        # Extract transcript with speaker diarization
        transcript_parts = []
        current_speaker = None
        
        if "results" in result and result["results"]["channels"]:
            for word in result["results"]["channels"][0]["alternatives"][0].get("words", []):
                speaker = word.get("speaker", 0)
                if speaker != current_speaker:
                    current_speaker = speaker
                    transcript_parts.append(f"\n[SPEAKER_{speaker}]: ")
                transcript_parts.append(word["word"] + " ")
        
        transcript = "".join(transcript_parts).strip()
        
        if not transcript:
            # Fallback to simple transcript
            transcript = result["results"]["channels"][0]["alternatives"][0].get("transcript", "")
        
        return {
            "raw_text": transcript,
            "language_detected": result.get("results", {}).get("channels", [{}])[0].get("detected_language", "en"),
            "confidence": result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("confidence", 0.0),
            "duration_seconds": result.get("metadata", {}).get("duration", 0)
        }
    
    async def process_transcript(
        self,
        transcript: str,
        meeting_date: datetime,
        duration_seconds: Optional[int] = None,
        uploader_name: str = "User",
        team_members: List[Dict[str, str]] = None
    ) -> AIProcessingResult:
        """Process transcript with LLM to extract all information"""
        
        team_members = team_members or []
        team_str = json.dumps(team_members) if team_members else "[]"
        
        duration_str = f"{duration_seconds // 60} minutes" if duration_seconds else "Unknown"
        
        prompt = PROCESSING_PROMPT_TEMPLATE.format(
            date=meeting_date.strftime("%Y-%m-%d %H:%M"),
            duration=duration_str,
            uploader=uploader_name,
            team_members=team_str,
            transcription=transcript
        )
        
        # Call LLM
        response = await self._call_llm(prompt)
        
        # Parse response
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            logger.error(f"Response was: {response[:500]}...")
            # Try to extract JSON from response
            data = self._extract_json(response)
        
        # Convert to structured models
        attendees = [
            Attendee(
                speaker_id=a.get("speaker_id", f"SPEAKER_{i}"),
                name=a.get("name"),
                email=a.get("email"),
                identified=a.get("identified", False),
                hint=a.get("hint")
            )
            for i, a in enumerate(data.get("attendees", []))
        ]
        
        tasks = [
            Task(
                id=t.get("id", f"TASK_{i+1:03d}"),
                title=t.get("title", "Untitled Task"),
                description=t.get("description"),
                assignee=t.get("assignee"),
                due_date=self._parse_date(t.get("deadline") or t.get("due_date")),
                deadline_source=t.get("deadline_source"),
                priority=TaskPriority(t.get("priority", "MEDIUM")),
                category=TaskCategory(t.get("category", "OTHER")),
                dependencies=t.get("dependencies", []),
                context=t.get("context")
            )
            for i, t in enumerate(data.get("tasks", []))
        ]
        
        calendar_events = [
            CalendarEvent(
                id=e.get("id", f"CAL_{i+1:03d}"),
                title=e.get("title", "Untitled Event"),
                description=e.get("description"),
                start_datetime=self._parse_datetime(e.get("start_datetime")),
                end_datetime=self._parse_datetime(e.get("end_datetime")),
                attendees=e.get("attendees", []),
                source=e.get("source"),
                type=CalendarEventType(e.get("type", "MEETING"))
            )
            for i, e in enumerate(data.get("calendar_events", []))
        ]
        
        mail_data = data.get("mail", {})
        mail = MailContent(
            subject=mail_data.get("subject", f"MoM: Meeting - {meeting_date.strftime('%Y-%m-%d')}"),
            to=mail_data.get("to", []),
            cc=mail_data.get("cc", []),
            body=mail_data.get("body", "Meeting notes attached.")
        )
        
        return AIProcessingResult(
            transcript_en=data.get("transcript_en") or data.get("transcribe") or transcript,
            transcript_hi=data.get("transcript_hi") or data.get("transcribe_hi", ""),
            transcript_hinglish=data.get("transcript_hinglish") or data.get("transcribe_eh", ""),
            attendees=attendees,
            tasks=tasks,
            calendar_events=calendar_events,
            mail=mail,
            summary=data.get("summary", "Meeting summary not available."),
            tags=data.get("tags", []),
            sentiment=data.get("sentiment", "neutral"),
            confidence=data.get("confidence", 0.7)
        )
    
    async def _call_llm(self, prompt: str) -> str:
        """Call LLM API using the unified AI library"""
        
        # Use AI library if available
        if self.ai_client:
            try:
                # Use async method
                response = await self.ai_client.achat(
                    prompt,
                    system_prompt=SYSTEM_PROMPT
                )
                return response
            except Exception as e:
                logger.error(f"AI library call failed: {e}, falling back to direct call")
        
        # Fallback to direct API calls
        if self.provider == ModelProvider.OPENROUTER:
            return await self._call_openrouter(prompt)
        elif self.provider == ModelProvider.OPENAI:
            return await self._call_openai(prompt)
        elif self.provider == ModelProvider.GEMINI:
            return await self._call_gemini(prompt)
        elif self.provider == ModelProvider.GROQ:
            return await self._call_groq(prompt)
        else:
            return await self._call_openrouter(prompt)
    
    async def _call_openrouter(self, prompt: str) -> str:
        """Call OpenRouter API"""
        # Models that don't support system prompts (merge system into user message)
        no_system_models = ["gemma", "gemini"]
        use_system_prompt = not any(m in self.model.lower() for m in no_system_models)
        
        if use_system_prompt:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        else:
            # Merge system prompt into user message
            messages = [
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n---\n\n{prompt}"}
            ]
            logger.info(f"Model {self.model} doesn't support system prompts, merging into user message")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "https://meeting.lehana.in",
                    "X-Title": "Meeting Master"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 8000
                },
                timeout=120.0
            )
        
        result = response.json()
        
        if response.status_code != 200:
            error_msg = result.get("error", {}).get("message", response.text)
            logger.error(f"OpenRouter error ({response.status_code}): {error_msg}")
            raise Exception(f"LLM call failed: {response.status_code} - {error_msg}")
        
        if "choices" not in result:
            logger.error(f"OpenRouter response missing 'choices': {result}")
            raise Exception(f"Invalid API response: {result}")
        
        # Handle both standard 'content' and DeepSeek's 'reasoning' format
        message = result["choices"][0]["message"]
        content = message.get("content") or message.get("reasoning", "")
        
        if not content:
            logger.warning(f"Empty response from model. Full message: {message}")
            raise Exception("Model returned empty response")
        
        return content
    
    async def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": "gpt-4-turbo-preview",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 8000
                },
                timeout=120.0
            )
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    async def _call_gemini(self, prompt: str) -> str:
        """Call Google Gemini API"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent",
                params={"key": self.api_key},
                json={
                    "contents": [
                        {"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}]}
                    ],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 8000
                    }
                },
                timeout=120.0
            )
        
        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]
    
    async def _call_groq(self, prompt: str) -> str:
        """Call Groq API"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": "llama-3.1-70b-versatile",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 8000
                },
                timeout=120.0
            )
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from text that may contain other content"""
        # Try to find JSON block
        import re
        
        # Look for JSON in code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Look for JSON object
        brace_start = text.find('{')
        if brace_start != -1:
            # Find matching closing brace
            depth = 0
            for i, char in enumerate(text[brace_start:], start=brace_start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start:i+1])
                        except json.JSONDecodeError:
                            pass
                        break
        
        # Return minimal structure
        return {
            "transcribe": text,
            "transcribe_hi": "",
            "transcribe_eh": "",
            "attendees": [],
            "tasks": [],
            "calendar_events": [],
            "mail": {"subject": "MoM", "to": [], "body": text},
            "summary": "Could not parse meeting.",
            "tags": [],
            "sentiment": "neutral",
            "confidence": 0.3
        }
    
    async def _transcribe_with_groq(self, audio_path: str) -> Dict[str, Any]:
        """Fallback transcription using Groq Whisper API
        
        Groq offers free Whisper-large-v3 with 25,000 audio seconds/month.
        Get free API key at https://console.groq.com/
        """
        groq_key = os.getenv("GROQ_API_KEY", "")
        
        if not groq_key or groq_key == "CONFIGURE_ME" or len(groq_key) < 10:
            message = "No STT provider configured. Set GROQ_API_KEY or configure the primary STT library providers before transcribing audio."
            logger.error(message)
            raise RuntimeError(message)
        
        logger.info(f"Using Groq Whisper for transcription (key: {groq_key[:8]}...)")
        
        # Read audio file
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        
        # Determine mime type from file extension
        import mimetypes
        mime_type = mimetypes.guess_type(audio_path)[0] or 'audio/mpeg'
        filename = os.path.basename(audio_path)
        
        try:
            async with httpx.AsyncClient() as client:
                # Groq uses OpenAI-compatible API for audio
                response = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                    },
                    files={
                        "file": (filename, audio_data, mime_type)
                    },
                    data={
                        "model": "whisper-large-v3",
                        "response_format": "verbose_json",
                        "language": "en"  # Auto-detect: remove this line if needed
                    },
                    timeout=120.0
                )
            
            logger.debug(f"Groq Whisper response code: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Groq Whisper error: {response.status_code} - {response.text[:500]}")
                raise Exception(f"Groq transcription failed: {response.status_code} - {response.text[:200]}")
            
            result = response.json()
            logger.info(f"Groq Whisper transcription complete: {len(result.get('text', ''))} chars")
            
            return {
                "raw_text": result.get("text", ""),
                "language_detected": result.get("language", "en"),
                "confidence": 0.95,
                "duration_seconds": result.get("duration", 0),
                "provider": "groq_whisper"
            }
            
        except Exception as e:
            logger.exception(f"Groq Whisper fallback failed: {e}")
            raise RuntimeError(f"Groq transcription failed: {e}") from e
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to date object"""
        if not date_str:
            return None
        try:
            # Try various formats
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
            return None
        except Exception:
            return None
    
    def _extract_json(self, text: str) -> dict:
        """Extract JSON from text that may contain markdown code blocks
        
        LLMs often return JSON wrapped in ```json ... ``` blocks.
        This method tries multiple strategies to extract valid JSON.
        """
        import re
        
        # Strategy 1: Try to extract from markdown code block
        json_pattern = r'```(?:json)?\s*([\s\S]*?)```'
        matches = re.findall(json_pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        
        # Strategy 2: Try to find JSON object pattern
        # Look for outermost { ... } structure
        brace_count = 0
        start_idx = None
        
        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx is not None:
                    json_str = text[start_idx:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        continue
        
        # Strategy 3: Try the raw text as is
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Strategy 4: Return minimal valid structure
        logger.error("Could not extract valid JSON from response, returning empty structure")
        return {
            "transcribe": text[:500] if text else "",
            "transcribe_hi": "",
            "transcribe_eh": "",
            "attendees": [],
            "tasks": [],
            "calendar_events": [],
            "mail": {
                "subject": "Meeting Notes",
                "to": [],
                "cc": [],
                "body": text[:1000] if text else "Unable to process transcript."
            },
            "summary": "Unable to process transcript due to parsing error.",
            "tags": [],
            "sentiment": "neutral",
            "confidence": 0.0
        }
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse datetime string to datetime object"""
        if not dt_str:
            return None
        try:
            # Try various formats
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"]:
                try:
                    return datetime.strptime(dt_str, fmt)
                except ValueError:
                    continue
            return None
        except Exception:
            return None


def get_ai_service(
    provider: ModelProvider = ModelProvider.OPENROUTER,
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> AIService:
    """Get AI service instance
    
    Args:
        provider: Model provider (openrouter, openai, gemini, groq)
        api_key: API key for the provider
        model: Specific model to use (e.g., "google/gemma-3-27b-it:free")
    """
    return AIService(provider=provider, api_key=api_key, model=model)
