import streamlit as st
import requests
import os
import stripe
from dotenv import load_dotenv
from supabase import create_client, Client
 
# Password reset uses GitHub Pages middleman - see reset.html

# Load environment variables
load_dotenv()

# Configuration
st.set_page_config(
    page_title="IOM Assist",
    page_icon="App-Icon.ico",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom meta tags for SEO
st.markdown("""
    <head>
        <meta name="description" content="IOM Assist - Your AI-powered companion for intraoperative neuromonitoring questions.">
        <meta property="og:title" content="IOM Assist">
        <meta property="og:description" content="AI-powered IONM assistant for neuromonitoring professionals.">
    </head>
""", unsafe_allow_html=True)

# Initialize Supabase client normally - PKCE handled via auth options
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY', '')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)



# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')

# App URL for Stripe redirects
APP_URL = os.getenv('APP_URL', 'https://iomassist.com')

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user" not in st.session_state:
    st.session_state.user = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "last_message_count" not in st.session_state:
    st.session_state.last_message_count = 0
if "show_signup" not in st.session_state:
    st.session_state.show_signup = False
if "show_forgot_password" not in st.session_state:
    st.session_state.show_forgot_password = False
if "show_password_reset_form" not in st.session_state:
    st.session_state.show_password_reset_form = False
if "recovery_token" not in st.session_state:
    st.session_state.recovery_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

def login(email, password):
    """Authenticate user with Supabase"""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        st.session_state.user = response.user
        profile = supabase.table('profiles').select('role').eq('id', response.user.id).single().execute()
        st.session_state.user_role = profile.data['role']
        return True, None
    except Exception as e:
        return False, str(e)

def signup(email, password, plan):
    """Create new user in Supabase and redirect to Stripe if Pro"""
    try:
        # Create Supabase auth user
        response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })
        user = response.user

        if not user:
            return False, None, "Failed to create account"

        if plan == 'free':
            # Free plan — just log them in
            login(email, password)
            return True, None, None
        else:
            # Pro plan — create Stripe checkout session
            checkout_session = stripe.checkout.Session.create(
                  payment_method_types=['card'],
                 line_items=[{
                'price': os.getenv('STRIPE_PRO_PRICE_ID'),
                'quantity': 1,
            }],
             mode='subscription',
             subscription_data={
                 'trial_period_days': 7
             },
             success_url=f"{APP_URL}?payment=success&user_id={user.id}",
             cancel_url=f"{APP_URL}?payment=cancelled",
             customer_email=email,
             metadata={'user_id': user.id}
)
            
            return True, checkout_session.url, None

    except Exception as e:
        return False, None, str(e)

def logout():
    """Log out current user"""
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.user_role = None
    st.session_state.messages = []
    st.session_state.last_message_count = 0
    st.session_state.show_signup = False

def change_password(new_password):
    """Change password for currently logged in user or during password reset"""
    try:
        # If we have recovery tokens, establish a session first
        # This is required for the forgot password flow where no session exists
        if st.session_state.get('recovery_token') and st.session_state.get('refresh_token'):
            supabase.auth.set_session(
                access_token=st.session_state.recovery_token,
                refresh_token=st.session_state.refresh_token
            )
        supabase.auth.update_user({"password": new_password})
        return True, None
    except Exception as e:
        return False, str(e)

def send_password_reset(email):
    """Send password reset email via Supabase"""
    try:
        supabase.auth.reset_password_email(
            email,
            options={
                "redirect_to": "https://gniznik.github.io/IOM_Assist_Chatbot/reset.html"
            }
        )
        return True, None
    except Exception as e:
        return False, str(e)   

def has_chat_access():
    """Check if user has access to chat"""
    role = st.session_state.user_role
    return role in ['beta', 'pro']

def call_n8n_webhook(user_message):
    """Send message to n8n workflow and get response"""
    webhook_url = os.getenv('N8N_WEBHOOK_URL')
    try:
        payload = {
            "message": user_message,
            "sessionId": st.session_state.get('session_id', 'default')
        }
        response = requests.post(webhook_url, json=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return result.get('output', result.get('response', 'Sorry, I encountered an error.'))
        else:
            return f"Error: Unable to get response (Status: {response.status_code})"
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again."
    except Exception as e:
        return f"Error: {str(e)}"

def handle_url_params():
    """Handle URL parameters for payment redirects and password reset"""
    params = st.query_params
    
    # Handle payment redirects
    if params.get('payment') == 'success':
        st.success("🎉 Payment successful! Welcome to IOM Assist Pro!")
        st.query_params.clear()
    elif params.get('payment') == 'cancelled':
        st.warning("Payment cancelled. You can try again anytime.")
        st.query_params.clear()
    
    # Handle password reset - tokens arrive as clean query parameters
    # thanks to the reset.html middleman page on GitHub Pages
    if params.get('type') == 'recovery':
        if params.get('access_token') and params.get('refresh_token'):
            # Store tokens and show the reset form
            st.session_state.recovery_token = params.get('access_token')
            st.session_state.refresh_token = params.get('refresh_token')
            st.session_state.show_password_reset_form = True
            st.query_params.clear()
        else:
            # type=recovery is present but tokens are missing
            # This shouldn't happen with the GitHub Pages middleman in place
            st.error("Invalid password reset link. Please request a new one.")

def main():
    # Handle payment redirects
    handle_url_params()

    # Show password reset form if recovery token detected
    if st.session_state.show_password_reset_form:
        st.title("Set New Password")
        new_pass = st.text_input("New Password", type="password", key="recovery_password")
        confirm_pass = st.text_input("Confirm Password", type="password", key="recovery_confirm")
        
        if st.button("Set New Password"):
            if not new_pass or not confirm_pass:
                st.warning("Please fill in both fields")
            elif new_pass != confirm_pass:
                st.error("Passwords don't match")
            elif len(new_pass) < 6:
                st.error("Password must be at least 6 characters")
            else:
                success, error = change_password(new_pass)
                if success:
                    st.success("✅ Password updated! Please sign in with your new password.")
                    st.session_state.show_password_reset_form = False
                    st.query_params.clear()
                else:
                    st.error(f"Error: {error}")
        return  # Stop rendering the rest of the app while resetting password

    with st.sidebar:
        st.image("App-Icon.ico", width=80)
        st.title("IOM Assist")
        st.markdown("---")

        if st.session_state.user is None:
            if not st.session_state.show_signup:
                if st.session_state.show_forgot_password:
                    # Forgot password form
                    st.subheader("Reset Password")
                    st.caption("Enter your email and we'll send you a reset link.")
                    reset_email = st.text_input("Email", key="reset_email")
                    
                    if st.button("Send Reset Link"):
                        if reset_email:
                            with st.spinner("Sending reset link..."):
                                success, error = send_password_reset(reset_email)
                            if success:
                                st.success("✅ Check your email for a reset link!")
                                st.session_state.show_forgot_password = False
                            else:
                                st.error(f"Error: {error}")
                        else:
                            st.warning("Please enter your email")
                    
                    if st.button("← Back to Sign In"):
                        st.session_state.show_forgot_password = False
                        st.rerun()
                else:
                    # Normal login form
                    st.subheader("Sign In")
                    email = st.text_input("Email", key="login_email")
                    password = st.text_input("Password", type="password", key="login_password")

                    if st.button("Sign In"):
                        if email and password:
                            with st.spinner("Signing in..."):
                                success, error = login(email, password)
                            if success:
                                st.rerun()
                            else:
                                st.error("Invalid email or password")
                        else:
                            st.warning("Please enter your email and password")

                    st.markdown("---")
                    if st.button("Forgot Password?"):
                        st.session_state.show_forgot_password = True
                        st.rerun()

                    st.markdown("---")
                    st.caption("Don't have an account?")
                    if st.button("Sign Up"):
                        st.session_state.show_signup = True
                        st.rerun()

            else:
                # Signup form
                st.subheader("Create Account")
                email = st.text_input("Email", key="signup_email")
                password = st.text_input("Password", type="password", key="signup_password")
                confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")

                st.markdown("**Choose your plan:**")
                plan = 'pro'
                st.info("🎉 Start with a **7-day free trial** — no charge until your trial ends!")

                if st.button("Create Account"):
                    if not email or not password:
                        st.warning("Please fill in all fields")
                    elif password != confirm_password:
                        st.error("Passwords don't match")
                    elif len(password) < 6:
                        st.error("Password must be at least 6 characters")
                    else:
                        with st.spinner("Creating account..."):
                            success, checkout_url, error = signup(email, password, plan)
                        if success and checkout_url:
                            st.warning("⚠️ **Important:** Check your email and confirm your account BEFORE completing payment. You will be redirected to payment in 2 seconds.")
                            st.markdown(f'<meta http-equiv="refresh" content="2;url={checkout_url}">', unsafe_allow_html=True)
                        elif success:
                            st.success("✅ Account created! Please check your email to confirm your account, then sign in.")
                            st.session_state.show_signup = False
                        else:
                            st.error(f"Error: {error}") 

                st.markdown("---")
                if st.button("← Back to Sign In"):
                    st.session_state.show_signup = False
                    st.rerun()

        else:
            # Logged in state
            st.success(f"✅ {st.session_state.user.email}")
            st.caption(f"Plan: {st.session_state.user_role.upper()}")
            
            if st.button("Logout"):
                logout()
                st.rerun()
            
            st.markdown("---")
            
            # Password change form
            with st.expander("🔑 Change Password"):
                new_password = st.text_input("New Password", type="password", key="new_password")
                confirm_new = st.text_input("Confirm New Password", type="password", key="confirm_new_password")
                if st.button("Update Password"):
                    if not new_password or not confirm_new:
                        st.warning("Please fill in both fields")
                    elif new_password != confirm_new:
                        st.error("Passwords don't match")
                    elif len(new_password) < 6:
                        st.error("Password must be at least 6 characters")
                    else:
                        with st.spinner("Updating password..."):
                            success, error = change_password(new_password)
                        if success:
                            st.success("✅ Password updated!")
                        else:
                            st.error(f"Error: {error}")
            
            st.markdown("---")
            st.subheader("Quick Actions")

            preset_questions = [
                "What are normal baseline values for SSEPs?",
                "How to troubleshoot poor waveform quality?",
                "Anesthesia effects on neuromonitoring",
                "MEP stimulation parameters",
                "When to notify the surgeon?"
            ]

            for question in preset_questions:
                if st.button(question, key=f"preset_{question[:20]}"):
                    st.session_state.messages.append({"role": "user", "content": question})
                    with st.spinner("Getting response..."):
                        response = call_n8n_webhook(question)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.rerun()

    

    # Main content area
    if st.session_state.user is not None:
        col1, col2 = st.columns([1, 6])
        with col1:
            st.image("App-Icon.ico", width=80)
        with col2:
            st.title("IOM Assist")
        st.markdown("Ask me anything about intraoperative neuromonitoring techniques, troubleshooting, or protocols.")

        chat_container = st.container()
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        if len(st.session_state.messages) > st.session_state.last_message_count:
            st.session_state.last_message_count = len(st.session_state.messages)
            st.markdown(
                """
                <script>
                    window.scrollTo(0, document.body.scrollHeight);
                </script>
                """,
                unsafe_allow_html=True
            )

        # Check access
        if has_chat_access():
            if prompt := st.chat_input("Ask your IONM question..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.spinner("Analyzing your question..."):
                    response = call_n8n_webhook(prompt)
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()

            if st.session_state.messages:
                if st.button("Clear Chat History"):
                    st.session_state.messages = []
                    st.session_state.last_message_count = 0
                    st.rerun()
        else:
            # Free user upgrade prompt
            st.markdown("---")
            st.warning("🔒 Chat access requires a Pro subscription.")
            st.markdown("**Upgrade to Pro** to get full access to IOM Assist:")
            st.markdown("- Unlimited IONM questions")
            st.markdown("- Real-time AI responses")
            st.markdown("- 24/7 availability")
            if st.button("⬆️ Upgrade to Pro - $29.95/month"):
                checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                 'price': os.getenv('STRIPE_PRO_PRICE_ID'),
                 'quantity': 1,
                 }],
                 mode='subscription',
                subscription_data={
                     'trial_period_days': 7
                },
                success_url=f"{os.getenv('APP_URL', 'https://iomassist.com')}?payment=success",
                cancel_url=f"{os.getenv('APP_URL', 'https://iomassist.com')}?payment=cancelled",
                 customer_email=st.session_state.user.email,
)
                
                st.markdown(f'<meta http-equiv="refresh" content="0;url={checkout_session.url}">', unsafe_allow_html=True)
                st.info("Redirecting to payment...")

    else:
        col1, col2 = st.columns([1, 6])
        with col1:
            st.image("App-Icon.ico", width=80)
        with col2:
            st.title("IOM Assist")
        st.markdown("""
        ### Welcome to IOM Assist

        Your AI-powered companion for intraoperative neuromonitoring questions.

        **Features:**
        - Real-time answers to technical questions
        - Protocol guidance and troubleshooting
        - Evidence-based recommendations
        - 24/7 availability

        Please sign in using the sidebar to begin.
        """)

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