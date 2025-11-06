#!/usr/bin/env python3
"""
Standalone Test Script for LLM Conversation

This script tests conversation with DeepSeek LLM.
It provides an interactive conversation loop with streaming responses.

Usage:
    python test_llm_converse.py

Type messages to chat with the LLM, or press Ctrl+C to stop.
"""

import os
import sys
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION - Tweak these variables as needed
# ============================================================================

# Path to .env file (relative to this script)
ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')

# DeepSeek LLM settings
DEEPSEEK_BASE_URL = "https://api.deepseek.com"  # Base URL for DeepSeek API
DEEPSEEK_MODEL = "deepseek-chat"  # Model name
LLM_TEMPERATURE = 0.6  # Temperature for LLM responses
LLM_TIMEOUT = 30.0  # Request timeout in seconds

# System prompt for the conversation
SYSTEM_PROMPT = "You are a friendly, concise wellness assistant. Keep responses short unless asked."

# Output directory for logs and results
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
CONVERSATION_FILE = os.path.join(OUTPUT_DIR, 'llm_conversation.json')
LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'test_llm_converse.log')

# ============================================================================
# SETUP
# ============================================================================

# Load environment variables
load_dotenv(ENV_FILE_PATH)

# Get DeepSeek API key from environment
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Override base URL and model if set in environment
if os.getenv("DEEPSEEK_BASE_URL"):
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")
if os.getenv("DEEPSEEK_MODEL"):
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL")

# Create output directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, 'logs'), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Add backend directory to path for imports (needed for relative imports in components)
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def save_conversation(messages: list):
    """Save conversation history to JSON file."""
    conversation_data = {
        "timestamp": datetime.now().isoformat(),
        "system_prompt": SYSTEM_PROMPT,
        "messages": messages
    }
    
    try:
        with open(CONVERSATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(conversation_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Conversation saved to {CONVERSATION_FILE}")
    except Exception as e:
        logger.error(f"Failed to save conversation: {e}")

def stream_llm_response(llm_client, messages: list) -> str:
    """Get streaming response from LLM."""
    logger.info("=" * 60)
    logger.info("Streaming LLM response...")
    logger.info("=" * 60)
    
    full_response = ""
    
    try:
        print("\n[Assistant] ", end="", flush=True)
        
        for chunk in llm_client.stream_chat(messages, temperature=LLM_TEMPERATURE):
            print(chunk, end="", flush=True)
            full_response += chunk
        
        print()  # Newline after stream completes
        logger.info(f"LLM response received ({len(full_response)} characters)")
        
        return full_response
        
    except Exception as e:
        logger.error(f"Error during LLM streaming: {e}", exc_info=True)
        return None

def main():
    """Main test function."""
    logger.info("=" * 60)
    logger.info("LLM Conversation Test Script")
    logger.info("=" * 60)
    
    # Validate configuration
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not found in environment variables!")
        logger.error("Please set DEEPSEEK_API_KEY in your .env file")
        return False
    
    logger.info(f"DeepSeek API Key: {DEEPSEEK_API_KEY[:10]}...")
    logger.info(f"DeepSeek Base URL: {DEEPSEEK_BASE_URL}")
    logger.info(f"DeepSeek Model: {DEEPSEEK_MODEL}")
    logger.info(f"Temperature: {LLM_TEMPERATURE}")
    logger.info(f"System Prompt: {SYSTEM_PROMPT}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Conversation File: {CONVERSATION_FILE}")
    logger.info(f"Debug Log: {LOG_FILE}")
    
    llm_client = None
    
    try:
        # Import LLM client
        from src.components.llm import DeepSeekClient
        
        # Initialize LLM client
        logger.info("Initializing DeepSeek LLM client...")
        llm_client = DeepSeekClient(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
            timeout=LLM_TIMEOUT
        )
        logger.info("LLM client initialized successfully")
        
        # Initialize conversation messages
        messages = []
        if SYSTEM_PROMPT:
            messages.append({"role": "system", "content": SYSTEM_PROMPT})
            logger.info("System prompt added to conversation")
        
        # Conversation loop
        logger.info("=" * 60)
        logger.info("Ready for conversation")
        logger.info("Type messages to chat with the LLM, or type 'quit' to exit")
        logger.info("Type 'clear' to reset the conversation")
        logger.info("Type 'save' to save the conversation to file")
        logger.info("=" * 60)
        
        while True:
            try:
                # Get user input
                user_input = input("\n[You] ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'quit':
                    break
                
                if user_input.lower() == 'clear':
                    messages = []
                    if SYSTEM_PROMPT:
                        messages.append({"role": "system", "content": SYSTEM_PROMPT})
                    logger.info("Conversation cleared")
                    continue
                
                if user_input.lower() == 'save':
                    save_conversation(messages)
                    continue
                
                # Add user message to conversation
                messages.append({"role": "user", "content": user_input})
                logger.debug(f"User message added: {user_input[:50]}...")
                
                # Get LLM response
                response = stream_llm_response(llm_client, messages)
                
                if response:
                    # Add assistant response to conversation
                    messages.append({"role": "assistant", "content": response})
                    logger.debug(f"Assistant response added: {response[:50]}...")
                else:
                    logger.error("Failed to get LLM response")
                    # Remove the user message if response failed
                    messages.pop()
                
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in conversation loop: {e}", exc_info=True)
        
        # Save conversation before exiting
        if messages:
            logger.info("Saving conversation before exit...")
            save_conversation(messages)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during LLM conversation test: {e}", exc_info=True)
        return False
        
    finally:
        logger.info("=" * 60)
        logger.info("Test completed")
        logger.info("=" * 60)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

