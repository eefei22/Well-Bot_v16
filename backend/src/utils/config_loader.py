"""
Central Configuration Loader for Well-Bot

This module loads all secrets and configuration from environment variables
and provides them to other modules. This centralizes all configuration
management and makes the application Docker-ready.
"""

import os
import json
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# DeepSeek API Configuration
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Google Cloud STT Configuration
GOOGLE_TYPE = os.getenv("GOOGLE_TYPE")
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
GOOGLE_PRIVATE_KEY_ID = os.getenv("GOOGLE_PRIVATE_KEY_ID")
GOOGLE_PRIVATE_KEY = os.getenv("GOOGLE_PRIVATE_KEY")
GOOGLE_CLIENT_EMAIL = os.getenv("GOOGLE_CLIENT_EMAIL")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_AUTH_URI = os.getenv("GOOGLE_AUTH_URI")
GOOGLE_TOKEN_URI = os.getenv("GOOGLE_TOKEN_URI")
GOOGLE_AUTH_PROVIDER_CERT_URL = os.getenv("GOOGLE_AUTH_PROVIDER_CERT_URL")
GOOGLE_CLIENT_CERT_URL = os.getenv("GOOGLE_CLIENT_CERT_URL")
GOOGLE_UNIVERSE_DOMAIN = os.getenv("GOOGLE_UNIVERSE_DOMAIN")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Porcupine Wake Word Configuration
PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY")

def validate_required_config():
    """Validate that all required environment variables are set."""
    required_vars = {
        "DeepSeek API": [DEEPSEEK_API_KEY],
        "Google Cloud STT": [
            GOOGLE_TYPE, GOOGLE_PROJECT_ID, GOOGLE_PRIVATE_KEY_ID,
            GOOGLE_PRIVATE_KEY, GOOGLE_CLIENT_EMAIL, GOOGLE_CLIENT_ID,
            GOOGLE_AUTH_URI, GOOGLE_TOKEN_URI, GOOGLE_AUTH_PROVIDER_CERT_URL,
            GOOGLE_CLIENT_CERT_URL, GOOGLE_UNIVERSE_DOMAIN
        ],
        "Supabase": [SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY],
        "Porcupine Wake Word": [PORCUPINE_ACCESS_KEY]
    }
    
    missing_vars = []
    for service, vars_list in required_vars.items():
        for var in vars_list:
            if not var:
                missing_vars.append(f"{service}: {var}")
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

def get_google_cloud_credentials_path():
    """
    Create a temporary Google Cloud credentials JSON file from environment variables.
    Returns the path to the temporary file.
    """
    credentials = {
        "type": GOOGLE_TYPE,
        "project_id": GOOGLE_PROJECT_ID,
        "private_key_id": GOOGLE_PRIVATE_KEY_ID,
        "private_key": GOOGLE_PRIVATE_KEY,
        "client_email": GOOGLE_CLIENT_EMAIL,
        "client_id": GOOGLE_CLIENT_ID,
        "auth_uri": GOOGLE_AUTH_URI,
        "token_uri": GOOGLE_TOKEN_URI,
        "auth_provider_x509_cert_url": GOOGLE_AUTH_PROVIDER_CERT_URL,
        "client_x509_cert_url": GOOGLE_CLIENT_CERT_URL,
        "universe_domain": GOOGLE_UNIVERSE_DOMAIN
    }
    
    # Create a temporary file for Google Cloud credentials
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(credentials, temp_file, indent=2)
    temp_file.close()
    
    return temp_file.name

def get_deepseek_config():
    """Get DeepSeek configuration as a dictionary."""
    return {
        "api_key": DEEPSEEK_API_KEY,
        "base_url": DEEPSEEK_BASE_URL,
        "model": DEEPSEEK_MODEL
    }

def get_supabase_config():
    """Get Supabase configuration as a dictionary."""
    return {
        "url": SUPABASE_URL,
        "anon_key": SUPABASE_ANON_KEY,
        "service_role_key": SUPABASE_SERVICE_ROLE_KEY
    }

def load_global_config():
    """Load global numerical configuration."""
    config_path = Path(__file__).parent.parent.parent / "config" / "global.json"
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_language_config(language='en'):
    """Load language-specific configuration."""
    config_path = Path(__file__).parent.parent.parent / "config" / f"{language}.json"
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# Load default configurations
try:
    GLOBAL_CONFIG = load_global_config()
    LANGUAGE_CONFIG = load_language_config('en')  # Default to English
except Exception as e:
    print(f"Error loading config files: {e}")
    GLOBAL_CONFIG = {}
    LANGUAGE_CONFIG = {}

# Validate configuration on import
try:
    validate_required_config()
except ValueError as e:
    print(f"Configuration Error: {e}")
    print("Please check your .env file and ensure all required variables are set.")
    print("See env_template.txt for reference.")

