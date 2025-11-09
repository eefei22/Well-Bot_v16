# Well-Bot CMS - Workflow Summary

## 📋 Project Overview

**Well-Bot CMS (Content Management System)** is a FastAPI-based service that processes user conversation messages from Supabase and generates two types of AI-powered summaries:
1. **Persona Facts** - Stable characteristics (communication style, interests, personality traits, values, concerns)
2. **Daily Life Context** - Experiential stories (routines, relationships, work life, daily activities)

Both summaries are extracted using DeepSeek's reasoning model (`deepseek-reasoner`) and stored in the database for use by the Well-Bot conversational AI system.

---

## 📁 Repository Structure

```
Well-Bot_CMS/
├── main.py                    # FastAPI application & endpoints
├── context_processor.py       # Daily life context extraction
├── facts_extractor.py         # Persona facts extraction
├── database.py                # Supabase connection & operations
├── llm.py                     # DeepSeek API client
├── schemas.py                 # Pydantic request/response models
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container configuration for Cloud Run
├── test_api.py               # API testing script
├── test_context_processor.py # Direct function testing
├── notes.txt                  # Development notes
└── venv/                      # Python virtual environment (local)
```

### Module Responsibilities

| File | Purpose |
|------|---------|
| `main.py` | FastAPI server, endpoint routing, request handling, error management |
| `context_processor.py` | Extracts daily life stories, routines, relationships, work context |
| `facts_extractor.py` | Extracts persona characteristics (traits, interests, communication style) |
| `database.py` | Supabase connection, message loading, context bundle persistence |
| `llm.py` | DeepSeek API client (supports streaming & non-streaming, reasoning models) |
| `schemas.py` | Pydantic request/response data models |

---

## ✅ Functional Requirements

### Core Features

1. **User Message Retrieval**
   - Load all user messages from Supabase database (`wb_conversation` and `wb_message` tables)
   - Filter by `user_id` and `role="user"` only
   - Group messages by conversation with metadata (conversation_id, timestamps)

2. **Message Preprocessing**
   - Filter short messages (< 4 words for space-separated languages, < 4 characters for CJK)
   - Normalize text (lowercase, strip whitespace, remove extra spaces)
   - Format messages as bullet-point list for LLM prompt consumption

3. **Persona Facts Extraction**
   - Extract communication style and patterns
   - Identify interests and preferences
   - Determine personality traits
   - Capture values and concerns
   - Note behavioral patterns
   - Output: Structured text summary saved to `facts` field

4. **Daily Life Context Extraction**
   - Extract daily routines and activities
   - Capture stories and experiences
   - Identify people and relationships
   - Extract work life context
   - Note life events and significant moments
   - Output: Structured text summary saved to `persona_summary` field

5. **Data Persistence**
   - Save facts to `users_context_bundle.facts` field
   - Save context to `users_context_bundle.persona_summary` field
   - Support partial updates (can update one or both fields independently)
   - Auto-update `version_ts` timestamp on each write

6. **RESTful API**
   - Process user context via POST endpoint
   - Return both summaries in response
   - Handle errors gracefully (400 for validation, 500 for server errors)
   - Provide health check endpoints (`/` and `/health`)

7. **Error Handling**
   - Facts extraction failure does not block context extraction
   - Context extraction failure returns error response
   - Both results saved independently to database
   - Comprehensive logging with timestamps

---

## 🔌 API Endpoints

### Base URL
- **Local Development**: `http://localhost:8000`
- **Production**: Configured via Google Cloud Run service URL

### Endpoints

#### 1. **GET /** - Root Endpoint
- **Purpose**: Health check / API status
- **Response**:
  ```json
  {
    "message": "Well-Bot CMS API is running"
  }
  ```
- **Status Code**: `200`

#### 2. **GET /health** - Health Check
- **Purpose**: Service health monitoring
- **Response**:
  ```json
  {
    "status": "healthy"
  }
  ```
- **Status Code**: `200`

#### 3. **POST /api/context/process** - Process User Context
- **Purpose**: Extract and save both persona facts and daily life context
- **Request Body**:
  ```json
  {
    "user_id": "8517c97f-66ef-4955-86ed-531013d33d3e"
  }
  ```
- **Response** (Success):
  ```json
  {
    "status": "success",
    "user_id": "8517c97f-66ef-4955-86ed-531013d33d3e",
    "facts": "• Communication style: [extracted facts]\n• Interests: [interests]\n...",
    "persona_summary": "• Daily routines: [routines]\n• Stories: [experiences]\n..."
  }
  ```
- **Response** (Error):
  ```json
  {
    "detail": "Error message here"
  }
  ```
- **Status Codes**:
  - `200`: Success
  - `400`: Bad Request (missing user_id, no messages found, validation errors)
  - `500`: Internal Server Error (LLM failure, database error, etc.)
- **Processing Time**: 2-6 minutes (both LLM extractions combined)
- **Error Handling**:
  - If facts extraction fails, context extraction still proceeds
  - If context extraction fails, request returns error
  - Both results saved independently to database

### Interactive API Documentation

FastAPI automatically generates interactive docs:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## 🔄 Data Flow

### Request Processing Flow

```
1. Client sends POST /api/context/process
   {
     "user_id": "uuid-here"
   }
   ↓
2. main.py receives request
   - Validates request schema (Pydantic)
   - Logs request start time
   ↓
3. facts_extractor.extract_user_facts(user_id)
   ├─→ database.load_user_messages(user_id)
   │   ├─→ Query wb_conversation table (filter by user_id)
   │   └─→ Query wb_message table (filter by role="user")
   │   └─→ Group messages by conversation
   ├─→ Extract message texts from conversation structure
   ├─→ Filter messages (< 4 words/chars)
   ├─→ Normalize messages (lowercase, whitespace cleanup)
   ├─→ Format messages for LLM prompt
   ├─→ Call DeepSeek API (persona facts prompt, timeout: 180s)
   └─→ database.write_users_context_bundle(user_id, facts=...)
       └─→ Upsert to users_context_bundle table
   ↓
4. context_processor.process_user_context(user_id)
   ├─→ database.load_user_messages(user_id) [same as above]
   ├─→ Extract message texts
   ├─→ Filter messages (< 4 words/chars)
   ├─→ Normalize messages
   ├─→ Format messages for LLM prompt
   ├─→ Call DeepSeek API (daily life context prompt, timeout: 180s)
   └─→ database.write_users_context_bundle(user_id, persona_summary=...)
       └─→ Upsert to users_context_bundle table
   ↓
5. Return response
   {
     "status": "success",
     "user_id": "uuid-here",
     "facts": "...",
     "persona_summary": "..."
   }
```

### Database Operations

**Read Operations**:
- `load_user_messages(user_id)`: 
  - Reads from `wb_conversation` table (filtered by `user_id`)
  - Reads from `wb_message` table (filtered by `conversation_id` and `role="user"`)
  - Returns structured conversation data with messages grouped by conversation

**Write Operations**:
- `write_users_context_bundle(user_id, persona_summary=None, facts=None)`:
  - Upserts to `users_context_bundle` table
  - First call: Saves `facts` field
  - Second call: Saves `persona_summary` field
  - Both updates same row (same `user_id` as primary key)
  - Auto-updates `version_ts` timestamp

### External API Calls

**DeepSeek API**:
- **Endpoint**: `https://api.deepseek.com/v1/chat/completions`
- **Model**: `deepseek-reasoner`
- **Timeout**: 180 seconds per request (3 minutes)
- **Total Processing**: 2 sequential calls (facts + context) = 2-6 minutes total

---

## 🚀 Deployment Summary

### Google Cloud Run Deployment

The service is containerized and deployed as a serverless service on Google Cloud Run.

#### Container Configuration

**Dockerfile**:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Key Details**:
- **Base Image**: `python:3.12-slim` (lightweight Python 3.12)
- **Port**: `8080` (Cloud Run default)
- **Server**: Uvicorn ASGI server
- **Host**: `0.0.0.0` (listens on all interfaces)

#### Deployment Steps

1. **Build Container Image**:
   ```bash
   gcloud builds submit --tag gcr.io/PROJECT_ID/well-bot-cms
   ```

2. **Deploy to Cloud Run**:
   ```bash
   gcloud run deploy well-bot-cms \
     --image gcr.io/PROJECT_ID/well-bot-cms \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --set-env-vars SUPABASE_URL=$SUPABASE_URL \
     --set-env-vars SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY \
     --set-env-vars DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY \
     --timeout 600 \
     --memory 2Gi \
     --cpu 2
   ```

#### Cloud Run Configuration

- **Platform**: Managed (fully serverless)
- **Region**: Configurable (e.g., `us-central1`)
- **Authentication**: Can be public or require authentication
- **Timeout**: 600 seconds (10 minutes) - sufficient for 2-6 minute processing
- **Memory**: 2Gi (recommended for LLM processing)
- **CPU**: 2 vCPU (recommended for concurrent processing)
- **Concurrency**: Default (80 requests per instance)
- **Min Instances**: 0 (scales to zero when idle)
- **Max Instances**: Configurable based on load

#### Environment Variables

Set via Cloud Run service configuration:
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key (admin access)
- `DEEPSEEK_API_KEY`: DeepSeek API key for LLM access

#### Service Characteristics

- **Auto-scaling**: Automatically scales based on request volume
- **Cold Start**: ~5-10 seconds (container initialization)
- **Warm Instances**: Faster response times for subsequent requests
- **Request Timeout**: 600 seconds (10 minutes) - handles long-running LLM calls
- **Health Checks**: `/health` endpoint for monitoring
- **Logging**: Integrated with Google Cloud Logging
- **Monitoring**: Available via Google Cloud Monitoring

#### Access & URLs

- **Service URL**: `https://well-bot-cms-XXXXX.run.app` (auto-generated)
- **Custom Domain**: Can be configured via Cloud Run domain mapping
- **API Documentation**: Available at `https://SERVICE_URL/docs`

---

## 📦 Dependencies

### Python Packages

```python
# Web Framework & Server
fastapi==0.109.0              # REST API framework
uvicorn[standard]==0.27.0     # ASGI server

# Database
supabase>=2.4.0               # Supabase Python client
httpx[http2]>=0.26,<0.28      # HTTP client (pinned for compatibility)

# Data Validation
pydantic>=2.10.0              # Data validation
pydantic-settings==2.1.0       # Settings management

# Environment & Configuration
python-dotenv==1.0.0           # .env file support

# Testing
requests==2.31.0               # HTTP client for testing
```

### External Services

1. **Supabase** (PostgreSQL Database)
   - Tables: `wb_conversation`, `wb_message`, `users_context_bundle`
   - Authentication: Service role key for admin operations

2. **DeepSeek API**
   - Model: `deepseek-reasoner` (reasoning model)
   - Endpoint: `https://api.deepseek.com/v1/chat/completions`
   - Timeout: 180 seconds per request

---

## 🗄️ Database Schema

### Table: `users_context_bundle`

```sql
CREATE TABLE public.users_context_bundle (
  user_id uuid NOT NULL PRIMARY KEY,
  version_ts timestamp with time zone NOT NULL DEFAULT now(),
  persona_summary text,           -- Daily life context (stories, routines, relationships)
  last_session_summary text,       -- Reserved for future use
  facts text                       -- Persona characteristics (traits, interests, values)
);
```

**Field Usage**:
- `user_id`: Primary key, identifies the user
- `version_ts`: Auto-updated timestamp on each write
- `persona_summary`: Stores daily life context extracted by `context_processor.py`
- `facts`: Stores persona facts extracted by `facts_extractor.py`
- `last_session_summary`: Reserved for future session-based summaries

### Related Tables (Read-Only)

**`wb_conversation`**:
- `id`: Conversation UUID
- `user_id`: User UUID
- `started_at`: Conversation start timestamp

**`wb_message`**:
- `id`: Message UUID
- `conversation_id`: Conversation UUID (FK)
- `role`: Message role ("user" or "assistant")
- `text`: Message content
- `created_at`: Message timestamp
