#!/usr/bin/env python3
"""
Test script for Intervention Logging

This script tests inserting dummy intervention logs with all the new intervention type names:
- Support Chat
- Journaling
- Meditation with Music
- Daily Quote
- Gratitude

It also tests mood rating functionality.

Run from backend directory: python testing/test_intervention_logging.py
Or from testing directory: python test_intervention_logging.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import time

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

# Load environment variables
env_path = backend_dir.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Import modules
from src.supabase.database import log_activity_start, log_activity_end, update_mood_rating, query_recent_activity_logs
from src.supabase.auth import get_current_user_id

print("=" * 80)
print("INTERVENTION LOGGING TEST")
print("=" * 80)
print()


def test_intervention_logging():
    """Test inserting intervention logs with all activity types"""
    
    # Get user ID
    try:
        user_id = get_current_user_id()
        print(f"Testing with User ID: {user_id}\n")
    except Exception as e:
        print(f"Error getting user ID: {e}")
        print("Make sure DEV_USER_ID is set in .env file or user_persona.json exists")
        sys.exit(1)
    
    # Define all intervention types to test
    intervention_types = [
        "Support Chat",
        "Journaling",
        "Meditation with Music",
        "Daily Quote",
        "Gratitude"
    ]
    
    print("=" * 80)
    print("TEST 1: INSERTING INTERVENTION LOGS")
    print("=" * 80)
    print()
    
    inserted_logs = []
    
    # Insert logs for each intervention type
    for i, intervention_type in enumerate(intervention_types):
        print(f"Inserting log {i+1}/{len(intervention_types)}: {intervention_type}")
        
        public_id = log_activity_start(
            user_id=user_id,
            activity_type=intervention_type,
            emotional_log_id=None  # Command-triggered
        )
        
        if public_id:
            inserted_logs.append({
                "public_id": public_id,
                "intervention_type": intervention_type
            })
            print(f"  ✓ Successfully inserted log with public_id: {public_id}")
        else:
            print(f"  ✗ Failed to insert log for {intervention_type}")
        
        # Small delay between inserts
        time.sleep(0.5)
    
    print()
    print(f"Successfully inserted {len(inserted_logs)}/{len(intervention_types)} logs")
    print()
    
    if not inserted_logs:
        print("ERROR: No logs were inserted. Cannot continue with tests.")
        return False
    
    # Test end timestamps
    print("=" * 80)
    print("TEST 2: TESTING END TIMESTAMPS")
    print("=" * 80)
    print()
    
    end_timestamp_results = []
    
    # Add end timestamps to first few logs
    for i, log_entry in enumerate(inserted_logs[:3]):
        print(f"Adding end_timestamp to log {i+1}: {log_entry['intervention_type']}")
        
        # Small delay to simulate activity duration
        time.sleep(1)
        
        success = log_activity_end(public_id=log_entry["public_id"])
        
        if success:
            print(f"  ✓ Successfully logged end timestamp")
            end_timestamp_results.append(True)
        else:
            print(f"  ✗ Failed to log end timestamp")
            end_timestamp_results.append(False)
    
    print()
    
    # Test mood ratings
    print("=" * 80)
    print("TEST 3: TESTING MOOD RATINGS")
    print("=" * 80)
    print()
    
    # Test different mood rating scenarios
    test_cases = [
        {"pre": 5, "post": 3, "description": "Both pre and post ratings"},
        {"pre": 7, "post": None, "description": "Only pre-rating"},
        {"pre": None, "post": 4, "description": "Only post-rating"},
        {"pre": 8, "post": 2, "description": "Both ratings (different values)"},
    ]
    
    mood_rating_results = []
    
    for i, test_case in enumerate(test_cases[:min(4, len(inserted_logs))]):
        log_entry = inserted_logs[i]
        print(f"Test case {i+1}: {test_case['description']}")
        print(f"  Intervention: {log_entry['intervention_type']}")
        print(f"  Pre-rating: {test_case['pre']}, Post-rating: {test_case['post']}")
        
        success = update_mood_rating(
            public_id=log_entry["public_id"],
            pre_rating=test_case["pre"],
            post_rating=test_case["post"]
        )
        
        if success:
            print(f"  ✓ Successfully updated mood rating")
            mood_rating_results.append(True)
        else:
            print(f"  ✗ Failed to update mood rating")
            mood_rating_results.append(False)
        print()
    
    # Query recent logs to verify
    print("=" * 80)
    print("TEST 4: QUERYING RECENT LOGS")
    print("=" * 80)
    print()
    
    print("Querying recent intervention logs (last 1 day)...")
    recent_logs = query_recent_activity_logs(
        user_id=user_id,
        limit=10,
        days_back=1
    )
    
    print(f"Found {len(recent_logs)} recent logs")
    print()
    
    # Display inserted logs
    print("Inserted logs summary:")
    print("-" * 80)
    for log_entry in inserted_logs:
        # Find the log in recent_logs
        matching_log = next(
            (log for log in recent_logs if log.get("public_id") == log_entry["public_id"]),
            None
        )
        
        if matching_log:
            print(f"Public ID: {log_entry['public_id']}")
            print(f"  Intervention Type: {matching_log.get('intervention_type', 'N/A')}")
            print(f"  Start Timestamp: {matching_log.get('timestamp', 'N/A')}")
            end_timestamp = matching_log.get('end_timestamp')
            if end_timestamp:
                print(f"  End Timestamp: {end_timestamp}")
            else:
                print(f"  End Timestamp: None")
            mood_rating = matching_log.get('mood_rating')
            if mood_rating:
                print(f"  Mood Rating: {mood_rating}")
            else:
                print(f"  Mood Rating: None")
            print()
        else:
            print(f"Public ID: {log_entry['public_id']} - Not found in query results")
            print()
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✓ Test 1: Insert Intervention Logs - {len(inserted_logs)}/{len(intervention_types)} passed")
    print(f"✓ Test 2: End Timestamps - {sum(end_timestamp_results)}/{len(end_timestamp_results)} passed")
    print(f"✓ Test 3: Mood Ratings - {sum(mood_rating_results)}/{len(mood_rating_results)} passed")
    print(f"✓ Test 4: Query Logs - Found {len(recent_logs)} logs")
    print()
    print("Check the database intervention_log table to verify:")
    print("  - All intervention_type values match the new standardized names")
    print("  - Start timestamps (timestamp column) are populated")
    print("  - End timestamps (end_timestamp column) are populated for first 3 logs")
    print("  - Mood ratings are stored as arrays [pre, post]")
    print("  - Duration column remains but is NOT populated (as per requirements)")
    print("=" * 80)
    print()
    
    return len(inserted_logs) == len(intervention_types)


if __name__ == "__main__":
    success = test_intervention_logging()
    sys.exit(0 if success else 1)
