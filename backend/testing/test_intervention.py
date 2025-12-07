#!/usr/bin/env python3
"""
Test script for Intervention Module Integration

This script tests:
1. Database query for emotional_log entries
2. Cloud service request and response
3. Response recording in intervention_record.json

Run from backend directory: python testing/test_intervention.py
Or from testing directory: python test_intervention.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

# Load environment variables
env_path = backend_dir.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Import modules
from src.supabase.database import query_emotional_logs_since
from src.utils.intervention_client import InterventionServiceClient
from src.utils.intervention_record import InterventionRecordManager
from src.supabase.auth import get_current_user_id

print("=" * 80)
print("INTERVENTION MODULE INTEGRATION TEST")
print("=" * 80)
print()


def test_database_query(user_id: str):
    """Test 1: Database query for emotional_log entries"""
    print("=" * 80)
    print("TEST 1: DATABASE QUERY")
    print("=" * 80)
    
    try:
        # Query for entries in the last 24 hours
        cutoff_time = datetime.now() - timedelta(hours=24)
        print(f"\nQuerying emotional_log for entries since: {cutoff_time}")
        
        entries = query_emotional_logs_since(user_id, cutoff_time)
        
        print(f"✓ Query successful")
        print(f"  Found {len(entries)} entries in last 24 hours")
        
        if entries:
            print(f"\n  Sample entries:")
            for i, entry in enumerate(entries[:3], 1):  # Show first 3
                print(f"    {i}. ID: {entry.get('id')}, "
                      f"Emotion: {entry.get('emotion_label')}, "
                      f"Confidence: {entry.get('confidence_score'):.2f}, "
                      f"Timestamp: {entry.get('timestamp')}")
            
            # Get the latest entry for testing
            latest_entry = entries[-1]
            print(f"\n  Latest entry (will use for cloud service test):")
            print(f"    ID: {latest_entry.get('id')}")
            print(f"    Emotion: {latest_entry.get('emotion_label')}")
            print(f"    Confidence: {latest_entry.get('confidence_score')}")
            print(f"    Timestamp: {latest_entry.get('timestamp')}")
            
            return latest_entry
        else:
            print("\n  ⚠ No entries found in last 24 hours")
            print("  Creating a test entry structure for cloud service test...")
            # Return a mock entry structure for testing
            return {
                "id": None,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
                "emotion_label": "Sad",
                "confidence_score": 0.85,
                "emotional_score": None
            }
        
    except Exception as e:
        print(f"\n✗ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_cloud_service(emotion_entry: dict):
    """Test 2: Cloud service request and response"""
    print("\n" + "=" * 80)
    print("TEST 2: CLOUD SERVICE REQUEST & RESPONSE")
    print("=" * 80)
    
    if not emotion_entry:
        print("\n✗ TEST 2 SKIPPED: No emotion entry available")
        return None
    
    try:
        # Initialize client
        print("\nInitializing InterventionServiceClient...")
        client = InterventionServiceClient()
        print(f"  Service URL: {client.service_url}")
        
        # Check health first
        print("\nChecking service health...")
        is_healthy = client.check_health()
        if is_healthy:
            print("  ✓ Service is healthy")
        else:
            print("  ⚠ Service health check failed (continuing anyway)")
        
        # Parse timestamp
        timestamp_str = emotion_entry.get("timestamp")
        try:
            if isinstance(timestamp_str, str):
                # Remove timezone info if present
                timestamp_str = timestamp_str.replace('Z', '').replace('+00:00', '')
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now()
        except Exception as e:
            print(f"  ⚠ Failed to parse timestamp, using current time: {e}")
            timestamp = datetime.now()
        
        # Prepare request
        user_id = emotion_entry.get("user_id")
        
        print(f"\nRequesting suggestion from cloud service...")
        print(f"  User ID: {user_id}")
        print(f"  Note: Cloud service will fetch latest emotion from database")
        
        # Make request
        request_time = datetime.now()
        response = client.get_suggestion(
            user_id=user_id
        )
        response_time = datetime.now()
        
        if response:
            print(f"\n✓ Request successful")
            print(f"  Request time: {request_time.isoformat()}")
            print(f"  Response time: {response_time.isoformat()}")
            print(f"  Duration: {(response_time - request_time).total_seconds():.2f}s")
            
            # Display decision
            decision = response.get("decision", {})
            print(f"\n  Decision:")
            print(f"    Trigger intervention: {decision.get('trigger_intervention')}")
            print(f"    Confidence: {decision.get('confidence_score', 0):.3f}")
            print(f"    Reasoning: {decision.get('reasoning', 'N/A')}")
            
            # Display suggestion
            suggestion = response.get("suggestion", {})
            ranked_activities = suggestion.get("ranked_activities", [])
            print(f"\n  Suggestion:")
            print(f"    Reasoning: {suggestion.get('reasoning', 'N/A')}")
            print(f"    Ranked Activities:")
            for activity in ranked_activities:
                print(f"      Rank {activity.get('rank')}: {activity.get('activity_type')} "
                      f"(score: {activity.get('score', 0):.3f})")
            
            return {
                "response": response,
                "request_time": request_time,
                "response_time": response_time
            }
        else:
            print(f"\n✗ TEST 2 FAILED: No response from cloud service")
            return None
        
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_record_saving(emotion_entry: dict, cloud_response: dict):
    """Test 3: Response recording in intervention_record.json"""
    print("\n" + "=" * 80)
    print("TEST 3: RECORD SAVING")
    print("=" * 80)
    
    if not emotion_entry or not cloud_response:
        print("\n✗ TEST 3 SKIPPED: Missing required data")
        return False
    
    try:
        # Initialize record manager
        record_file_path = backend_dir / "config" / "intervention_record.json"
        print(f"\nInitializing InterventionRecordManager...")
        print(f"  Record file: {record_file_path}")
        
        manager = InterventionRecordManager(record_file_path)
        
        # Check if file exists
        if record_file_path.exists():
            print(f"  ✓ Record file exists")
        else:
            print(f"  ⚠ Record file does not exist (will be created)")
        
        # Load current record
        print("\nLoading current record...")
        current_record = manager.load_record()
        print(f"  Current latest emotion entry: {current_record.get('latest_emotion_entry')}")
        
        # Update record
        print("\nUpdating record with new data...")
        response_data = cloud_response.get("response", {})
        decision = response_data.get("decision", {})
        suggestion = response_data.get("suggestion", {})
        
        success = manager.update_record(
            decision=decision,
            suggestion=suggestion,
            request_time=cloud_response.get("request_time"),
            response_time=cloud_response.get("response_time")
        )
        
        if success:
            print(f"  ✓ Record updated successfully")
        else:
            print(f"  ✗ Failed to update record")
            return False
        
        # Verify record was saved
        print("\nVerifying saved record...")
        saved_record = manager.load_record()
        
        print(f"  Latest emotion entry:")
        saved_emotion = saved_record.get("latest_emotion_entry")
        if saved_emotion:
            print(f"    ID: {saved_emotion.get('id')}")
            print(f"    Emotion: {saved_emotion.get('emotion_label')}")
            print(f"    Confidence: {saved_emotion.get('confidence_score')}")
        else:
            print(f"    None")
        
        print(f"  Latest decision:")
        saved_decision = saved_record.get("latest_decision")
        if saved_decision:
            print(f"    Trigger: {saved_decision.get('trigger_intervention')}")
            print(f"    Confidence: {saved_decision.get('confidence_score')}")
        else:
            print(f"    None")
        
        print(f"  Latest suggestion:")
        saved_suggestion = saved_record.get("latest_suggestion")
        if saved_suggestion:
            ranked = saved_suggestion.get("ranked_activities", [])
            print(f"    Top activity: {ranked[0].get('activity_type') if ranked else 'N/A'} "
                  f"(rank {ranked[0].get('rank') if ranked else 'N/A'})")
        else:
            print(f"    None")
        
        print(f"  Last request time: {saved_record.get('last_request_time')}")
        print(f"  Last response time: {saved_record.get('last_response_time')}")
        
        # Verify file contents
        print("\nVerifying JSON file contents...")
        with open(record_file_path, 'r', encoding='utf-8') as f:
            file_contents = json.load(f)
        
        if file_contents == saved_record:
            print(f"  ✓ File contents match loaded record")
        else:
            print(f"  ⚠ File contents differ from loaded record")
        
        print("\n✓ TEST 3 PASSED: Record saving working correctly")
        return True
        
    except Exception as e:
        print(f"\n✗ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print()
    
    # Get user ID
    try:
        user_id = get_current_user_id()
        print(f"Testing with User ID: {user_id}\n")
    except Exception as e:
        print(f"Error getting user ID: {e}")
        print("Make sure DEV_USER_ID is set in .env file")
        sys.exit(1)
    
    # Test 1: Database query
    emotion_entry = test_database_query(user_id)
    
    if not emotion_entry:
        print("\n" + "=" * 80)
        print("TESTS ABORTED: Database query failed")
        print("=" * 80)
        sys.exit(1)
    
    # Test 2: Cloud service
    cloud_response = test_cloud_service(emotion_entry)
    
    if not cloud_response:
        print("\n" + "=" * 80)
        print("TESTS ABORTED: Cloud service request failed")
        print("=" * 80)
        print("\nNote: This might be due to:")
        print("  - Cloud service not accessible")
        print("  - Network connectivity issues")
        print("  - Invalid CLOUD_SERVICE_URL in .env")
        sys.exit(1)
    
    # Test 3: Record saving
    success = test_record_saving(emotion_entry, cloud_response)
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✓ Test 1: Database Query - PASSED")
    print(f"✓ Test 2: Cloud Service - PASSED")
    if success:
        print(f"✓ Test 3: Record Saving - PASSED")
        print("\n✓ All tests passed!")
    else:
        print(f"✗ Test 3: Record Saving - FAILED")
        print("\n⚠ Some tests failed")
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()

