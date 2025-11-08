#!/usr/bin/env python3
"""
Test script for context processor endpoint.
Tests the connection and API call from Well-Bot to the context processor service.
"""

import sys
import logging
import requests
from pathlib import Path
from typing import Optional

# Add the backend directory to the path
backend_dir = Path(__file__).parent
sys.path.append(str(backend_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Default user ID (from database.py)
DEFAULT_USER_ID = "8517c97f-66ef-4955-86ed-531013d33d3e"


def test_context_processor_endpoint(
    user_id: str = DEFAULT_USER_ID,
    context_service_url: str = "http://localhost:8000",
    timeout: int = 300
) -> bool:
    """
    Test the context processor endpoint.
    
    Args:
        user_id: User UUID to test with
        context_service_url: Base URL of the context processor service
        timeout: Request timeout in seconds
        
    Returns:
        True if successful, False otherwise
    """
    endpoint = f"{context_service_url}/api/context/process"
    
    logger.info("=" * 60)
    logger.info("Testing Context Processor Endpoint")
    logger.info("=" * 60)
    logger.info(f"Endpoint: {endpoint}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Timeout: {timeout}s")
    logger.info("")
    
    # Step 1: Health check
    logger.info("Step 1: Checking service health...")
    try:
        health_url = f"{context_service_url}/health"
        logger.info(f"  Health check URL: {health_url}")
        health_response = requests.get(health_url, timeout=5)
        
        if health_response.status_code == 200:
            health_data = health_response.json() if health_response.text else {}
            logger.info(f"  ✓ Service is healthy: {health_data}")
        else:
            logger.warning(f"  ⚠ Health check returned status {health_response.status_code}")
    except requests.exceptions.ConnectionError:
        logger.error(f"  ✗ Cannot connect to service at {context_service_url}")
        logger.error(f"  Please verify the context processor service is running")
        return False
    except requests.exceptions.Timeout:
        logger.warning(f"  ⚠ Health check timed out (service may be slow)")
    except Exception as e:
        logger.warning(f"  ⚠ Health check failed: {e} (continuing anyway)")
    
    logger.info("")
    
    # Step 2: Make the processing request
    logger.info("Step 2: Making POST request to context processor...")
    try:
        request_payload = {"user_id": user_id}
        logger.info(f"  Request payload: {request_payload}")
        logger.info(f"  Sending POST request...")
        
        response = requests.post(
            endpoint,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        
        logger.info(f"  Response status: {response.status_code}")
        logger.info(f"  Response headers: {dict(response.headers)}")
        
        # Check for HTTP errors
        if response.status_code >= 400:
            logger.error(f"  ✗ Request failed with status {response.status_code}")
            error_text = response.text[:500] if response.text else "No error message"
            logger.error(f"  Error response: {error_text}")
            
            try:
                error_json = response.json()
                logger.error(f"  Error details: {error_json}")
            except:
                pass
            
            return False
        
        # Parse successful response
        try:
            result = response.json()
            logger.info("  ✓ Request successful!")
            logger.info(f"  Response data:")
            logger.info(f"    Status: {result.get('status', 'N/A')}")
            logger.info(f"    User ID: {result.get('user_id', 'N/A')}")
            logger.info(f"    Facts extracted: {result.get('facts') is not None}")
            logger.info(f"    Persona summary extracted: {result.get('persona_summary') is not None}")
            
            # Show preview of extracted data if available
            if result.get('facts'):
                facts_preview = str(result.get('facts'))[:200]
                logger.info(f"    Facts preview: {facts_preview}...")
            
            if result.get('persona_summary'):
                persona_preview = str(result.get('persona_summary'))[:200]
                logger.info(f"    Persona preview: {persona_preview}...")
            
            return True
            
        except ValueError as e:
            logger.error(f"  ✗ Failed to parse JSON response: {e}")
            logger.error(f"  Response text: {response.text[:500]}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"  ✗ Request timed out after {timeout}s")
        logger.error(f"  The context processor may be taking longer than expected")
        return False
        
    except requests.exceptions.ConnectionError as e:
        logger.error(f"  ✗ Failed to connect to endpoint: {e}")
        logger.error(f"  Please verify:")
        logger.error(f"    1. The context processor service is running")
        logger.error(f"    2. The URL is correct: {context_service_url}")
        logger.error(f"    3. There are no firewall/network issues")
        return False
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"  ✗ HTTP error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                logger.error(f"  Error details: {error_detail}")
            except:
                error_text = e.response.text[:500] if e.response.text else "No error message"
                logger.error(f"  Error response: {error_text}")
        return False
        
    except requests.exceptions.RequestException as e:
        logger.error(f"  ✗ Request exception: {e}")
        logger.error(f"  Error type: {type(e).__name__}")
        return False
        
    except Exception as e:
        logger.error(f"  ✗ Unexpected error: {e}")
        logger.exception(e)
        return False


def main():
    """Main test function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test the context processor endpoint"
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=DEFAULT_USER_ID,
        help=f"User ID to test with (default: {DEFAULT_USER_ID})"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="Context processor service URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)"
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip health check"
    )
    
    args = parser.parse_args()
    
    logger.info("")
    logger.info("Context Processor Endpoint Test")
    logger.info("=" * 60)
    logger.info("")
    
    success = test_context_processor_endpoint(
        user_id=args.user_id,
        context_service_url=args.url,
        timeout=args.timeout
    )
    
    logger.info("")
    logger.info("=" * 60)
    if success:
        logger.info("✓ Test PASSED - Context processor is working correctly")
        return 0
    else:
        logger.error("✗ Test FAILED - Check the errors above")
        return 1


if __name__ == "__main__":
    exit(main())

