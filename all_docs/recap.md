# User Language Configuration System - Implementation Recap

## Overview

Implemented a dynamic user-specific language configuration system that fetches user language preferences from the database and loads the appropriate configuration files (en.json, cn.json, bm.json) for each user. The system supports multi-user scenarios where each user can have different language preferences while running a single-user application instance.

## Architecture

### Core Principles
- **Single-User Instance**: Each application instance (`main.py`) serves one user at a time
- **Dynamic Config Loading**: Language configs are loaded at runtime based on user's database preference
- **Caching**: In-memory cache (300s TTL) for performance optimization
- **User Identity**: Resolved from `DEV_USER_ID` environment variable (placeholder for future JWT auth)
- **Language Source**: `users.language` field from database

### Data Flow

```
main.py (startup)
  ↓
get_current_user_id() → Read DEV_USER_ID from .env
  ↓
resolve_language(user_id) → Query users.language from DB
  ↓
get_global_config_for_user(user_id) → Load global.json + update language codes
  ↓
get_language_config(user_id) → Load en.json/cn.json/bm.json
  ↓
Initialize components with language-specific configs
  ↓
Run system with user's preferred language
```

---

## File Changes and Additions

### 1. New File: `backend/src/utils/config_resolver.py`

**Purpose**: User-specific configuration resolver with caching

**Key Features**:
- Fetches user language from database with caching (300s TTL)
- Loads language-specific config files (en.json, cn.json, bm.json)
- Updates global config with language-specific codes (TTS/STT voice codes)
- Thread-safe caching with invalidate methods

**Key Functions**:
```python
class ConfigResolver:
    def resolve_language(user_id: str) -> LanguageCode  # 'en', 'cn', 'bm'
    def get_language_config(user_id: str) -> dict  # Load language-specific config
    def get_global_config_with_language(language: LanguageCode) -> dict
    def invalidate_user(user_id: str)  # Clear cache for user
    def invalidate_all()  # Clear all caches
```

**Language Code Mappings**:
```python
LANGUAGE_CODES = {
    'en': {
        'tts_voice_name': 'en-US-Chirp3-HD-Charon',
        'tts_language_code': 'en-US',
        'stt_language_code': 'en-US'
    },
    'cn': {
        'tts_voice_name': 'cmn-CN-Chirp3-HD-Charon',
        'tts_language_code': 'cmn-CN',
        'stt_language_code': 'cmn-CN'
    },
    'bm': {
        'tts_voice_name': 'id-ID-Chirp3-HD-Charon',
        'tts_language_code': 'id-ID',
        'stt_language_code': 'id-ID'
    }
}
```

**Changes from original plan**:
- Added `update_global_config_language()` to write language codes to global.json
- Added `get_global_config_for_user()` convenience function
- Added language-specific code mappings for TTS/STT services

---

### 2. Updated: `backend/src/supabase/client.py`

**Changes**:
- Added `fetch_user_by_id()` function to query users table

**New Function**:
```python
def fetch_user_by_id(user_id: str, client: Optional[Client] = None) -> Optional[Dict]:
    """
    Fetch user record by ID.
    Returns user dict with id, email, language or None if not found.
    """
```

**Details**:
- Reads from `users` table (not wb_* tables)
- Returns user dict including `language` field
- Handles errors gracefully with logging

---

### 3. Updated: `backend/src/supabase/database.py`

**Changes**:
- Added `get_user_language()` function
- Added `get_user_by_id()` wrapper function

**New Functions**:
```python
def get_user_language(user_id: str) -> Optional[str]:
    """
    Fetch user's language preference from database.
    Returns language code ('en', 'cn', 'bm') or None if not found.
    """

def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get full user record by ID."""
```

**Details**:
- Wrapper around `client.fetch_user_by_id()`
- Normalizes language codes
- Logs successful/failed fetches

---

### 4. Updated: `backend/src/supabase/auth.py`

**Changes**:
- Created placeholder for user identity resolution
- Reads `DEV_USER_ID` from environment

**Key Functions**:
```python
def get_current_user_id() -> str:
    """
    Get the current user ID for this session.
    Reads from DEV_USER_ID environment variable or defaults to hardcoded value.
    """

def set_session_user(user_id: str) -> None:
    """
    Set the current session user (for testing multi-user scenarios).
    Sets DEV_USER_ID environment variable.
    """
```

**Details**:
- Placeholder for future JWT authentication
- Default user ID: `"8517c97f-66ef-4955-86ed-531013d33d3e"`
- Environment variable name: `DEV_USER_ID`
- Designed to be replaced with real auth in Phase 4+

---

### 5. Updated: `backend/src/activities/smalltalk.py`

**Changes**:
- Modified `__init__()` to accept optional `user_id` parameter
- Updated `initialize()` to load user-specific configs
- Replaced hardcoded config loading with dynamic resolver calls

**Before**:
```python
def __init__(self, backend_dir: Path):
    self.backend_dir = backend_dir
    # ...

def initialize(self) -> bool:
    # Load configurations
    self.global_config = load_global_config()
    self.language_config = load_language_config('en')  # ← Hardcoded 'en'
```

**After**:
```python
def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
    self.backend_dir = backend_dir
    self.user_id = user_id or get_current_user_id()  # ← Dynamic user resolution
    # ...

def initialize(self) -> bool:
    # Load user-specific configurations
    self.global_config = get_global_config_for_user(self.user_id)
    self.language_config = get_language_config(self.user_id)  # ← User-specific
```

**Key Changes**:
- Accepts `user_id` in constructor
- Falls back to `get_current_user_id()` if not provided
- Loads configs dynamically based on user's language
- Logs user ID for debugging

**Imports Added**:
```python
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
```

---

### 6. Updated: `backend/src/activities/journal.py`

**Changes**:
- Modified `__init__()` to accept optional `user_id` parameter
- Updated `initialize()` to load user-specific configs
- Replaced hardcoded config loading with dynamic resolver calls

**Before**:
```python
def __init__(self, backend_dir: Path, user_id: str = DEV_USER_ID):
    self.backend_dir = backend_dir
    self.user_id = user_id  # ← Required parameter
    # ...

def initialize(self) -> bool:
    # Load configurations
    self.global_config = load_global_config()
    language_config = load_language_config('en')  # ← Hardcoded 'en'
```

**After**:
```python
def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
    self.backend_dir = backend_dir
    self.user_id = user_id or get_current_user_id()  # ← Dynamic user resolution
    # ...

def initialize(self) -> bool:
    # Load user-specific configurations
    self.global_config = get_global_config_for_user(self.user_id)
    language_config = get_language_config(self.user_id)  # ← User-specific
```

**Key Changes**:
- `user_id` is now optional (not required parameter)
- Falls back to `get_current_user_id()` if not provided
- Loads configs dynamically based on user's language
- Logs user ID and resolved language

**Imports Added**:
```python
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
```

---

### 7. Updated: `backend/src/components/_pipeline_wakeword.py`

**Changes**:
- Modified `VoicePipeline.__init__()` to accept optional `user_id` parameter
- Updated config loading to use dynamic resolver
- Added user-specific config loading in constructor

**Before**:
```python
def __init__(
    self,
    wakeword_detector: WakeWordDetector,
    stt_service: GoogleSTTService,
    lang: str = "en-US",
    # ... no user_id parameter
):
    # ...
    self.language_config = load_language_config('en')  # ← Hardcoded 'en'
    self.global_config = load_global_config()
```

**After**:
```python
def __init__(
    self,
    wakeword_detector: WakeWordDetector,
    stt_service: GoogleSTTService,
    lang: str = "en-US",
    user_id: Optional[str] = None,  # ← New parameter
    # ...
):
    # ...
    self.user_id = user_id if user_id is not None else get_current_user_id()
    self.global_config = get_global_config_for_user(self.user_id)  # ← Dynamic
    self.language_config = get_language_config(self.user_id)  # ← Dynamic
```

**Changes to `create_voice_pipeline()`**:
```python
def create_voice_pipeline(
    access_key_file: str,
    custom_keyword_file: Optional[str] = None,
    language: str = "en-US",
    user_id: Optional[str] = None,  # ← New parameter
    # ...
):
    # ...
    pipeline = VoicePipeline(
        # ...
        user_id=user_id,  # ← Pass user_id to pipeline
        # ...
    )
```

---

### 8. Updated: `backend/main.py`

**Changes**:
- Modified `WellBotOrchestrator.__init__()` to resolve user at startup
- Updated config loading to use dynamic resolver
- Passes `user_id` through to all components

**Before**:
```python
def __init__(self):
    # ...
    self.global_config = GLOBAL_CONFIG  # ← Global constant
    self.language_config = LANGUAGE_CONFIG  # ← Global constant

def _initialize_components(self) -> bool:
    # ...
    self.stt_service = GoogleSTTService(language="en-US", sample_rate=16000)
    # Hardcoded language
```

**After**:
```python
def __init__(self):
    # ...
    self.user_id = get_current_user_id()  # ← Resolve user at startup
    self.global_config = None  # ← Will be loaded in _initialize_components
    # ...

def _initialize_components(self) -> bool:
    # Resolve user language and load configs
    user_lang = resolve_language(self.user_id)  # ← Query DB for language
    self.global_config = get_global_config_for_user(self.user_id)  # ← Dynamic
    
    # Use language-specific codes for STT
    stt_language = self.global_config["language_codes"]["stt_language_code"]
    self.stt_service = GoogleSTTService(language=stt_language, sample_rate=16000)
```

**Passing user_id to components**:
```python
# VoicePipeline
self.voice_pipeline = create_voice_pipeline(
    # ...
    user_id=self.user_id,  # ← Pass user_id
    # ...
)

# SmallTalkActivity
self.smalltalk_activity = SmallTalkActivity(
    backend_dir=self.backend_dir,
    user_id=self.user_id  # ← Pass user_id
)
```

**Config loading in audio callbacks**:
```python
def _handle_wakeword_nudge(self):
    # ...
    from src.utils.config_resolver import get_language_config
    language_config = get_language_config(self.user_id)  # ← Dynamic load
    nudge_audio_path = self.backend_dir / language_config["audio_paths"]["nudge_audio_path"]
    # ...
```

**Imports Changed**:
```python
# Before
from src.utils.config_loader import load_global_config, load_language_config, GLOBAL_CONFIG, LANGUAGE_CONFIG

# After
from src.utils.config_resolver import get_global_config_for_user, resolve_language
from src.supabase.auth import get_current_user_id
```

---

## System Flow

### Application Startup Sequence

1. **Environment Setup**
   ```python
   # Load .env file
   load_dotenv()
   # Read DEV_USER_ID (e.g., "740376ad-592e-4a6a-9b29-cc6196f30cc2")
   ```

2. **Orchestrator Initialization**
   ```python
   # main.py: WellBotOrchestrator.__init__()
   self.user_id = get_current_user_id()  # Returns DEV_USER_ID from .env
   # Log: "Orchestrator initialized for user: 740376ad..."
   ```

3. **Component Initialization**
   ```python
   # main.py: _initialize_components()
   
   # Step 1: Resolve user language
   user_lang = resolve_language(self.user_id)  # Queries users.language
   # Returns: 'en', 'cn', or 'bm'
   # Log: "Resolved language 'en' for user 740376ad..."
   
   # Step 2: Load configs
   self.global_config = get_global_config_for_user(self.user_id)
   # Loads global.json + updates language codes based on user_lang
   # Returns: global config with language-specific TTS/STT codes
   # Log: "Loaded global config for user"
   
   # Step 3: Initialize STT with language-specific code
   stt_language = self.global_config["language_codes"]["stt_language_code"]
   self.stt_service = GoogleSTTService(language=stt_language)
   # If user_lang='en': stt_language='en-US'
   # If user_lang='cn': stt_language='cmn-CN'
   # If user_lang='bm': stt_language='id-ID'
   ```

4. **VoicePipeline Initialization**
   ```python
   self.voice_pipeline = create_voice_pipeline(
       user_id=self.user_id,  # Pass user_id
       language=self.global_config["language_codes"]["stt_language_code"],
       # ...
   )
   # Inside VoicePipeline.__init__():
   #   self.user_id = resolve from parameter or get_current_user_id()
   #   self.global_config = get_global_config_for_user(self.user_id)
   #   self.language_config = get_language_config(self.user_id)
   #   self.intent_phrases = self.language_config.get("intents", {})
   #   # Load user's language-specific intent phrases
   ```

5. **SmallTalkActivity Initialization**
   ```python
   self.smalltalk_activity = SmallTalkActivity(
       backend_dir=self.backend_dir,
       user_id=self.user_id  # Pass user_id
   )
   # Inside SmallTalkActivity.initialize():
   #   self.global_config = get_global_config_for_user(self.user_id)
   #   self.language_config = get_language_config(self.user_id)
   #   self.smalltalk_config = self.language_config.get("smalltalk", {})
   #   self.audio_paths = self.language_config.get("audio_paths", {})
   #   # Load user's language-specific prompts and audio paths
   ```

---

## Configuration Loading Examples

### Example 1: English User (user_lang='en')

```
Database: users.language = 'en'
↓
config_resolver.resolve_language(user_id)
↓
get_global_config_for_user(user_id)
↓
  Loads: global.json
  Updates: language_codes with 'en' values
    - tts_voice_name: 'en-US-Chirp3-HD-Charon'
    - tts_language_code: 'en-US'
    - stt_language_code: 'en-US'
↓
get_language_config(user_id)
↓
  Loads: en.json
  Returns: {
    "intents": {
      "smalltalk": ["can we talk", "i'm bored", ...],
      ...
    },
    "smalltalk": {
      "system_prompt": "You are Well-Bot...",
      "prompts": {
        "start": "What's on your mind?",
        ...
      }
    },
    "audio_paths": {
      "wokeword_audio_path": "assets/ENGLISH/wokeword_EN_male.wav",
      ...
    }
  }
```

### Example 2: Chinese User (user_lang='cn')

```
Database: users.language = 'cn'
↓
config_resolver.resolve_language(user_id)
↓
get_global_config_for_user(user_id)
↓
  Loads: global.json
  Updates: language_codes with 'cn' values
    - tts_voice_name: 'cmn-CN-Chirp3-HD-Charon'
    - tts_language_code: 'cmn-CN'
    - stt_language_code: 'cmn-CN'
↓
get_language_config(user_id)
↓
  Loads: cn.json
  Returns: {
    "intents": {
      "smalltalk": ["我们聊聊", "我很无聊", ...],
      ...
    },
    "smalltalk": {
      "system_prompt": "您是Well-Bot...",
      "prompts": {
        "start": "有什么心事吗？",
        ...
      }
    },
    "audio_paths": {
      "wokeword_audio_path": "assets/CHINESE/wokeword_CN_male.wav",
      ...
    }
  }
```

### Example 3: Malay User (user_lang='bm')

```
Database: users.language = 'bm'
↓
config_resolver.resolve_language(user_id)
↓
get_global_config_for_user(user_id)
↓
  Loads: global.json
  Updates: language_codes with 'bm' values
    - tts_voice_name: 'id-ID-Chirp3-HD-Charon'
    - tts_language_code: 'id-ID'
    - stt_language_code: 'id-ID'
↓
get_language_config(user_id)
↓
  Loads: bm.json
  Returns: {
    "intents": {
      "smalltalk": ["boleh kita bercakap", "saya bosan", ...],
      ...
    },
    "smalltalk": {
      "system_prompt": "Anda adalah Well-Bot...",
      "prompts": {
        "start": "Apa yang ada dalam fikiran anda?",
        ...
      }
    },
    "audio_paths": {
      "wokeword_audio_path": "assets/MALAY/wokeword_BN_male.wav",
      ...
    }
  }
```

---

## Testing

### Test Script: `backend/testing/test_config_resolver.py`

**Purpose**: Quick verification of config resolution

**Usage**:
```bash
cd backend
python testing\test_config_resolver.py
```

**What it tests**:
1. Reads `DEV_USER_ID` from `.env`
2. Resolves user language from database
3. Loads language-specific config
4. Displays language codes and sample content
5. Tests cache performance (second call should be instant)

---

### Test Script: `backend/testing/test_system_language_config.py`

**Purpose**: Full system language configuration test

**Usage**:
```bash
cd backend
python testing\test_system_language_config.py --user-id 740376ad-592e-4a6a-9b29-cc6196f30cc2
```

**What it tests**:
1. Fetches user data from database
2. Resolves language preference
3. Tests config loading
4. Displays sample prompts and intent phrases
5. Shows updated language codes
6. Tests file update functionality

---

## Running the Application

### Option 1: Using .env file (Recommended)

```bash
# Set DEV_USER_ID in .env file
DEV_USER_ID=740376ad-592e-4a6a-9b29-cc6196f30cc2

# Run application
cd backend
python main.py
```

### Option 2: Using batch script

```bash
cd backend
.\start_backend_with_user.bat 740376ad-592e-4a6a-9b29-cc6196f30cc2
```

### Option 3: Using environment variable (Windows CMD)

```cmd
set DEV_USER_ID=740376ad-592e-4a6a-9b29-cc6196f30cc2
python main.py
```

### Option 4: Using environment variable (Windows PowerShell)

```powershell
$env:DEV_USER_ID="740376ad-592e-4a6a-9b29-cc6196f30cc2"
python main.py
```

---

## Caching Behavior

### Language Cache (300s TTL)

```
First call:
  resolve_language(user_id) → Query DB → Cache result → Return

Second call (within 300s):
  resolve_language(user_id) → Read from cache → Return (instant)

Third call (after 300s):
  resolve_language(user_id) → Cache expired → Query DB → Cache result → Return
```

### Config Cache (No TTL - persists for application lifetime)

```
First call for language='en':
  get_language_config(user_id) → Load en.json → Cache → Return

Second call for same user (same language):
  get_language_config(user_id) → Read from cache → Return (instant)
```

### Manual Cache Invalidation

```python
from src.utils.config_resolver import invalidate_user_cache

# Force refresh for specific user
invalidate_user_cache(user_id)

# After preference change in database:
invalidate_user_cache(user_id)
# Next call will fetch fresh from DB
```

---

## Multi-User Support

### Current Implementation (Single-User Instance)

- Each application instance serves one user
- User identified by `DEV_USER_ID` environment variable
- Configs loaded at startup based on that user's language preference
- No runtime user switching

### Future Implementation (Multi-User Instance)

When real authentication is implemented:

```python
# In auth.py (replacing get_current_user_id())
def get_current_user_id() -> str:
    """
    Extract user ID from JWT token in request.
    """
    token = extract_jwt_from_request()
    user_id = validate_and_decode_jwt(token)
    return user_id
```

No changes needed to activities or pipeline - they already use `user_id` parameter!

---

## Database Schema

### Required Table: `users`

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT,
    language TEXT DEFAULT 'en'  -- Language code: 'en', 'cn', or 'bm'
);
```

### Expected Data

```sql
-- Example users
INSERT INTO users (id, email, language) VALUES
    ('740376ad-592e-4a6a-9b29-cc6196f30cc2', 'user1@example.com', 'en'),
    ('user-id-2', 'user2@example.com', 'cn'),
    ('user-id-3', 'user3@example.com', 'bm');
```

---

## Summary of Changes

### Files Modified
1. ✅ `backend/src/utils/config_resolver.py (created)`
2. ✅ `backend/src/supabase/client.py` - Added `fetch_user_by_id()`
3. ✅ `backend/src/supabase/database.py` - Added `get_user_language()`, `get_user_by_id()`
4. ✅ `backend/src/supabase/auth.py` - Created placeholder
5. ✅ `backend/src/activities/smalltalk.py` - Updated to use user-specific configs
6. ✅ `backend/src/activities/journal.py` - Updated to use user-specific configs
7. ✅ `backend/src/components/_pipeline_wakeword.py` - Updated to accept user_id
8. ✅ `backend/main.py` - Updated to resolve user and pass user_id through pipeline

### Files Created
1. ✅ `backend/src/utils/config_resolver.py` - User-specific config resolver
2. ✅ `backend/src/supabase/auth.py` - User identity placeholder
3. ✅ `backend/testing/test_config_resolver.py` - Quick config test
4. ✅ `backend/testing/test_system_language_config.py` - Full system test
5. ✅ `backend/start_backend_with_user.bat` - Helper script for user switching

### Configuration Files
- ✅ `backend/config/global.json` - Global numerical settings + language codes
- ✅ `backend/config/en.json` - English language content
- ✅ `backend/config/cn.json` - Chinese language content
- ✅ `backend/config/bm.json` - Malay language content

---

## Benefits

1. **Multi-Language Support**: Users can interact in their preferred language
2. **Centralized Config**: All language-specific content in dedicated JSON files
3. **Database-Driven**: Language preference fetched from database, not hardcoded
4. **Performance**: Caching reduces database queries
5. **Scalable**: Easy to add new languages (just add new language_XX.json file)
6. **Testable**: Placeholder auth allows easy multi-user testing
7. **Future-Ready**: Ready for real JWT authentication in Phase 4+

---

## Next Steps

### To Add a New Language:

1. Create `backend/config/xx.json` with language content
2. Add language code mappings to `LANGUAGE_CODES` in `config_resolver.py`:
   ```python
   'xx': {
       'tts_voice_name': 'xx-XX-Chirp3-HD-Charon',
       'tts_language_code': 'xx-XX',
       'stt_language_code': 'xx-XX'
   }
   ```
3. Update `LanguageCode` type in `config_resolver.py`:
   ```python
   LanguageCode = Literal['en', 'cn', 'bm', 'xx']
   ```
4. Add users with `language='xx'` to database

---

## Troubleshooting

### Issue: Config not loading for user
**Check**:
- User exists in `users` table with valid UUID
- `language` field is set ('en', 'cn', or 'bm')
- `DEV_USER_ID` environment variable is set correctly
- Database connection is working

### Issue: Wrong language loaded
**Check**:
- `DEV_USER_ID` matches user in database
- Database `users.language` field is correct
- Cache is cleared if needed: `invalidate_user_cache(user_id)`

### Issue: Language-specific audio not playing
**Check**:
- Audio files exist in language-specific directories
- Paths in language JSON files are correct
- `use_audio_files` setting in global.json is enabled

---
---

so moving forward from now, i just need to make sure all new downstream components / activities accept user_id such that the user preference will be known as long as the user_id is passed ?

---

Yes. Passing `user_id` to new components/activities is sufficient; `config_resolver.py` will resolve the user-specific configs.


[1 tool called]

## Pattern to follow

Add `user_id` as an optional parameter that falls back to the current user:

```python
from src.supabase.auth import get_current_user_id
from src.utils.config_resolver import get_language_config, get_global_config_for_user

class YourNewActivity:
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()  # ← Use this pattern
        # ... rest of init
    
    def initialize(self) -> bool:
        # Load user-specific configs
        self.global_config = get_global_config_for_user(self.user_id)  # ← Gets language codes
        language_config = get_language_config(self.user_id)  # ← Gets en/cn/bm content
        
        # Use the configs...
        your_config = language_config.get("your_feature", {})
        
        return True
```

## Functions to call

### 1. `get_global_config_for_user(user_id)` 
Returns global config with correct language codes:
```python
config = get_global_config_for_user(self.user_id)
# Returns:
{
    "language_codes": {
        "tts_voice_name": "en-US-Chirp3-HD-Charon",  # or cn/bm
        "tts_language_code": "en-US",
        "stt_language_code": "en-US"
    },
    "your_feature": {
        "timeout": 30,
        "threshold": 0.5
    }
}
```

### 2. `get_language_config(user_id)`
Returns language-specific config:
```python
config = get_language_config(self.user_id)
# Returns en.json, cn.json, or bm.json based on user's database language
# Contains prompts, phrases, audio paths in user's language
```

## How it resolves preferences

The resolver:
1. Receives `user_id`
2. Queries `users.language` (cached 300s)
3. Loads `en.json`/`cn.json`/`bm.json` accordingly
4. Updates global config with language-specific TTS/STT codes
5. Returns the merged configs

The system handles:
- Caching
- DB queries
- Language file loading
- Error fallback to 'en'
- Thread safety

## Example: new activity

```python
class NewFeatureActivity:
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()
        # No need to know HOW user_id is resolved!
        # Just store it and use it later
    
    def initialize(self) -> bool:
        # Get user's configs (language already resolved)
        self.global_config = get_global_config_for_user(self.user_id)
        language_config = get_language_config(self.user_id)
        
        # Extract your feature config
        self.feature_config = language_config.get("new_feature", {})
        self.audio_paths = language_config.get("audio_paths", {})
        
        # Get language-specific TTS codes
        tts_voice = self.global_config["language_codes"]["tts_voice_name"]
        tts_lang = self.global_config["language_codes"]["tts_language_code"]
        
        # Initialize your components with correct language
        self.tts = GoogleTTSClient(voice_name=tts_voice, language_code=tts_lang)
        
        return True
```

## Summary

- Accept `user_id` (or `None`) in `__init__`
- Use `self.user_id = user_id or get_current_user_id()`
- Call `get_global_config_for_user(self.user_id)` and `get_language_config(self.user_id)`
- Read language-specific prompts/phrases/audio from the returned config
- Use the correct TTS/STT codes from the global config

`config_resolver.py` handles preference resolution. Components stay decoupled from auth details.

