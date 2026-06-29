#!/usr/bin/env python3
"""
Test script to verify chat persistence endpoints.
Run this after the backend is running.
"""

import asyncio
import httpx
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api"

# Test data
TEST_USER_ID = "firebase-test-user-123"
TEST_SESSION_ID = "session-" + datetime.now().isoformat()

async def test_chat_with_user_id():
    """Test sending a chat message with user_id"""
    print("\n📤 Test 1: Send chat message with user_id")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30) as client:
        payload = {
            "session_id": TEST_SESSION_ID,
            "message": "What is your name?",
            "user_id": TEST_USER_ID
        }
        
        print(f"Request: POST {BASE_URL}/chat")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = await client.post(f"{BASE_URL}/chat", json=payload)
        
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Response:\n{json.dumps(result, indent=2, default=str)}")
        
        return response.status_code == 200


async def test_get_chat_history():
    """Test retrieving chat history for a user"""
    print("\n📥 Test 2: Get chat history")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{BASE_URL}/chat-history/{TEST_USER_ID}?limit=10"
        
        print(f"Request: GET {url}")
        
        response = await client.get(url)
        
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Response:\n{json.dumps(result, indent=2, default=str)}")
        
        if response.status_code == 200:
            print(f"\n✅ Found {result.get('message_count', 0)} messages in history")
        
        return response.status_code == 200


async def test_clear_chat_history():
    """Test clearing chat history for a user"""
    print("\n🗑️  Test 3: Clear chat history")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{BASE_URL}/chat-history/{TEST_USER_ID}"
        
        print(f"Request: DELETE {url}")
        
        response = await client.delete(url)
        
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Response:\n{json.dumps(result, indent=2, default=str)}")
        
        return response.status_code == 200


async def main():
    print("\n" + "=" * 70)
    print("🧪 DHANDHO AI - Chat Persistence API Tests")
    print("=" * 70)
    
    print(f"Test User ID: {TEST_USER_ID}")
    print(f"Test Session ID: {TEST_SESSION_ID}")
    
    try:
        # Test 1: Send chat
        test1_passed = await test_chat_with_user_id()
        
        # Test 2: Get history
        test2_passed = await test_get_chat_history()
        
        # Test 3: Clear history
        test3_passed = await test_clear_chat_history()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 Test Summary")
        print("=" * 70)
        print(f"✅ Chat with user_id: {'PASSED' if test1_passed else 'FAILED'}")
        print(f"✅ Get chat history: {'PASSED' if test2_passed else 'FAILED'}")
        print(f"✅ Clear chat history: {'PASSED' if test3_passed else 'FAILED'}")
        
        if all([test1_passed, test2_passed, test3_passed]):
            print("\n🎉 All tests PASSED! Chat persistence is working.")
        else:
            print("\n⚠️  Some tests failed. Check the responses above.")
    
    except Exception as e:
        print(f"\n❌ Test error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
