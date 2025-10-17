#!/usr/bin/env python3
"""
Test script to verify database integration in SmallTalkSession
"""
import sys
import os

# Add the backend directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.supabase.database import start_conversation, add_message, end_conversation

def test_database_functions():
    """Test the database functions work correctly"""
    print("Testing Supabase database functions...")
    
    try:
        # Test starting a conversation
        print("1. Testing start_conversation...")
        conversation_id = start_conversation(title="Test Small Talk")
        print(f"   ✓ Conversation started with ID: {conversation_id}")
        
        # Test adding user message
        print("2. Testing add_message (user)...")
        user_msg_id = add_message(
            conversation_id=conversation_id,
            role="user",
            content="Hello, this is a test message",
            intent="small_talk",
            lang="en"
        )
        print(f"   ✓ User message added with ID: {user_msg_id}")
        
        # Test adding assistant message
        print("3. Testing add_message (assistant)...")
        assistant_msg_id = add_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Hello! This is a test response from the assistant.",
            lang="en"
        )
        print(f"   ✓ Assistant message added with ID: {assistant_msg_id}")
        
        # Test ending conversation
        print("4. Testing end_conversation...")
        end_conversation(conversation_id)
        print(f"   ✓ Conversation {conversation_id} ended successfully")
        
        print("\n[SUCCESS] All database tests passed!")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Database test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_database_functions()
    sys.exit(0 if success else 1)
