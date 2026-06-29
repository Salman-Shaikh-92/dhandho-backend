# Firebase Authentication + Chat Persistence Setup Guide

## Backend Changes (Completed ✅)

Your backend is now ready to:
- Accept `user_id` in chat requests
- Save chat history per user to MongoDB
- Retrieve chat history on page reload
- Clear chat history when requested

### Updated Endpoints

#### 1. **POST /api/chat** (Updated)
Now accepts `user_id` from Firebase login:

```json
{
  "session_id": "session-123",
  "message": "How do I automate my sales process?",
  "user_id": "firebase-user-id-here"
}
```

Response includes:
```json
{
  "session_id": "session-123",
  "status": "success",
  "recommended_tool": "CRM Automation",
  "user_id": "firebase-user-id-here",
  "timestamp": "2026-06-16T10:30:00Z",
  ...
}
```

#### 2. **GET /api/chat-history/{user_id}** (New)
Retrieve user's entire chat history:

```bash
GET http://localhost:8000/api/chat-history/firebase-user-id?limit=50
```

Response:
```json
{
  "user_id": "firebase-user-id",
  "message_count": 5,
  "messages": [
    {
      "_id": "mongo-doc-id",
      "user_id": "firebase-user-id",
      "session_id": "session-123",
      "user_message": "How do I automate sales?",
      "ai_response": "CRM Automation can help streamline...",
      "status": "success",
      "timestamp": "2026-06-16T10:30:00Z"
    }
  ]
}
```

#### 3. **DELETE /api/chat-history/{user_id}** (New)
Clear all chat history for a user:

```bash
DELETE http://localhost:8000/api/chat-history/firebase-user-id
```

---

## Frontend Setup (Next Steps)

### Step 1: Install Firebase SDK

```bash
npm install firebase
```

### Step 2: Initialize Firebase in Your Frontend

Create `firebase-config.js`:

```javascript
import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';

const firebaseConfig = {
  apiKey: "YOUR_API_KEY",
  authDomain: "YOUR_AUTH_DOMAIN",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "YOUR_STORAGE_BUCKET",
  messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
  appId: "YOUR_APP_ID"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
```

Get your `firebaseConfig` from: [Firebase Console](https://console.firebase.google.com/)

### Step 3: Setup Google + Phone Authentication

```javascript
import { signInWithPopup, GoogleAuthProvider, signInWithPhoneNumber, RecaptchaVerifier } from 'firebase/auth';
import { auth } from './firebase-config';

// Google Login
const googleProvider = new GoogleAuthProvider();
async function loginWithGoogle() {
  try {
    const result = await signInWithPopup(auth, googleProvider);
    const user = result.user;
    // Use user.uid as user_id for backend
    localStorage.setItem('userId', user.uid);
    console.log('Logged in:', user.uid);
  } catch (error) {
    console.error('Google login error:', error);
  }
}

// Phone Login (requires reCAPTCHA)
async function loginWithPhone(phoneNumber) {
  const recaptchaVerifier = new RecaptchaVerifier('recaptcha-container', {}, auth);
  try {
    const confirmationResult = await signInWithPhoneNumber(auth, phoneNumber, recaptchaVerifier);
    // User will verify the OTP they receive
    window.confirmationResult = confirmationResult;
  } catch (error) {
    console.error('Phone login error:', error);
  }
}
```

### Step 4: Send Chat with user_id

When the user sends a message, include their Firebase user ID:

```javascript
async function sendChatMessage(message) {
  const userId = localStorage.getItem('userId'); // Get from Firebase login
  
  if (!userId) {
    console.error('User not logged in');
    return;
  }

  const response = await fetch('http://localhost:8000/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: 'session-' + Date.now(),
      message: message,
      user_id: userId  // Send Firebase user ID
    })
  });

  const data = await response.json();
  console.log('Chat response:', data);
  
  // Save to state/UI
  return data;
}
```

### Step 5: Load Chat History on Page Refresh

When the page loads and user is logged in:

```javascript
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from './firebase-config';

async function loadChatHistoryOnPageLoad() {
  onAuthStateChanged(auth, async (user) => {
    if (user) {
      // User is logged in
      const userId = user.uid;
      localStorage.setItem('userId', userId);
      
      // Fetch their chat history
      try {
        const response = await fetch(`http://localhost:8000/api/chat-history/${userId}`);
        const data = await response.json();
        
        console.log('Chat history loaded:', data.messages);
        
        // Restore chat in UI
        displayChatHistory(data.messages);
      } catch (error) {
        console.error('Error loading chat history:', error);
      }
    } else {
      // User is logged out
      console.log('User logged out');
      clearChatUI();
    }
  });
}

// Call this function when your chat page loads
loadChatHistoryOnPageLoad();
```

### Step 6: Display Chat History in UI

```javascript
function displayChatHistory(messages) {
  const chatContainer = document.getElementById('chat-messages');
  chatContainer.innerHTML = ''; // Clear existing

  messages.forEach(msg => {
    // User message
    const userDiv = document.createElement('div');
    userDiv.className = 'message user-message';
    userDiv.textContent = msg.user_message;
    chatContainer.appendChild(userDiv);

    // AI response
    const aiDiv = document.createElement('div');
    aiDiv.className = 'message ai-message';
    aiDiv.textContent = msg.ai_response;
    chatContainer.appendChild(aiDiv);
  });
}
```

### Step 7: Add Logout Functionality

```javascript
import { signOut } from 'firebase/auth';
import { auth } from './firebase-config';

async function logout() {
  try {
    await signOut(auth);
    localStorage.removeItem('userId');
    clearChatUI();
    console.log('User logged out');
  } catch (error) {
    console.error('Logout error:', error);
  }
}
```

---

## Summary of Data Flow

1. **User logs in via Firebase** (Google/Phone)
2. **Frontend stores Firebase `user.uid`** in localStorage
3. **Chat message sent** with `user_id` field
4. **Backend saves** to MongoDB `users_chat_history` collection
5. **On page refresh**:
   - Firebase detects logged-in user
   - Frontend calls `GET /api/chat-history/{user_id}`
   - Chat history is restored in UI
6. **On logout**:
   - User can optionally clear history via `DELETE /api/chat-history/{user_id}`
   - Or keep history for next login

---

## Backend Deployment Notes

After testing locally, remember to:
1. Update your frontend API endpoint from `localhost:8000` to your deployed backend URL
2. Enable CORS if frontend is on a different domain
3. Set `MONGODB_URI` environment variable on your hosting platform

---

## Testing Checklist

- [ ] Frontend Firebase login works (Google)
- [ ] Frontend Firebase login works (Phone)
- [ ] Chat messages are sent with `user_id`
- [ ] MongoDB stores messages in `users_chat_history` collection
- [ ] GET `/api/chat-history/{user_id}` returns past messages
- [ ] Page refresh shows chat history (user stays logged in)
- [ ] Logout clears localStorage and resets UI
- [ ] Multiple messages are restored in correct order
