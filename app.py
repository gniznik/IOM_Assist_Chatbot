import streamlit as st
import requests
import os
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Configuration
st.set_page_config(
    page_title="IOM Assist",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_authenticated" not in st.session_state:
    st.session_state.user_authenticated = False

def call_n8n_webhook(user_message):
    """Send message to n8n workflow and get response"""
    webhook_url = os.getenv('N8N_WEBHOOK_URL')
    
    try:
        payload = {
            "message": user_message,
            "sessionId": st.session_state.get('session_id', 'default')
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get('output', result.get('response', 'Sorry, I encountered an error.'))
        else:
            return f"Error: Unable to get response (Status: {response.status_code})"
            
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again."
    except Exception as e:
        return f"Error: {str(e)}"

def main():
    # Sidebar for user info and settings
    with st.sidebar:
        st.title("🧠 IOM Assist")
        st.markdown("---")
        
        # User authentication placeholder
        if not st.session_state.user_authenticated:
            st.subheader("Access Required")
            access_code = st.text_input("Enter access code:", type="password")
            if st.button("Authenticate"):
                # Replace with your actual authentication logic
                if access_code == os.getenv('ACCESS_CODE', 'demo123'):
                    st.session_state.user_authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid access code")
        else:
            st.success("✅ Authenticated")
            if st.button("Logout"):
                st.session_state.user_authenticated = False
                st.session_state.messages = []
                st.rerun()
            
            st.markdown("---")
            st.subheader("Quick Actions")
            
            # Preset questions for IONM
            preset_questions = [
                "What are normal baseline values for SSEPs?",
                "How to troubleshoot poor waveform quality?",
                "Anesthesia effects on neuromonitoring",
                "MEP stimulation parameters",
                "When to notify the surgeon?"
            ]
            
            for question in preset_questions:
                if st.button(question, key=f"preset_{question[:20]}"):
                    # Add to chat
                    st.session_state.messages.append({"role": "user", "content": question})
                    with st.spinner("Getting response..."):
                        response = call_n8n_webhook(question)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.rerun()

    # Main chat interface
    if st.session_state.user_authenticated:
        st.title("IOM Assist")
        st.markdown("Ask me anything about intraoperative neuromonitoring techniques, troubleshooting, or protocols.")
        
        # Chat history
        chat_container = st.container()
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
        
        # Chat input
        if prompt := st.chat_input("Ask your IONM question..."):
            # Add user message
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            # Display user message immediately
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Get and display assistant response
            with st.chat_message("assistant"):
                with st.spinner("Analyzing your question..."):
                    response = call_n8n_webhook(prompt)
                st.markdown(response)
            
            # Add assistant response to session state
            st.session_state.messages.append({"role": "assistant", "content": response})
        
        # Clear chat button
        if st.session_state.messages:
            if st.button("Clear Chat History"):
                st.session_state.messages = []
                st.rerun()
                
    else:
        st.title("🧠 IOM Assist")
        st.markdown("""
        ### Welcome to IOM Assist
        
        Your AI-powered companion for intraoperative neuromonitoring questions.
        
        **Features:**
        - Real-time answers to technical questions
        - Protocol guidance and troubleshooting
        - Evidence-based recommendations
        - 24/7 availability
        
        Please authenticate in the sidebar to begin.
        """)
        
        # Demo section for non-authenticated users
        st.subheader("What you can ask:")
        st.markdown("""
        - "What are the normal baseline values for SSEPs?"
        - "How do I troubleshoot poor MEP responses?"
        - "What anesthesia drugs affect neuromonitoring?"
        - "When should I alert the surgeon about changes?"
        - "Setup parameters for different monitoring modalities"
        """)

if __name__ == "__main__":
    main()