# Meeting Master - Pitch Document

**One-tap meeting intelligence that turns conversations into action.**

---

## 🎯 The Problem

### The Meeting Productivity Crisis

Every day, **55 million meetings** happen worldwide. Yet:

- **71% of meetings are unproductive** (Harvard Business Review)
- **$37 billion** lost annually due to unproductive meetings (Atlassian)
- **91% of professionals** admit to daydreaming in meetings
- **73% of workers** do other work during meetings
- Average professional spends **31 hours monthly** in unproductive meetings

### The Real Pain Points

1. **Manual Note-Taking is Broken**
   - Attendees focus on typing, not participating
   - Critical decisions and action items get lost
   - Different people capture different (often conflicting) notes

2. **Follow-up Fails**
   - "Who was supposed to do that by when?"
   - Tasks fall through the cracks
   - Deadline ambiguity ("soon", "next week", "ASAP")

3. **Meeting Chaos**
   - No central record of what was discussed
   - Searching old meetings is impossible
   - New team members lack context

### India-Specific Challenges

- **Code-switching**: Teams frequently mix Hindi and English
- **Existing tools fail**: Otter.ai, Fireflies, etc. struggle with Indian accents and Hinglish
- **Cost barriers**: Enterprise tools are $15-30/user/month - prohibitive for Indian startups

---

## 💡 Our Solution: Meeting Master

**The AI meeting assistant built for real workplaces.**

### Core Value Proposition

> "Record your meeting with one tap. Get transcription, tasks, calendar events, and email summary - automatically."

### Key Differentiators

| Feature | Meeting Master | Otter.ai | Fireflies | Krisp |
|---------|---------------|----------|-----------|-------|
| **One-tap start** | ✅ | ❌ | ❌ | ✅ |
| **Hindi/Hinglish** | ✅ Native | ❌ | Limited | ❌ |
| **Smart deadline inference** | ✅ AI-powered | ❌ | ❌ | ❌ |
| **Editable outputs** | ✅ All fields | Limited | Limited | ❌ |
| **BYOK (Own API keys)** | ✅ | ❌ | ❌ | ❌ |
| **Free tier** | Generous | Limited | Limited | Limited |
| **Privacy-first** | ✅ | ❌ | ❌ | ✅ |

### The Magic: Smart Deadline Inference

**From this conversation:**
> "Let's have the report ready by Friday. And schedule a follow-up next Tuesday at 2 PM."

**We automatically generate:**

✅ **Task**: "Prepare report" → Due: Friday, Jan 31st  
📅 **Event**: "Follow-up meeting" → Tuesday, Feb 4th, 2:00 PM - 3:00 PM

No manual date entry. No ambiguity. AI handles the context.

---

## 🚀 Product Overview

### User Journey

```
1. RECORD        →  2. PROCESS       →  3. REVIEW & EDIT  →  4. EXECUTE
   One-tap           AI transcribes      Edit tasks/events     Sync to calendar
   recording         + analyzes          + email MoM           Send email MoM
```

### Feature Deep-Dive

#### 📝 Triple-Language Transcription
- **English**: Clean, formatted transcript
- **Hindi (Devanagari)**: Full Hindi translation
- **Hinglish (Roman)**: Transliterated for easy reading

#### ✅ Intelligent Task Extraction
- Auto-identifies action items from conversation
- Assigns to mentioned team members
- Infers deadlines from context ("next week" → actual date)
- Priority classification (High/Medium/Low)

#### 📅 Calendar Event Detection
- Recognizes scheduling discussions
- Creates complete calendar entries
- Includes attendees and descriptions
- One-click Google Calendar sync

#### ✉️ Professional MoM Generation
- Structured email template
- Key decisions highlighted
- Action items with owners
- Ready to send or edit

---

## 📊 Market Opportunity

### TAM/SAM/SOM

- **TAM**: $6.5B - Global meeting management software
- **SAM**: $1.2B - AI meeting assistants (transcription + insights)
- **SOM**: $120M - India + English-Hindi bilingual market

### Target Segments

1. **Primary**: Indian tech startups (5-100 employees)
2. **Secondary**: Remote-first global teams
3. **Tertiary**: Enterprise teams with offshore India units

### Competitive Landscape

**Why we win:**
- Existing players (Otter, Fireflies, Grain) are US-centric
- No good solution for Hindi/Hinglish speakers
- Our BYOK model appeals to privacy-conscious enterprises
- 3x lower price point for Indian market

---

## 💰 Business Model

### Freemium SaaS

| Tier | Price | Limits |
|------|-------|--------|
| **Free** | $0 | 5 meetings/month, 30 min each |
| **Pro** | $8/month | Unlimited meetings, 2 hours each |
| **Team** | $6/user/month | Shared workspace, integrations |
| **Enterprise** | Custom | SSO, on-prem, custom AI |

### Revenue Projections (Year 1-3)

- **Year 1**: $50K ARR (1,000 paying users)
- **Year 2**: $300K ARR (5,000 paying users)
- **Year 3**: $1.2M ARR (15,000 paying users)

---

## 🏗️ Technical Architecture

### Stack

- **Frontend**: HTML5/CSS3/JS (PWA-ready)
- **Backend**: FastAPI (Python)
- **Storage**: Local JSON-backed persistence
- **AI**: OpenRouter (Claude, GPT-4) + Deepgram STT
- **Infrastructure**: Docker + Traefik on Lehana.in

### AI Pipeline

```
Audio → Deepgram STT → LLM Processing → Structured Output
                           ↓
        [Transcription + Translation + Tasks + Calendar + Email]
```

### BYOK Architecture

Users can provide their own API keys for:
- OpenRouter (access all models)
- OpenAI (GPT-4, GPT-4o)
- Google Gemini
- Groq (Llama 3.1)

**Why BYOK?**
- Enterprise data privacy requirements
- Users pay AI costs directly (lower our margin pressure)
- Access to specialized models

---

## 🎯 Traction & Validation

### Current Status

- ✅ MVP deployed at meeting.lehana.in
- ✅ Core AI pipeline working
- ✅ Hindi/Hinglish transcription tested
- ✅ 5+ internal test meetings processed

### Early Feedback

> "Finally, a tool that understands when my team switches between Hindi and English mid-sentence!"
> — Startup founder, Bangalore

### Roadmap

**Q1 2026**: Public beta, Google Calendar integration  
**Q2 2026**: Slack/Teams integrations, mobile apps  
**Q3 2026**: Enterprise features, custom AI models  
**Q4 2026**: Series A readiness, 10K users target

---

## 👥 Team

**Paras Lehana** - Founder & Developer
- Full-stack engineer with 10+ years experience
- Built multiple production AI systems
- Deep expertise in Indian language AI

---

## 💵 Ask

### Seeking: $150K Pre-Seed

**Use of Funds:**
- 40% - Engineering (expand team)
- 30% - AI/Infrastructure costs
- 20% - Marketing & Growth
- 10% - Operations

### What We Offer

- Equity negotiable
- Advisors with AI/SaaS experience welcome
- Strategic partnerships in EdTech/Enterprise space

---

## 📞 Contact

- **Demo**: https://meeting.lehana.in
- **Email**: paras@lehana.in
- **LinkedIn**: linkedin.com/in/paraslehana

---

*"Every meeting is an opportunity. We make sure none are wasted."*
