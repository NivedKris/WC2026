from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import socket
from flask_mail import Mail, Message
import requests
import threading
import time
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import json
from dotenv import load_dotenv
import hashlib
from flask_compress import Compress
import requests
import re
from authlib.integrations.flask_client import OAuth

load_dotenv()
app = Flask(__name__, static_folder="static", static_url_path="/static")
Compress(app)
# Expose certain environment helpers to Jinja templates.
# Templates previously attempted to call os.getenv(...) directly which
# raises UndefinedError unless the os module or variables are injected.
app.jinja_env.globals.update(
    os=os,
    UPI_ID=os.getenv('UPI_ID')
)
@app.after_request
def add_header(response):
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=31536000'
    return response


app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Hosted/development redirect configuration for OAuth
# Use ISDEV env var to control whether we use a local redirect (development)
# or the hosted production redirect (e.g. https://wc2026.onrender.com/callback)
HOSTED_URL = os.getenv('HOSTED_URL', 'https://wc2026.onrender.com')
# ISDEV: treat missing value as True for local development; set ISDEV=false in production
ISDEV = os.getenv('ISDEV', 'True').lower() in ('1', 'true', 'yes')
DEV_REDIRECT_URL = os.getenv('DEV_REDIRECT_URL', f'http://localhost:8000/callback')
PROD_REDIRECT_URL = os.getenv('PROD_REDIRECT_URL', f'{HOSTED_URL}/callback')

# Configure session cookie behavior so the OAuth state cookie survives the
# cross-site redirect back from Google. Browsers require 'Secure' when
# using 'SameSite=None'. For local development we keep 'Lax' to avoid needing
# HTTPS. In production (ISDEV=False) we set SameSite=None and Secure=True.
if ISDEV:
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
else:
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# OAuth (Google) configuration
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    # Use OpenID Connect discovery so Authlib can find jwks_uri and endpoints
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    # Register a default redirect_uri here (picked from env). Authlib will
    # include this value when building the authorization request if
    # authorize_redirect() is called without an explicit redirect_uri.
    redirect_uri=(DEV_REDIRECT_URL if ISDEV else PROD_REDIRECT_URL),
    client_kwargs={'scope': 'openid email profile'},
)

# Flask optimizations for production
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # Cache static files for 1 year (in seconds)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max request size

# MongoDB Atlas configuration
MONGODB_URI = os.getenv('MONGODB_URI')
client = MongoClient(MONGODB_URI)
db = client['wc2026']

# Collections
users_collection = db['users']
nations_collection = db['nations']
monthly_payments_collection = db['monthly_payments']
user_stats_collection = db['user_stats']
winner_claims_collection = db['winner_claims']
app_settings_collection = db['app_settings']


@app.route('/wake-webhook', methods=['GET'])
def wake_webhook():
    """Server-side wake endpoint: performs a simple GET to the configured
    external webhook and returns a JSON summary. Uses a 50s timeout to allow
    cold-starts on the external service.
    """
    webhook = os.getenv('PAYMENT_WEBHOOK_URL', 'https://sms-webhook-9l8c.onrender.com')
    try:
        resp = requests.get(webhook, timeout=50)
        # Try to parse JSON body if present
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:1000]
        return jsonify({'ok': resp.status_code == 200, 'status': resp.status_code, 'body': body}), resp.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'ok': False, 'error': str(e)}), 502

# Razorpay is deprecated in this deployment; keep placeholders in env for compatibility but do not initialize client
try:
    import razorpay  # optional dependency
    RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID')
    RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET')
    # do not create a razorpay.Client to avoid network calls in environments without keys
    razorpay_client = None
except Exception:
    razorpay_client = None

# Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('GMAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('GMAIL_APP_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)

# --- Startup ping to wake external webhook(s) on application start ---
# Configure one or more comma-separated URLs via STARTUP_PING_URLS env var.
STARTUP_PING_URLS = os.getenv('STARTUP_PING_URLS', 'https://sms-webhook-9l8c.onrender.com/')

def _ping_startup_urls():
    """Background worker that pings configured URLs once at startup.
    Runs as a daemon thread so it does not block application start.
    Retries a few times on transient failures and logs results to stdout.
    """
    urls = [u.strip() for u in (STARTUP_PING_URLS or '').split(',') if u and u.strip()]
    if not urls:
        return

    for url in urls:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                print(f"startup-ping: attempting GET {url} (attempt {attempt}/{attempts})")
                resp = requests.get(url, timeout=10)
                print(f"startup-ping: {url} responded {resp.status_code}")
                # Stop retrying this URL on success (2xx/3xx)
                if 200 <= resp.status_code < 400:
                    break
            except Exception as e:
                print(f"startup-ping: attempt {attempt} failed for {url}: {e}")
                if attempt < attempts:
                    time.sleep(2)
                else:
                    print(f"startup-ping: giving up on {url}")

# Start the ping thread (do not block import/startup)
try:
    threading.Thread(target=_ping_startup_urls, daemon=True).start()
except Exception as e:
    print('startup-ping: failed to start ping thread:', e)


# Password hashing function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Email sending functions
def send_email(subject, recipients, html_body):
    import traceback
    try:
        # Normalize recipients: allow a single string or iterable; filter out falsy values
        if recipients is None:
            print('send_email called with recipients=None')
            return False

        # If a single string (one email) was passed, wrap in list
        if isinstance(recipients, str):
            recip_list = [recipients]
        else:
            try:
                recip_list = list(recipients)
            except Exception:
                # Not iterable
                print('send_email: recipients is not iterable:', type(recipients))
                return False

        # Filter out invalid entries
        recip_list = [r for r in recip_list if r]
        if not recip_list:
            print('send_email: no valid recipient addresses after filtering')
            return False

        # If BREVO_API_KEY is configured, send via Brevo's SMTP API (HTTP)
        brevo_api_key = os.getenv('BREVO_API_KEY')
        use_brevo = os.getenv('USE_BREVO', 'False').lower() in ('1', 'true', 'yes')

        if brevo_api_key or use_brevo:
            # Prefer explicit BREVO_API_KEY, but if USE_BREVO is true and no key
            # is configured we'll fail early with a clear message.
            if not brevo_api_key:
                print('send_email: BREVO requested via USE_BREVO but BREVO_API_KEY is not set')
                return False

            brevo_url = 'https://api.brevo.com/v3/smtp/email'
            headers = {
                'accept': 'application/json',
                'api-key': brevo_api_key,
                'content-type': 'application/json'
            }

            # Build payload
            sender_email = app.config.get('MAIL_DEFAULT_SENDER') or os.getenv('MAIL_DEFAULT_SENDER') or 'no-reply@wc2026.onrender.com'
            sender_name = os.getenv('MAIL_SENDER_NAME', 'WC2026')
            to_list = [{'email': r} for r in recip_list]

            payload = {
                'sender': {'name': sender_name, 'email': sender_email},
                'to': to_list,
                'subject': subject,
                'htmlContent': html_body
            }

            try:
                resp = requests.post(brevo_url, json=payload, headers=headers, timeout=10)
                if resp.status_code in (200, 201):
                    return True
                else:
                    print(f'send_email: Brevo API error {resp.status_code}: {resp.text}')
                    return False
            except Exception as e:
                print('send_email: Brevo request failed:', e)
                return False

        # Fallback: send using configured SMTP (Flask-Mail). Keep the TCP pre-check
        mail_server = app.config.get('MAIL_SERVER')
        mail_port = app.config.get('MAIL_PORT')
        try:
            if mail_server:
                sock = socket.create_connection((mail_server, int(mail_port)), timeout=5)
                sock.close()
        except Exception as conn_err:
            print(f'send_email: cannot connect to SMTP {mail_server}:{mail_port} - {conn_err}')
            return False

        # Ensure Message creation and sending happen inside an application context
        with app.app_context():
            msg = Message(subject, recipients=recip_list)
            msg.html = html_body
            mail.send(msg)
        return True
    except Exception as e:
        print('Error sending email:', e)
        print(traceback.format_exc())
        return False

def send_signup_email(email, username):
    subject = "Welcome to WC 2026!"
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                <h1 style="color: #1173d4;">Welcome to WC 2026! 🎉</h1>
                <p style="color: #fbbf24; font-size: 16px; font-style: italic; font-weight: bold;">May Your Nation Lead You to Glory</p>
                <p>Hi <strong>{username}</strong>,</p>
                <p>Thank you for signing up! You're now part of our exclusive World Cup supporter community.</p>
                <h3>Next Steps:</h3>
                <ol>
                    <li>Select your favorite nation to support</li>
                    <li>Make your first monthly payment of ₹50</li>
                    <li>Join the leaderboard and compete with other fans!</li>
                </ol>
                <p>If your nation wins the World Cup 2026, you'll share in the prize pool with all supporters of the winning team!</p>
                <p style="margin-top: 30px;">Best regards,<br><strong>WC 2026 Team</strong></p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)

def send_payment_reminder(email, username, month_year, reminder_type='start'):
    """Send a reminder email to a single user. reminder_type in ('start','end') affects wording."""
    subject = f"Payment Reminder - {month_year}"
    app_link = 'https://wc2026.onrender.com/'
    if reminder_type == 'end':
        lead = f"It's almost the end of {month_year}."
        cta_text = 'Pay now to ensure your support is recorded for this month'
    else:
        lead = f"Welcome to {month_year}."
        cta_text = 'Please make your monthly payment to support your nation'

    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                <h2 style="color: #1173d4;">Monthly Payment Reminder 💰</h2>
                <p>Hi <strong>{username}</strong>,</p>
                <p>{lead} This is a friendly reminder that your monthly payment of <strong>₹50</strong> for <strong>{month_year}</strong> is still outstanding.</p>
                <p style="font-weight:600;">{cta_text}.</p>
                <p style="margin-top:12px;"><a href="{app_link}" style="display: inline-block; background-color: #1173d4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 6px;">Open WC2026 App</a></p>
                <p style="margin-top: 20px;">Best regards,<br><strong>WC 2026 Team</strong></p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)


# NoParam email verification helper
def verify_email_with_noparam(email: str, min_score: int = None):
    """Return (is_valid: bool, message: str, details: dict).
    Tries NOPARAM_API_KEY first and falls back to NOPARAM_API_KEY1 if provided.
    If no keys are configured, verification is skipped (signup allowed).
    On API/network errors for a key, the function will try the next key.

    IMPORTANT: This function enforces that details.mailbox_exists must be True
    for the email to be accepted. If mailbox_exists is False (or MX records are
    missing), the function returns (False, message, details).
    """
    # Allow overriding min_score via env var; default to 80 if not provided
    if min_score is None:
        try:
            min_score = int(os.getenv('NOPARAM_MIN_SCORE', '80'))
        except Exception:
            min_score = 80

    # NoParam email verification removed. We keep a lightweight local format check
    # and allow signup to proceed. If you want to re-enable a third-party
    # verification service later, implement it here and return the same tuple
    # signature (is_valid: bool, message: str, details: dict).
    return (True, 'Email verification disabled (use Google OAuth for signup)', {})


def is_valid_email_format(email: str) -> bool:
    """Basic regex check for email format. Not exhaustive, just filters obvious invalid strings."""
    if not email or len(email) > 254:
        return False
    # Simple RFC-like regex (not full RFC5322, but practical)
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return re.match(pattern, email) is not None

def send_payment_approved(email, username, month_year, amount):
    subject = f"Payment Approved - {month_year}"
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                <h2 style="color: #059669;">Payment Approved ✓</h2>
                <p>Hi <strong>{username}</strong>,</p>
                <p>Great news! Your payment of <strong>₹{amount}</strong> for <strong>{month_year}</strong> has been approved.</p>
                <p>Thank you for supporting your nation! Keep up the momentum!</p>
                <p style="margin-top: 30px;">Best regards,<br><strong>WC 2026 Team</strong></p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)


def _safe_send_payment_approved(email, username, month_year, amount=50.00):
    """Helper wrapper to call send_payment_approved from background threads with robust logging."""
    import traceback
    try:
        print(f"_safe_send_payment_approved: preparing to send to={email} user={username} month={month_year}")
        if not email:
            print("_safe_send_payment_approved: no email address provided, aborting send")
            return False
        result = send_payment_approved(email, username, month_year, amount)
        print(f"_safe_send_payment_approved: send result={result}")
        return result
    except Exception as e:
        print("_safe_send_payment_approved: exception while sending:", e)
        print(traceback.format_exc())
        return False

def send_payment_rejected(email, username, month_year):
    subject = f"Payment Issue - {month_year}"
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                <h2 style="color: #dc2626;">Payment Not Approved</h2>
                <p>Hi <strong>{username}</strong>,</p>
                <p>Unfortunately, your payment for <strong>{month_year}</strong> could not be approved.</p>
                <p>Please contact support or try submitting your payment again.</p>
                <p style="margin-top: 30px;">Best regards,<br><strong>WC 2026 Team</strong></p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)

def send_reward_approved(email, username, amount):
    subject = "Reward Approved - Congratulations! 🎉"
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #fef3c7; padding: 30px; border-radius: 10px; border: 3px solid #fbbf24;">
                <h1 style="color: #92400e;">🏆 CONGRATULATIONS! 🏆</h1>
                <p>Hi <strong>{username}</strong>,</p>
                <p style="font-size: 18px;">Your reward claim of <strong style="color: #059669; font-size: 24px;">₹{amount}</strong> has been approved!</p>
                <p>Your nation won the World Cup and you're a winner! 🎉</p>
                <p style="margin-top: 30px;">Best regards,<br><strong>WC 2026 Team</strong></p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)

def send_admin_notification(subject, body):
    admin_email = os.getenv('ADMIN_EMAIL', 'nithupd@gmail.com')
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                <h2 style="color: #1173d4;">Admin Notification</h2>
                <p>{body}</p>
                <p style="margin-top: 30px;">WC 2026 System</p>
            </div>
        </body>
    </html>
    """

    # Helper that sends synchronously and returns success boolean
    def _send_sync():
        try:
            return send_email(subject, [admin_email], html)
        except Exception as e:
            print('Error sending admin notification:', e)
            return False

    # Attempt to send in a background thread by default to avoid blocking web requests
    try:
        import threading
        t = threading.Thread(target=_send_sync, daemon=True)
        t.start()
        return True
    except Exception as e:
        # Fallback to synchronous send if threads can't be started
        print('Could not start admin notify thread, sending synchronously:', e)
        return _send_sync()


# Informational pages and contact form
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')

        subject = f"Contact Form Message from {name or email}"
        html = f"""
        <p><strong>From:</strong> {name or 'N/A'} &lt;{email or 'N/A'}&gt;</p>
        <p><strong>Message:</strong></p>
        <div>{(message or '').replace('\n','<br/>')}</div>
        """

        # Notify admin (non-blocking)
        try:
            send_admin_notification(subject, html)
        except Exception as e:
            print('contact: admin notify failed', e)

        # Send confirmation to user (non-blocking) with WC 2026 wording
        try:
            import threading
            def _send_user_confirm():
                try:
                    subject = 'Message received — WC 2026'
                    html = f"""
                    <p>Hi {name or ''},</p>
                    <p>Thanks for contacting WC 2026. We have received your message and will respond within 2–3 working days.</p>
                    <p>If your message is about a payment issue, please include your transaction reference so we can investigate quickly.</p>
                    <p>Best regards,<br><strong>WC 2026 Team</strong></p>
                    """
                    send_email(subject, [email], html)
                except Exception as e:
                    print('contact: user confirmation failed', e)
            threading.Thread(target=_send_user_confirm, daemon=True).start()
        except Exception as e:
            print('contact: could not spawn confirmation thread', e)

        return render_template('contact.html', success='Your message was sent. We will respond shortly.')

    return render_template('contact.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html')

@app.route('/shipping-policy')
def shipping_policy():
    return render_template('shipping_policy.html')

def send_winner_announcement_to_winners(winning_nation):
    """Send email to all users who supported the winning nation"""
    winners = list(users_collection.find(
        {'nation': winning_nation},
        {'username': 1, 'email': 1}
    ))
    
    # Calculate reward info
    pipeline = [
        {'$match': {'status': 'completed'}},
        {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
    ]
    result = list(monthly_payments_collection.aggregate(pipeline))
    total_pool = result[0]['total'] if result else 0
    winner_count = len(winners)
    reward_per_person = round(total_pool / winner_count, 2) if winner_count > 0 else 0
    
    for winner in winners:
        username = winner['username']
        email = winner['email']
        subject = f"🏆 CONGRATULATIONS! {winning_nation} Won the World Cup!"
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #fef3c7;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px; border: 4px solid #fbbf24;">
                    <div style="text-align: center;">
                        <h1 style="color: #92400e; font-size: 36px;">🏆 CONGRATULATIONS! 🏆</h1>
                        <h2 style="color: #1173d4;">{winning_nation} Won the World Cup 2026!</h2>
                    </div>
                    <p style="font-size: 18px;">Hi <strong>{username}</strong>,</p>
                    <p style="font-size: 16px; line-height: 1.6;">
                        Amazing news! Your nation <strong style="color: #059669;">{winning_nation}</strong> has won the World Cup 2026! 🎉
                    </p>
                    <div style="background-color: #dcfce7; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
                        <p style="margin: 0; font-size: 16px;">Your Reward Amount:</p>
                        <p style="margin: 10px 0; font-size: 32px; font-weight: bold; color: #059669;">₹{reward_per_person}</p>
                        <p style="margin: 0; font-size: 14px; color: #666;">Total Pool: ₹{total_pool} | Winners: {winner_count}</p>
                    </div>
                    <p style="font-size: 16px;">
                        <strong>Next Step:</strong> Login to your dashboard and claim your reward now!
                    </p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="#" style="display: inline-block; background-color: #059669; color: white; padding: 15px 40px; text-decoration: none; border-radius: 8px; font-size: 16px; font-weight: bold;">Claim Your Reward</a>
                    </div>
                    <p style="margin-top: 30px; font-size: 14px; color: #666;">
                        Best regards,<br><strong>WC 2026 Team</strong>
                    </p>
                </div>
            </body>
        </html>
        """
        send_email(subject, [email], html)

def send_winner_announcement_to_losers(winning_nation):
    """Send email to all users who did NOT support the winning nation"""
    losers = list(users_collection.find(
        {
            'nation': {'$ne': None, '$ne': winning_nation}
        },
        {'username': 1, 'email': 1, 'nation': 1}
    ))
    
    for loser in losers:
        username = loser['username']
        email = loser['email']
        their_nation = loser['nation']
        subject = f"World Cup 2026 Winner Announced - {winning_nation}"
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                    <h2 style="color: #1173d4;">World Cup 2026 Winner Announced</h2>
                    <p>Hi <strong>{username}</strong>,</p>
                    <p>The World Cup 2026 has concluded and the winner has been announced!</p>
                    <div style="background-color: #fef3c7; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
                        <p style="font-size: 24px; font-weight: bold; color: #92400e; margin: 0;">🏆 {winning_nation} 🏆</p>
                    </div>
                    <p>You supported <strong>{their_nation}</strong>. While your team didn't win this time, thank you for being part of the WC 2026 community!</p>
                    <p style="font-size: 20px; margin-top: 30px;"><strong>Better luck next time! ⚽</strong></p>
                    <p>We hope to see you at the next World Cup!</p>
                    <p style="margin-top: 30px; font-size: 14px; color: #666;">
                        Best regards,<br><strong>WC 2026 Team</strong>
                    </p>
                </div>
            </body>
        </html>
        """
        send_email(subject, [email], html)

def send_missed_payment_warning(email, username, missed_months):
    """Send warning email when user has missed payments"""
    subject = f"⚠️ Payment Reminder - {len(missed_months)} Month(s) Unpaid"
    
    missed_list = "<br>".join([f"• <strong>{month}</strong>" for month in missed_months])
    
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px; border: 3px solid #ef4444;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <span style="font-size: 48px;">⚠️</span>
                    <h2 style="color: #dc2626; margin: 10px 0;">Missed Payment Alert!</h2>
                </div>
                
                <p style="font-size: 16px;">Hi <strong>{username}</strong>,</p>
                
                <p style="font-size: 16px; line-height: 1.6;">
                    We noticed you have <strong style="color: #dc2626;">{len(missed_months)} unpaid month(s)</strong> for your nation support.
                </p>
                
                <div style="background-color: #fee2e2; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ef4444;">
                    <p style="margin: 0 0 10px 0; font-weight: bold; color: #991b1b;">Missed Months:</p>
                    <p style="margin: 0; line-height: 1.8;">{missed_list}</p>
                </div>
                
                <p style="font-size: 16px; line-height: 1.6;">
                    <strong>Don't worry!</strong> You can still make backpayments and catch up. Every month counts towards:
                </p>
                
                <ul style="font-size: 15px; line-height: 1.8; color: #374151;">
                    <li>🏆 <strong>Leaderboard Rankings</strong> - Compete with other supporters</li>
                    <li>⭐ <strong>Premium Status</strong> - Unlock after 3 months</li>
                    <li>💰 <strong>Prize Eligibility</strong> - Share in winnings if your nation wins</li>
                    <li>📊 <strong>Support Stats</strong> - Show your dedication</li>
                </ul>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="#" style="display: inline-block; background-color: #dc2626; color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        Login & Pay Now
                    </a>
                </div>
                
                <p style="font-size: 14px; color: #6b7280; margin-top: 20px;">
                    <strong>Payment Amount:</strong> ₹50 per month<br>
                    <strong>Total Due:</strong> ₹{len(missed_months) * 50}
                </p>
                
                <p style="margin-top: 30px; font-size: 14px; color: #666;">
                    Best regards,<br><strong>WC 2026 Team</strong>
                </p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)

def send_monthly_reminder_to_all(reminder_type='start'):
    """Send monthly payment reminder to all users at start/end of month.
    reminder_type: 'start' or 'end' (affects email wording). Returns number of reminders sent.
    """
    current_month = get_current_month_year()

    # Get all users who have a nation
    all_users = list(users_collection.find(
        {'nation': {'$ne': None}},
        {'_id': 1, 'username': 1, 'email': 1}
    ))

    # Get user IDs who have already paid or have pending payment for current month
    paid_user_ids = [
        p['user_id'] for p in monthly_payments_collection.find(
            {
                'month_year': current_month,
                'status': {'$in': ['completed', 'pending']}
            },
            {'user_id': 1}
        )
    ]

    # Send reminder to users who haven't paid
    sent = 0
    # Batch send: send in chunks to avoid SMTP throttling
    BATCH_SIZE = 50
    SLEEP_BETWEEN_BATCHES = 1  # seconds
    to_send = [u for u in all_users if str(u['_id']) not in paid_user_ids]
    import time
    for i in range(0, len(to_send), BATCH_SIZE):
        batch = to_send[i:i+BATCH_SIZE]
        for user in batch:
            try:
                send_payment_reminder(user['email'], user['username'], current_month, reminder_type=reminder_type)
                sent += 1
            except Exception as e:
                print(f'Failed to send reminder to {user.get("email")}: {e}')
                continue
        # brief pause between batches
        if i + BATCH_SIZE < len(to_send):
            time.sleep(SLEEP_BETWEEN_BATCHES)

    # Log run
    try:
        reminder_runs_collection = db['reminder_runs']
        reminder_runs_collection.insert_one({
            'run_at': datetime.now(),
            'mode': reminder_type,
            'month': current_month,
            'sent': sent,
            'total_candidates': len(to_send)
        })
    except Exception as e:
        print('Failed to write reminder run log:', e)

    return sent


@app.route('/admin/run-monthly-reminders', methods=['POST'])
def admin_run_monthly_reminders():
    """Admin-only endpoint to trigger monthly reminders on demand (returns JSON report)."""
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'unauthorized'}), 403

    # Accept JSON or form 'mode' parameter: 'start' or 'end'
    data = request.get_json() or {}
    mode = data.get('mode') or request.form.get('mode') or 'start'
    mode = mode if mode in ('start', 'end') else 'start'

    sent = send_monthly_reminder_to_all(reminder_type=mode)

    # Notify admin of reminder summary
    send_admin_notification('Monthly Reminders Sent', f'Reminders sent to {sent} users for {get_current_month_year()} (mode={mode}).')
    return jsonify({'status': 'ok', 'reminders_sent': sent, 'mode': mode})


@app.route('/admin/reminder-status')
def admin_reminder_status():
    """Return last reminder run info for display in admin panel."""
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'unauthorized'}), 403
    reminder_runs_collection = db['reminder_runs']
    last = reminder_runs_collection.find().sort('run_at', -1).limit(1)
    last = list(last)
    if not last:
        return jsonify({'status': 'ok', 'last_run': None})
    lr = last[0]
    return jsonify({'status': 'ok', 'last_run': {
        'run_at': lr['run_at'].isoformat(),
        'mode': lr.get('mode'),
        'month': lr.get('month'),
        'sent': lr.get('sent'),
        'total_candidates': lr.get('total_candidates')
    }})


def _monthly_scheduler_loop():
    """Background thread that waits until the first of each month and runs reminders."""
    import time
    while True:
        now = datetime.now()
        # compute next run at 00:10 on first day of next month
        year = now.year + (1 if now.month == 12 else 0)
        month = 1 if now.month == 12 else now.month + 1
        next_run = datetime(year, month, 1, 0, 10, 0)
        wait_seconds = (next_run - now).total_seconds()
        if wait_seconds <= 0:
            # if we missed (rare), run now and loop
            try:
                send_monthly_reminder_to_all()
            except Exception as e:
                print('Error running monthly reminders:', e)
            time.sleep(60)
            continue
        # sleep until next_run
        time.sleep(wait_seconds)
        try:
            send_monthly_reminder_to_all()
            print(f'Monthly reminders executed for {get_current_month_year()}')
        except Exception as e:
            print('Error running monthly reminders:', e)


# Database initialization
def init_db():
    # MongoDB initialization - Create indexes for performance
    
    # Create indexes for users collection
    users_collection.create_index('username', unique=True)
    users_collection.create_index('email')
    
    # Create indexes for nations collection
    nations_collection.create_index('name', unique=True)
    
    # Create indexes for monthly_payments collection
    monthly_payments_collection.create_index([('user_id', 1), ('month_year', 1)])
    monthly_payments_collection.create_index('status')
    
    # Create indexes for user_stats collection
    user_stats_collection.create_index('user_id', unique=True)
    
    # Create indexes for winner_claims collection
    winner_claims_collection.create_index('user_id')
    winner_claims_collection.create_index('status')
    
    # Insert default nations (FIFA World Cup 2026 Top Teams)
    nations = [
        {'name': 'Spain', 'flag_url': 'https://flagcdn.com/w320/es.png', 'supporter_count': 0},
        {'name': 'France', 'flag_url': 'https://flagcdn.com/w320/fr.png', 'supporter_count': 0},
        {'name': 'England', 'flag_url': 'https://flagcdn.com/w320/gb-eng.png', 'supporter_count': 0},
        {'name': 'Brazil', 'flag_url': 'https://flagcdn.com/w320/br.png', 'supporter_count': 0},
        {'name': 'Argentina', 'flag_url': 'https://flagcdn.com/w320/ar.png', 'supporter_count': 0},
        {'name': 'Germany', 'flag_url': 'https://flagcdn.com/w320/de.png', 'supporter_count': 0},
        {'name': 'Portugal', 'flag_url': 'https://flagcdn.com/w320/pt.png', 'supporter_count': 0},
        {'name': 'Netherlands', 'flag_url': 'https://flagcdn.com/w320/nl.png', 'supporter_count': 0},
        {'name': 'Italy', 'flag_url': 'https://flagcdn.com/w320/it.png', 'supporter_count': 0},
        {'name': 'Uruguay', 'flag_url': 'https://flagcdn.com/w320/uy.png', 'supporter_count': 0},
        {'name': 'Belgium', 'flag_url': 'https://flagcdn.com/w320/be.png', 'supporter_count': 0},
        {'name': 'Colombia', 'flag_url': 'https://flagcdn.com/w320/co.png', 'supporter_count': 0},
        {'name': 'Mexico', 'flag_url': 'https://flagcdn.com/w320/mx.png', 'supporter_count': 0},
        {'name': 'United States', 'flag_url': 'https://flagcdn.com/w320/us.png', 'supporter_count': 0},
        {'name': 'Norway', 'flag_url': 'https://flagcdn.com/w320/no.png', 'supporter_count': 0},
        {'name': 'Croatia', 'flag_url': 'https://flagcdn.com/w320/hr.png', 'supporter_count': 0},
        {'name': 'Denmark', 'flag_url': 'https://flagcdn.com/w320/dk.png', 'supporter_count': 0},
        {'name': 'Japan', 'flag_url': 'https://flagcdn.com/w320/jp.png', 'supporter_count': 0},
        {'name': 'Switzerland', 'flag_url': 'https://flagcdn.com/w320/ch.png', 'supporter_count': 0},
        {'name': 'Morocco', 'flag_url': 'https://flagcdn.com/w320/ma.png', 'supporter_count': 0},
        {'name': 'Canada', 'flag_url': 'https://flagcdn.com/w320/ca.png', 'supporter_count': 0},
        {'name': 'Sweden', 'flag_url': 'https://flagcdn.com/w320/se.png', 'supporter_count': 0},
        {'name': 'Austria', 'flag_url': 'https://flagcdn.com/w320/at.png', 'supporter_count': 0},
        {'name': 'Ecuador', 'flag_url': 'https://flagcdn.com/w320/ec.png', 'supporter_count': 0}
    ]
    
    # Insert nations only if collection is empty
    if nations_collection.count_documents({}) == 0:
        nations_collection.insert_many(nations)
    
    # Insert admin user with hashed password if not exists
    if not users_collection.find_one({'username': 'admin'}):
        users_collection.insert_one({
            'username': 'admin',
            'password': hash_password('admin@2025wc!'),
            'email': 'nithupd@gmail.com',
            'nation': None,
            'avatar_url': 'default_avatar.png',
            'theme_color': '#1173d4',
            'is_premium': False,
            'is_admin': True,
            'created_at': datetime.now()
        })
    
    # Insert default app settings if not exists
    if app_settings_collection.count_documents({}) == 0:
        app_settings_collection.insert_one({
            'winning_nation': None,
            'winner_declared_at': None,
            'declared_by': None
        })

    # Sanitize existing avatar_url values: replace any that look like full external
    # URLs (for example Google profile picture URLs) with a random local avatar
    # filename so templates that concatenate `/static/avatars/` will not produce
    # invalid paths like `/static/avatars/https://...`.
    try:
        import random, re
        # Find users whose avatar_url starts with http:// or https://
        users_cursor = users_collection.find({'avatar_url': {'$regex': '^https?://'}})
        for u in users_cursor:
            new_avatar = f"avatar{random.randint(1,25)}.png"
            users_collection.update_one({'_id': u['_id']}, {'$set': {'avatar_url': new_avatar}})
        # Ensure documents missing avatar_url get a default
        users_collection.update_many({'avatar_url': {'$exists': False}}, {'$set': {'avatar_url': 'default_avatar.png'}})
    except Exception as e:
        print('init_db: avatar sanitation failed:', e)

def get_current_month_year():
    return datetime.now().strftime("%B %Y")

def get_months_until_world_cup():
    world_cup_date = datetime(2026, 7, 19)
    current_date = datetime.now()
    months = []
    
    temp_date = current_date.replace(day=1)
    while temp_date < world_cup_date:
        months.append(temp_date.strftime("%B %Y"))
        if temp_date.month == 12:
            temp_date = temp_date.replace(year=temp_date.year + 1, month=1)
        else:
            temp_date = temp_date.replace(month=temp_date.month + 1)
    
    return months

def get_winning_nation():
    result = app_settings_collection.find_one({})
    return result['winning_nation'] if result and 'winning_nation' in result else None

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    """Render the login page. Manual username/password login is disabled; users should
    sign in with Google via the provided button. The Google OAuth flow is started at
    `/login/google`.
    """
    return render_template('login.html')


@app.route('/login/google')
def login_google():
    """Redirect to Google's OAuth 2.0 authorization endpoint."""
    # Generate a nonce for OIDC ID token validation and store in session
    import secrets
    nonce = secrets.token_urlsafe(16)
    session['oauth_nonce'] = nonce

    # We rely on Authlib to generate and manage the OAuth2 state value.
    # Generating a separate application-level `oauth_state` can conflict
    # with Authlib's internal state handling and cause mismatches.
    state = None

    # Determine redirect URI based on environment flag
    # If DEV_REDIRECT_URL/PROD_REDIRECT_URL were explicitly set in ENV, use them.
    # Otherwise use the current request host via url_for(..., _external=True)
    if ISDEV:
        # Use explicit DEV_REDIRECT_URL only if it was set in the environment
        if 'DEV_REDIRECT_URL' in os.environ:
            redirect_uri = DEV_REDIRECT_URL
        else:
            # Build redirect using current request host (keeps localhost vs 127.0.0.1 consistent)
            redirect_uri = url_for('auth_callback', _external=True)
    else:
        # Use explicit PROD_REDIRECT_URL only if it was set in the environment
        if 'PROD_REDIRECT_URL' in os.environ:
            redirect_uri = PROD_REDIRECT_URL
        else:
            redirect_uri = url_for('auth_callback', _external=True)

    # Debug info to help diagnose state mismatches locally
    try:
        # Print Authlib's internal state keys (they look like `_state_google_<rand>`)
        internal_state_keys = [k for k in session.keys() if k.startswith('_state_')]
        print(f"login_google: redirect_uri={redirect_uri} nonce={nonce} internal_state_keys={internal_state_keys} session_keys={list(session.keys())}")
    except Exception:
        pass

    # Pass the nonce and the explicit state to the authorize call so Google will
    # include them in the response. We intentionally do NOT pass redirect_uri
    # here so Authlib will use the redirect_uri registered above. That keeps
    # the authorization request consistent with the Google Cloud Console
    # client configuration and avoids accidental mismatches caused by
    # differing request hosts.
    try:
        return oauth.google.authorize_redirect(nonce=nonce, state=state)
    except TypeError:
        # Older versions of Authlib expected redirect_uri first; fall back to
        # positional call for maximum compatibility.
        return oauth.google.authorize_redirect(nonce, state)


@app.route('/callback')
def auth_callback():
    """Handle the OAuth2 callback from Google, create or lookup the user,
    and establish a session.
    """
    # Debug incoming state vs stored state to diagnose CSRF mismatches
    try:
        incoming_state = request.args.get('state')
        internal_state_keys = [k for k in session.keys() if k.startswith('_state_')]
        print(f"auth_callback: incoming_state={incoming_state} internal_state_keys={internal_state_keys} session_keys={list(session.keys())}")
    except Exception:
        pass

    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        print('Google authorize_access_token failed:', e)
        # If CSRF state mismatch occurs, include debug hint in the template
        return render_template('login.html', error='Google sign-in failed (state mismatch). Try clearing cookies or use the exact host used for redirect URI.')

    # Try to fetch userinfo via the userinfo endpoint
    # Prefer parsing the ID token (OpenID Connect). This avoids relying on
    # the client.get() helper which can fail if api_base_url is not set.
    userinfo = {}
    try:
        # authorize_access_token returns a token dict that includes 'id_token'
        # when using OpenID Connect. parse_id_token will validate and decode it.
        nonce = session.pop('oauth_nonce', None)
        userinfo = oauth.google.parse_id_token(token, nonce=nonce)
    except Exception as id_err:
        print('ID token parse failed, falling back to userinfo endpoint:', id_err)
        try:
            # Fallback: fetch userinfo endpoint from provider metadata
            metadata = oauth.google.load_server_metadata()
            userinfo_endpoint = metadata.get('userinfo_endpoint')
            if userinfo_endpoint:
                # Use the access token when calling the userinfo endpoint
                resp = oauth.google.get(userinfo_endpoint, token=token)
                userinfo = resp.json()
            else:
                print('No userinfo_endpoint found in provider metadata')
        except Exception as e:
            print('Failed fetching userinfo fallback:', e)
            userinfo = {}

    email = userinfo.get('email')
    if not email:
        return render_template('login.html', error='Google did not return an email address')

    # Find existing user by email
    user = users_collection.find_one({'email': email})

    if not user:
        # Create a new user record using Google profile info
        base_username = (userinfo.get('name') or email.split('@')[0]).strip().replace(' ', '_')
        if not base_username:
            base_username = email.split('@')[0]

        username = base_username
        i = 1
        while users_collection.find_one({'username': username}):
            username = f"{base_username}{i}"
            i += 1

        # Assign a local random avatar from the bundled set to avoid storing
        # external URLs (Google profile pictures) which the templates expect
        # to be simple filenames and concatenate with our `/static/avatars/` path.
        # This prevents 404s like `/static/avatars/https://lh3.google...`
        import random
        avatar = f"avatar{random.randint(1,25)}.png"
        try:
            r = users_collection.insert_one({
                'username': username,
                'password': hash_password(os.urandom(24).hex()),  # placeholder random password
                'email': email,
                'nation': None,
                'avatar_url': avatar,
                'theme_color': '#1173d4',
                'is_premium': False,
                'is_admin': False,
                'created_at': datetime.now()
            })
            user_id = str(r.inserted_id)
            user_stats_collection.insert_one({
                'user_id': user_id,
                'months_paid': 0,
                'total_paid': 0.00,
                'last_payment_month': None
            })
            # notify admin about new registration (non-blocking)
            try:
                admin_subject = f"New user registered: {username}"
                admin_body = f"A new user has registered via Google OAuth:<br><br><strong>Username:</strong> {username}<br><strong>Email:</strong> {email}<br><strong>Time:</strong> {datetime.now().isoformat()}"
                # send_admin_notification already starts a background thread by default
                send_admin_notification(admin_subject, admin_body)
            except Exception as e:
                print('Failed to send admin notification for new user:', e)

            # send welcome email (non-blocking)
            try:
                import threading
                threading.Thread(target=lambda e=email, u=username: send_signup_email(e, u), daemon=True).start()
            except Exception:
                try:
                    send_signup_email(email, username)
                except Exception as e:
                    print('Welcome email failed:', e)

            user = users_collection.find_one({'_id': r.inserted_id})
        except Exception as e:
            print('Error creating user from Google profile:', e)
            return render_template('login.html', error='Failed to create user account')
    # If the logged in Google email matches ADMIN_EMAIL, grant admin rights
    admin_email = os.getenv('ADMIN_EMAIL')
    try:
        if admin_email and email.lower() == admin_email.lower():
            # Ensure user document has is_admin True
            users_collection.update_one({'email': email}, {'$set': {'is_admin': True}})
            # Refresh user object
            user = users_collection.find_one({'email': email})
    except Exception as e:
        print('Error setting admin flag for user:', e)

    # Establish session
    session['user_id'] = str(user['_id'])
    session['username'] = user['username']
    session['avatar_url'] = user.get('avatar_url', 'default_avatar.png')
    session['theme_color'] = user.get('theme_color', '#1173d4')
    session['is_premium'] = bool(user.get('is_premium', False))
    session['is_admin'] = bool(user.get('is_admin', False))
    session['nation'] = user.get('nation')

    # If the user is an admin, send them to the admin panel regardless of nation
    if session.get('is_admin'):
        return redirect(url_for('admin_panel'))

    # Redirect new users to nation selection, existing users to dashboard
    if not session.get('nation'):
        return redirect(url_for('select_nation'))
    return redirect(url_for('dashboard'))

@app.route('/signup')
def signup():
    """Render the signup page. Manual username/password signup is disabled; users
    should sign up with Google via the provided button which starts the OAuth flow
    at `/login/google`.
    """
    return render_template('signup.html')

@app.route('/select-nation', methods=['GET', 'POST'])
def select_nation():
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    # Check if user already has a nation in the database
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    
    if user and user.get('nation'):
        session['nation'] = user['nation']
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nation_id = request.form.get('nation_id')
        
        if nation_id:
            nation = nations_collection.find_one({'_id': ObjectId(nation_id)})
            
            if nation:
                # Update user's nation
                users_collection.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {'$set': {'nation': nation['name']}}
                )
                # Update supporter count
                nations_collection.update_one(
                    {'_id': ObjectId(nation_id)},
                    {'$inc': {'supporter_count': 1}}
                )
                
                session['nation'] = nation['name']
                return redirect(url_for('dashboard'))
    
    # Get nations for selection (after POST processing)
    nations_cursor = nations_collection.find({}, {'_id': 1, 'name': 1, 'flag_url': 1})
    # Convert to tuples for template compatibility (id, name, flag_url)
    nations = [(str(n['_id']), n['name'], n['flag_url']) for n in nations_cursor]
    
    return render_template('select_nation.html', nations=nations)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    world_cup_date = datetime(2026, 7, 19)
    now = datetime.now()
    time_left = world_cup_date - now
    winning_nation = get_winning_nation()
    
    # Get user stats
    user_stats_doc = user_stats_collection.find_one({'user_id': session['user_id']})
    user_stats = (
        int(user_stats_doc.get('months_paid', 0)) if user_stats_doc else 0,
        float(user_stats_doc.get('total_paid', 0.00)) if user_stats_doc else 0.00,
        user_stats_doc.get('last_payment_month') if user_stats_doc else None
    )
    
    # Get payment history
    payment_history_cursor = monthly_payments_collection.find(
        {'user_id': session['user_id']},
        {'month_year': 1, 'amount': 1, 'status': 1, 'payment_date': 1, 'approved_at': 1}
    ).sort('payment_date', -1)
    payment_history = []
    for p in payment_history_cursor:
        # Format datetime objects
        payment_date = p['payment_date']
        if isinstance(payment_date, datetime):
            payment_date_str = payment_date.strftime('%Y-%m-%d %H:%M:%S')
        else:
            payment_date_str = str(payment_date) if payment_date else None
        
        approved_at = p.get('approved_at')
        if approved_at and isinstance(approved_at, datetime):
            approved_at_str = approved_at.strftime('%Y-%m-%d %H:%M:%S')
        else:
            approved_at_str = str(approved_at) if approved_at else None
        
        payment_history.append((
            p['month_year'], 
            p['amount'], 
            p['status'], 
            payment_date_str, 
            approved_at_str
        ))
    
    # Get current month payment status
    current_month = get_current_month_year()
    current_payment_doc = monthly_payments_collection.find_one({
        'user_id': session['user_id'],
        'month_year': current_month
    })
    current_payment = (current_payment_doc['status'],) if current_payment_doc else None
    
    # Check if user has pending winner claim
    pending_claim_doc = winner_claims_collection.find_one({
        'user_id': session['user_id'],
        'status': 'pending'
    })
    pending_claim = (pending_claim_doc['status'],) if pending_claim_doc else None
    
    # Check if user can claim reward
    can_claim_reward = False
    if winning_nation and session.get('nation') == winning_nation:
        existing_claim = winner_claims_collection.find_one({
            'user_id': session['user_id'],
            'winning_nation': winning_nation
        })
        can_claim_reward = not existing_claim
    
    # Get top nations
    top_nations_cursor = nations_collection.find(
        {},
        {'name': 1, 'flag_url': 1, 'supporter_count': 1}
    ).sort('supporter_count', -1).limit(7)
    top_nations = [(n['name'], n['flag_url'], n['supporter_count']) for n in top_nations_cursor]
    
    # Get leaderboard using a MongoDB aggregation with $lookup to join user_stats
    # This avoids building the entire user list in Python and is far more
    # efficient for large collections (uses DB sort + skip + limit).
    try:
        try:
            supporters_page = int(request.args.get('supporters_page', '1'))
        except Exception:
            supporters_page = 1
        if supporters_page < 1:
            supporters_page = 1
        PAGE_SIZE = 10

        total_supporters = users_collection.count_documents({'nation': {'$ne': None}})
        total_pages = max(1, (total_supporters + PAGE_SIZE - 1) // PAGE_SIZE)
        if supporters_page > total_pages:
            supporters_page = total_pages
        start_idx = (supporters_page - 1) * PAGE_SIZE

        # Aggregation pipeline: match nation, project fields, lookup stats by converting _id to string
        pipeline = [
            {'$match': {'nation': {'$ne': None}}},
            {'$project': {'username': 1, 'nation': 1, 'avatar_url': 1}},
            {'$addFields': {'_id_str': {'$toString': '$_id'}}},
            {'$lookup': {
                'from': 'user_stats',
                'let': {'uid': '$_id_str'},
                'pipeline': [
                    {'$match': {'$expr': {'$eq': ['$user_id', '$$uid']}}},
                    {'$project': {'months_paid': 1, 'total_paid': 1, '_id': 0}}
                ],
                'as': 'stats'
            }},
            {'$unwind': {'path': '$stats', 'preserveNullAndEmptyArrays': True}},
            {'$addFields': {
                'months_paid': {'$ifNull': ['$stats.months_paid', 0]},
                'total_paid': {'$ifNull': ['$stats.total_paid', 0]}
            }},
            {'$sort': {'months_paid': -1, 'total_paid': -1}},
            {'$skip': start_idx},
            {'$limit': PAGE_SIZE}
        ]

        cursor = users_collection.aggregate(pipeline)
        leaderboard = []
        idx = start_idx
        for u in cursor:
            idx += 1
            leaderboard.append((u.get('username'), u.get('nation'), u.get('avatar_url', 'default_avatar.png'), int(u.get('months_paid', 0)), float(u.get('total_paid', 0.0))))
    except Exception as e:
        print('dashboard: leaderboard aggregation failed, falling back to in-memory (error):', e)
        # Fallback: small dataset approach
        users_with_stats = []
        for user in users_collection.find({'nation': {'$ne': None}}, {'username': 1, 'nation': 1, 'avatar_url': 1}):
            stats = user_stats_collection.find_one({'user_id': str(user['_id'])})
            users_with_stats.append({
                'username': user['username'],
                'nation': user['nation'],
                'avatar_url': user.get('avatar_url', 'default_avatar.png'),
                'months_paid': int(stats.get('months_paid', 0)) if stats else 0,
                'total_paid': float(stats.get('total_paid', 0.00)) if stats else 0.00
            })

        users_with_stats.sort(key=lambda x: (-x['months_paid'], -x['total_paid']))
        supporters_page = int(request.args.get('supporters_page', '1')) if request.args.get('supporters_page') else 1
        PAGE_SIZE = 10
        total_supporters = len(users_with_stats)
        total_pages = max(1, (total_supporters + PAGE_SIZE - 1) // PAGE_SIZE)
        if supporters_page < 1: supporters_page = 1
        if supporters_page > total_pages: supporters_page = total_pages
        start_idx = (supporters_page - 1) * PAGE_SIZE
        page_slice = users_with_stats[start_idx:start_idx+PAGE_SIZE]
        leaderboard = [(u['username'], u['nation'], u['avatar_url'], u['months_paid'], u['total_paid']) for u in page_slice]
    
    # Calculate missed payments and payment status for all months
    months_until_wc = get_months_until_world_cup()
    current_month_index = months_until_wc.index(current_month) if current_month in months_until_wc else 0
    
    # Get all paid/pending months for this user
    user_payments_cursor = monthly_payments_collection.find(
        {'user_id': session['user_id']},
        {'month_year': 1, 'status': 1}
    )
    user_payments = {p['month_year']: p['status'] for p in user_payments_cursor}
    
    # Identify missed months (previous months that weren't paid)
    missed_months = []
    payment_calendar = []
    
    for i, month in enumerate(months_until_wc):
        status = user_payments.get(month, 'not_paid')
        is_current = (month == current_month)
        is_past = (i < current_month_index)
        
        payment_calendar.append({
            'month': month,
            'status': status,
            'is_current': is_current,
            'is_past': is_past
        })
        
        # Track missed months (past months that are not paid or pending)
        if is_past and status not in ['completed', 'pending']:
            missed_months.append(month)
    
    # Send warning email if there are missed payments (once per login session)
    if missed_months and 'missed_payment_warning_sent' not in session:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        if user and user.get('email'):
            send_missed_payment_warning(user['email'], session['username'], missed_months)
            session['missed_payment_warning_sent'] = True
    
    return render_template('dashboard.html', 
                         time_left=time_left,
                         top_nations=top_nations,
                         leaderboard=leaderboard,
                         user_stats=user_stats,
                         payment_history=payment_history,
                         current_month=current_month,
                         current_payment=current_payment,
                         months_until_wc=months_until_wc,
                         winning_nation=winning_nation,
                         can_claim_reward=can_claim_reward,
                         pending_claim=pending_claim,
                         missed_months=missed_months,
                         payment_calendar=payment_calendar,
                         supporters_page=supporters_page,
                         total_pages=total_pages,
                         total_supporters=total_supporters,
                         index_start=start_idx)


@app.route('/api/supporters')
def api_supporters():
    """Return JSON slice of supporters for AJAX pagination.
    Query params: page (int)
    """
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'not_authenticated'}), 401

    try:
        supporters_page = int(request.args.get('page', '1'))
    except Exception:
        supporters_page = 1
    if supporters_page < 1:
        supporters_page = 1

    PAGE_SIZE = 10

    # Use DB aggregation for pagination + lookup for efficiency
    try:
        total_supporters = users_collection.count_documents({'nation': {'$ne': None}})
        total_pages = max(1, (total_supporters + PAGE_SIZE - 1) // PAGE_SIZE)
        if supporters_page > total_pages:
            supporters_page = total_pages

        start_idx = (supporters_page - 1) * PAGE_SIZE

        pipeline = [
            {'$match': {'nation': {'$ne': None}}},
            {'$project': {'username': 1, 'nation': 1, 'avatar_url': 1}},
            {'$addFields': {'_id_str': {'$toString': '$_id'}}},
            {'$lookup': {
                'from': 'user_stats',
                'let': {'uid': '$_id_str'},
                'pipeline': [
                    {'$match': {'$expr': {'$eq': ['$user_id', '$$uid']}}},
                    {'$project': {'months_paid': 1, 'total_paid': 1, '_id': 0}}
                ],
                'as': 'stats'
            }},
            {'$unwind': {'path': '$stats', 'preserveNullAndEmptyArrays': True}},
            {'$addFields': {
                'months_paid': {'$ifNull': ['$stats.months_paid', 0]},
                'total_paid': {'$ifNull': ['$stats.total_paid', 0]}
            }},
            {'$sort': {'months_paid': -1, 'total_paid': -1}},
            {'$skip': start_idx},
            {'$limit': PAGE_SIZE}
        ]

        cursor = users_collection.aggregate(pipeline)
        entries = []
        for u in cursor:
            entries.append({
                'username': u.get('username'),
                'nation': u.get('nation'),
                'avatar_url': u.get('avatar_url', 'default_avatar.png'),
                'months_paid': int(u.get('months_paid', 0)),
                'total_paid': float(u.get('total_paid', 0.0))
            })

        return jsonify({
            'status': 'ok',
            'entries': entries,
            'page': supporters_page,
            'page_size': PAGE_SIZE,
            'total_supporters': total_supporters,
            'total_pages': total_pages,
            'index_start': start_idx
        })
    except Exception as e:
        print('api_supporters: aggregation failed, falling back to in-memory (error):', e)
        # Fallback to previous behavior
        users_with_stats = []
        for user in users_collection.find({'nation': {'$ne': None}}, {'username': 1, 'nation': 1, 'avatar_url': 1}):
            stats = user_stats_collection.find_one({'user_id': str(user['_id'])})
            users_with_stats.append({
                'username': user['username'],
                'nation': user['nation'],
                'avatar_url': user.get('avatar_url', 'default_avatar.png'),
                'months_paid': int(stats.get('months_paid', 0)) if stats else 0,
                'total_paid': float(stats.get('total_paid', 0.00)) if stats else 0.00
            })

        users_with_stats.sort(key=lambda x: (-x['months_paid'], -x['total_paid']))
        total_supporters = len(users_with_stats)
        total_pages = max(1, (total_supporters + PAGE_SIZE - 1) // PAGE_SIZE)
        if supporters_page > total_pages:
            supporters_page = total_pages
        start_idx = (supporters_page - 1) * PAGE_SIZE
        page_slice = users_with_stats[start_idx:start_idx+PAGE_SIZE]
        entries = []
        for u in page_slice:
            entries.append({
                'username': u['username'],
                'nation': u['nation'],
                'avatar_url': u['avatar_url'],
                'months_paid': u['months_paid'],
                'total_paid': u['total_paid']
            })

        return jsonify({
            'status': 'ok',
            'entries': entries,
            'page': supporters_page,
            'page_size': PAGE_SIZE,
            'total_supporters': total_supporters,
            'total_pages': total_pages,
            'index_start': start_idx
        })
@app.route('/pay-monthly')
def pay_monthly():
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    # Get month from query parameter, default to current month
    selected_month = request.args.get('month', get_current_month_year())
    
    # Validate that the month is in the valid range
    months_until_wc = get_months_until_world_cup()
    if selected_month not in months_until_wc:
        return redirect(url_for('dashboard'))
    
    # Check if payment already exists for this month
    existing_payment = monthly_payments_collection.find_one({
        'user_id': session['user_id'],
        'month_year': selected_month
    })
    
    if existing_payment:
        # If payment already exists and is completed, redirect to dashboard
        if existing_payment.get('status') == 'completed':
            return redirect(url_for('dashboard'))
        # If pending, redirect to payment processing
        return redirect(url_for('payment_processing', month=selected_month))
    
    # Redirect to payment processing page with Razorpay
    return redirect(url_for('payment_processing', month=selected_month))

@app.route('/create-razorpay-order', methods=['POST'])
def create_razorpay_order():
    """Compatibility shim: create a pending payment record and return an order-like
    response so older front-end code can continue to call the same endpoint.

    Instead of creating a Razorpay order, we record a pending 'upi_pending'
    monthly payment and return a synthetic payload. The client should then
    open the UPI URL (UPI ID from env) and prompt the user to enter the
    transaction id which will be verified by `/verify-upi-transaction`.
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json() or {}
        selected_month = data.get('month', get_current_month_year())

        # Ensure no completed payment exists for this user/month
        existing_payment = monthly_payments_collection.find_one({'user_id': session['user_id'], 'month_year': selected_month})
        if existing_payment and existing_payment.get('status') == 'completed':
            return jsonify({'error': 'Payment already completed for this month'}), 400

        # Create or update a pending payment record with a synthetic order id
        import time, uuid
        synth_order_id = f"UPI-{session['user_id'][:8]}-{int(time.time())}"

        if existing_payment:
            monthly_payments_collection.update_one({'_id': existing_payment['_id']}, {'$set': {
                'order_id': synth_order_id,
                'amount': 50.00,
                'status': 'pending',
                'notes': {'flow': 'upi_shim'},
                'payment_date': datetime.now()
            }})
            payment_doc_id = existing_payment['_id']
        else:
            res = monthly_payments_collection.insert_one({
                'user_id': session['user_id'],
                'month_year': selected_month,
                'order_id': synth_order_id,
                'amount': 50.00,
                'status': 'pending',
                'notes': {'flow': 'upi_shim'},
                'created_at': datetime.now(),
                'payment_date': None
            })
            payment_doc_id = res.inserted_id

        # Return a payload similar to Razorpay order response so front-end can reuse UI
        payload = {
            'order_id': synth_order_id,
            'amount': 5000,  # paise
            'currency': 'INR',
            'key_id': os.getenv('RAZORPAY_KEY_ID', 'UPI_SHIM'),
            'note': 'Use UPI app to pay ₹50 and then enter the transaction id to verify.'
        }
        return jsonify(payload)
    except Exception as e:
        print('Error creating synthetic upi order:', e)
        return jsonify({'error': 'server_error'}), 500

@app.route('/verify-razorpay-payment', methods=['POST'])
def verify_razorpay_payment():
    """Verify Razorpay payment signature and update database"""
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    try:
        # Two supported verification modes:
        # 1) UPI/manual mode: client posts a transaction_id (preferred)
        # 2) Legacy Razorpay mode: verify Razorpay signature if client provides it
        order_id = request.form.get('razorpay_order_id') or request.form.get('order_id')
        # Legacy params (may be provided by Razorpay callbacks)
        payment_id = request.form.get('razorpay_payment_id') or request.form.get('payment_id')
        signature = request.form.get('razorpay_signature') or request.form.get('signature')

        txn_id = (request.form.get('transaction_id') or request.form.get('txn_id') or '').strip()

        payment_record = None

        # If transaction_id supplied, verify against transactions collection
        if txn_id:
            transactions_collection = db['transactions']
            txdoc = transactions_collection.find_one({'transaction_id': txn_id})
            if not txdoc:
                print('UPI txn not found:', txn_id)
                return render_template('payment_failed.html')

            # read amount safely
            try:
                amount = float(txdoc.get('amount', {}).get('$numberDouble', txdoc.get('amount') or 0))
            except Exception:
                try:
                    amount = float(txdoc.get('amount') or 0)
                except Exception:
                    amount = 0.0

            if abs(amount - 50.0) > 0.01:
                print('UPI amount mismatch', amount)
                return render_template('payment_failed.html')

            # Ensure transaction not used
            existing = monthly_payments_collection.find_one({'transaction_id': txn_id})
            if existing:
                print('Transaction already used', txn_id)
                return render_template('payment_failed.html')

            # Find pending payment by order_id if provided, else by user and month
            if order_id:
                payment_record = monthly_payments_collection.find_one({'order_id': order_id, 'user_id': session['user_id']})
            if not payment_record:
                # fallback: find pending for this user and month
                payment_record = monthly_payments_collection.find_one({'user_id': session['user_id'], 'status': 'pending'})

            if not payment_record:
                print('No pending payment record found for user to attach txn', session['user_id'])
                return render_template('payment_failed.html')

            # Mark payment completed
            monthly_payments_collection.update_one({'_id': payment_record['_id']}, {'$set': {
                'status': 'completed',
                'transaction_id': txn_id,
                'amount': 50.00,
                'approved_at': datetime.now(),
                'approved_by': 'upi_manual'
            }})
        
        if payment_record:
            # Update payment status to completed
            monthly_payments_collection.update_one(
                {'_id': payment_record['_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'razorpay_payment_id': payment_id,
                        'razorpay_signature': signature,
                        'approved_at': datetime.now(),
                        'approved_by': 'razorpay_auto'
                    }
                }
            )
            
            # Update user stats
            user_stats = user_stats_collection.find_one({'user_id': session['user_id']})
            if user_stats:
                new_months_paid = user_stats.get('months_paid', 0) + 1
                user_stats_collection.update_one(
                    {'user_id': session['user_id']},
                    {
                        '$inc': {
                                'months_paid': 1,
                                'total_paid': 50.00
                        },
                        '$set': {
                            'last_payment_month': payment_record['month_year']
                        }
                    }
                )
                
                # Check if user qualifies for premium (3+ payments)
                if new_months_paid >= 3:
                    users_collection.update_one(
                        {'_id': ObjectId(session['user_id'])},
                        {'$set': {'is_premium': True}}
                    )
            else:
                user_stats_collection.insert_one({
                    'user_id': session['user_id'],
                    'months_paid': 1,
                    'total_paid': 50.00,
                    'last_payment_month': payment_record['month_year']
                })
            
            # Notify admin (non-blocking by default)
            try:
                send_admin_notification(
                    "Payment Completed",
                    f"<strong>{session['username']}</strong> successfully completed payment for <strong>{payment_record['month_year']}</strong>.<br>Order/Ref: {order_id or payment_record.get('order_id') or ''}<br>Transaction: {txn_id if txn_id else payment_record.get('transaction_id','N/A')}"
                )
            except Exception as e:
                print('Admin notify failed:', e)

            # Send confirmation email to the user (non-blocking)
            try:
                # Capture request/session-scoped values here so the background thread
                # does NOT try to access Flask's `session` or request context.
                user_email = payment_record.get('email') or session.get('email')
                username = session.get('username')
                month_year = payment_record['month_year']

                import threading
                threading.Thread(target=lambda e=user_email, u=username, m=month_year: send_payment_approved(e, u, m, 50.00), daemon=True).start()
            except Exception:
                # Fallback synchronous send (safe because values already captured)
                try:
                    send_payment_approved(payment_record.get('email') or session.get('email'), session.get('username'), payment_record['month_year'], 50.00)
                except Exception as e:
                    print('User payment confirmation email failed:', e)
            
            # Render success page directly to avoid intermediate redirect/pain flashes
            return render_template('payment_success.html')
        else:
            return render_template('payment_failed.html')
    except Exception as e:
        # If razorpay client exists and signature was provided, we attempted verification
        print(f"Error verifying payment: {str(e)}")
        return render_template('payment_failed.html')


@app.route('/verify-razorpay-payment-ajax', methods=['POST'])
def verify_razorpay_payment_ajax():
    """AJAX-friendly verification endpoint. Returns JSON instead of redirecting.
    This allows the client to show an immediate overlay and then navigate to success
    without the intermediate flash.
    """
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'not_authenticated'}), 401

    data = request.get_json() or {}
    payment_id = data.get('razorpay_payment_id')
    order_id = data.get('razorpay_order_id')
    signature = data.get('razorpay_signature')

    try:
        # If client provided a transaction_id in JSON, use UPI verification flow
        txn_id = (data.get('transaction_id') or data.get('txn_id') or '').strip()
        payment_record = None
        if txn_id:
            transactions_collection = db['transactions']
            txdoc = transactions_collection.find_one({'transaction_id': txn_id})
            if not txdoc:
                return jsonify({'status': 'error', 'message': 'transaction not found'}), 404

            try:
                amount = float(txdoc.get('amount', {}).get('$numberDouble', txdoc.get('amount') or 0))
            except Exception:
                try:
                    amount = float(txdoc.get('amount') or 0)
                except Exception:
                    amount = 0.0

            if abs(amount - 50.0) > 0.01:
                return jsonify({'status': 'error', 'message': 'amount mismatch'}), 400

            # Ensure not already used
            existing = monthly_payments_collection.find_one({'transaction_id': txn_id})
            if existing:
                return jsonify({'status': 'error', 'message': 'transaction already used'}), 400

            # Find pending payment record (by order or by user)
            if order_id:
                payment_record = monthly_payments_collection.find_one({'order_id': order_id, 'user_id': session['user_id']})
            if not payment_record:
                payment_record = monthly_payments_collection.find_one({'user_id': session['user_id'], 'status': 'pending'})
            if not payment_record:
                return jsonify({'status': 'error', 'message': 'no_pending_payment'}), 404

            # Mark completed
            monthly_payments_collection.update_one({'_id': payment_record['_id']}, {'$set': {
                'status': 'completed',
                'transaction_id': txn_id,
                'amount': 50.00,
                'approved_at': datetime.now(),
                'approved_by': 'upi_manual'
            }})

            # Update or create user stats
            user_stats = user_stats_collection.find_one({'user_id': session['user_id']})
            if user_stats:
                user_stats_collection.update_one({'user_id': session['user_id']}, {'$inc': {'months_paid': 1, 'total_paid': 50.00}, '$set': {'last_payment_month': payment_record['month_year']}})
                new_months = user_stats.get('months_paid', 0) + 1
            else:
                user_stats_collection.insert_one({'user_id': session['user_id'], 'months_paid': 1, 'total_paid': 50.00, 'last_payment_month': payment_record['month_year']})
                new_months = 1

            if new_months >= 3:
                users_collection.update_one({'_id': ObjectId(session['user_id'])}, {'$set': {'is_premium': True}})

            # notify admin
            try:
                send_admin_notification('Payment Completed (UPI)', f"<strong>{session['username']}</strong> verified a UPI payment (txn={txn_id}) for {payment_record['month_year']} — ₹50")
            except Exception as e:
                print('Admin notify failed for UPI (ajax):', e)

            # send user email
            try:
                user_email = session.get('email')
                username = session.get('username')
                import threading
                threading.Thread(target=lambda e=user_email, u=username, m=payment_record['month_year']: send_payment_approved(e, u, m, 50.00), daemon=True).start()
            except Exception as e:
                print('User email send failed for UPI (ajax):', e)

            return jsonify({'status': 'ok'})

        # Otherwise fall back to legacy signature verification if available
        if razorpay_client:
            try:
                razorpay_client.utility.verify_payment_signature({'razorpay_order_id': order_id, 'razorpay_payment_id': payment_id, 'razorpay_signature': signature})
            except Exception as e:
                print('Razorpay signature verify failed (ajax):', e)
                return jsonify({'status': 'error', 'message': 'signature_verification_failed'}), 400
            # After successful signature verification, reuse existing logic by looking up payment_record and marking it completed
            payment_record = monthly_payments_collection.find_one({'razorpay_order_id': order_id, 'user_id': session['user_id']})
            if not payment_record:
                return jsonify({'status': 'error', 'message': 'no_payment_record'}), 404
            monthly_payments_collection.update_one({'_id': payment_record['_id']}, {'$set': {'status': 'completed', 'razorpay_payment_id': payment_id, 'razorpay_signature': signature, 'approved_at': datetime.now(), 'approved_by': 'razorpay_auto'}})
            # update user stats & notify same as above
            # ... reuse existing code path by returning ok and letting ajax handler above handle notifications in later code
            try:
                send_admin_notification('Payment Completed (Razorpay)', f"<strong>{session['username']}</strong> completed payment for {payment_record['month_year']}")
            except Exception:
                pass
            try:
                import threading
                threading.Thread(target=lambda: send_payment_approved(session.get('email'), session.get('username'), payment_record['month_year'], 50.00), daemon=True).start()
            except Exception:
                pass
            return jsonify({'status': 'ok'})

        return jsonify({'status': 'error', 'message': 'unsupported_verification_method'}), 400
    except Exception as e:
        print(f'Error verifying payment (ajax): {e}')
        return jsonify({'status': 'error', 'message': 'server_error'}), 500


@app.route('/verify-upi-transaction', methods=['POST'])
def verify_upi_transaction():
    """Verify a UPI transaction id that the user provides by checking the
    `transactions` collection (populated by the admin's SMS/UPI parser).
    Expected JSON: { transaction_id: '123456789012' }
    Returns JSON { status: 'ok' } or { status: 'error', message: '...' }
    """
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'not_authenticated'}), 401

    data = request.get_json() or {}
    txn = (data.get('transaction_id') or '').strip()
    if not txn:
        return jsonify({'status': 'error', 'message': 'transaction_id required'}), 400

    try:
        # Look up transaction in the `transactions` collection
        transactions_collection = db['transactions']
        txdoc = transactions_collection.find_one({'transaction_id': txn})
        if not txdoc:
            return jsonify({'status': 'error', 'message': 'transaction not found'}), 404

        # Basic sanity: amount approx 50
        try:
            amount = float(txdoc.get('amount', {}).get('$numberDouble', txdoc.get('amount') or 0))
        except Exception:
            # attempt direct numeric
            try:
                amount = float(txdoc.get('amount') or 0)
            except Exception:
                amount = 0.0

        if abs(amount - 50.0) > 0.01:
            return jsonify({'status': 'error', 'message': 'amount mismatch'}), 400

        # Check if we already used this transaction id for a payment
        existing = monthly_payments_collection.find_one({'transaction_id': txn})
        if existing:
            return jsonify({'status': 'error', 'message': 'transaction already used'}), 400

        # Mark payment completed: create monthly payment record and update user stats
        # Compute month_year as current month name + year
        month_year = get_current_month_year()

        # Insert monthly payment record
        monthly_payments_collection.insert_one({
            'user_id': session['user_id'],
            'month_year': month_year,
            'amount': 50.00,
            'status': 'completed',
            'transaction_id': txn,
            'payment_date': datetime.now(),
            'approved_at': datetime.now(),
            'approved_by': 'upi_manual'
        })

        # Update or insert user stats
        user_stats = user_stats_collection.find_one({'user_id': session['user_id']})
        if user_stats:
            user_stats_collection.update_one({'user_id': session['user_id']}, {'$inc': {'months_paid': 1, 'total_paid': 50.00}, '$set': {'last_payment_month': month_year}})
            new_months = user_stats.get('months_paid', 0) + 1
        else:
            user_stats_collection.insert_one({'user_id': session['user_id'], 'months_paid': 1, 'total_paid': 50.00, 'last_payment_month': month_year})
            new_months = 1

        # If user now qualifies for premium, set it
        if new_months >= 3:
            users_collection.update_one({'_id': ObjectId(session['user_id'])}, {'$set': {'is_premium': True}})

        # Notify admin
        try:
            send_admin_notification('Payment Completed (UPI)', f"<strong>{session.get('username')}</strong> verified a UPI payment (txn={txn}) for {month_year} — ₹50")
        except Exception as e:
            print('Admin notify failed for UPI:', e)

        # Send user confirmation email in background
        try:
            user_email = session.get('email')
            username = session.get('username')
            import threading
            threading.Thread(target=lambda e=user_email, u=username, m=month_year: send_payment_approved(e, u, m, 50.00), daemon=True).start()
        except Exception as e:
            print('User email send failed for UPI:', e)

        return jsonify({'status': 'ok'})
    except Exception as e:
        print('Error verifying UPI transaction:', e)
        return jsonify({'status': 'error', 'message': 'internal_error'}), 500

@app.route('/payment-failed')
def payment_failed():
    """Page shown when payment fails or is cancelled"""
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    return render_template('payment_failed.html')

@app.route('/payment-processing')
def payment_processing():
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    # Get month from query parameter, default to current month
    selected_month = request.args.get('month', get_current_month_year())
    return render_template('payment_processing.html', current_month=selected_month)

@app.route('/claim-reward')
def claim_reward():
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    winning_nation = get_winning_nation()
    
    if not winning_nation or session.get('nation') != winning_nation:
        return redirect(url_for('dashboard'))
    
    # Check if already claimed
    existing_claim = winner_claims_collection.find_one({
        'user_id': session['user_id'],
        'winning_nation': winning_nation
    })
    
    if not existing_claim:
        # Calculate total pool from completed payments
        pipeline = [
            {'$match': {'status': 'completed'}},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ]
        result = list(monthly_payments_collection.aggregate(pipeline))
        total_pool = result[0]['total'] if result else 0
        
        # Count how many users supported the winning nation
        winner_count = users_collection.count_documents({'nation': winning_nation})
        
        # Calculate reward per winner
        reward_amount = round(total_pool / winner_count, 2) if winner_count > 0 else 0
        
        winner_claims_collection.insert_one({
            'user_id': session['user_id'],
            'winning_nation': winning_nation,
            'reward_amount': reward_amount,
            'status': 'pending',
            'claimed_at': datetime.now(),
            'approved_at': None,
            'approved_by': None
        })
        
        # Notify admin about reward claim
        send_admin_notification(
            "New Reward Claim",
            f"User <strong>{session['username']}</strong> has claimed a reward of <strong>₹{reward_amount}</strong> for supporting <strong>{winning_nation}</strong>. Please review in admin panel."
        )
    
    return redirect(url_for('reward_processing'))

@app.route('/reward-processing')
def reward_processing():
    if 'user_id' not in session:
        return redirect(url_for('login_google'))
    
    winning_nation = get_winning_nation()
    return render_template('reward_processing.html', winning_nation=winning_nation)

@app.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    
    avatar_url = request.form.get('avatar_url')
    
    users_collection.update_one(
        {'_id': ObjectId(session['user_id'])},
        {'$set': {'avatar_url': avatar_url}}
    )
    
    session['avatar_url'] = avatar_url
    
    return jsonify({'success': True, 'message': 'Profile updated successfully'})

@app.route('/go-premium')
def go_premium():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('is_premium'):
        return redirect(url_for('dashboard'))
    
    return render_template('premium.html')

@app.route('/payment-success')
def payment_success():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('payment_success.html')
@app.route('/profile-customization')
def profile_customization():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('profile_customization.html')

@app.route('/user/profile')
def user_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get user data
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    user_stats = user_stats_collection.find_one({'user_id': session['user_id']})
    
    # Format created_at as string
    created_at = user.get('created_at')
    if created_at and isinstance(created_at, datetime):
        created_at_str = created_at.strftime('%Y-%m-%d %H:%M:%S')
    else:
        created_at_str = str(created_at) if created_at else None
    
    # Create user_data tuple to match template expectations
    user_data = (
        user['username'],
        user['email'],
        user.get('nation'),
        user.get('is_premium', False),
        created_at_str,
        user_stats.get('months_paid', 0) if user_stats else 0,
        user_stats.get('total_paid', 0.00) if user_stats else 0.00,
        user_stats.get('last_payment_month') if user_stats else None
    )
    
    # Get nation flag
    nation_flag = None
    if user_data[2]:  # if user has a nation
        nation = nations_collection.find_one({'name': user_data[2]})
        if nation:
            nation_flag = nation['flag_url']
    
    # Get payment history
    payment_history_cursor = monthly_payments_collection.find(
        {'user_id': session['user_id']},
        {'month_year': 1, 'amount': 1, 'status': 1, 'payment_date': 1, 'approved_at': 1}
    ).sort('payment_date', -1)
    payment_history = []
    for p in payment_history_cursor:
        # Format datetime objects as strings
        payment_date = p['payment_date']
        if isinstance(payment_date, datetime):
            payment_date_str = payment_date.strftime('%Y-%m-%d %H:%M:%S')
        else:
            payment_date_str = str(payment_date) if payment_date else None
        
        approved_at = p.get('approved_at')
        if approved_at and isinstance(approved_at, datetime):
            approved_at_str = approved_at.strftime('%Y-%m-%d %H:%M:%S')
        else:
            approved_at_str = str(approved_at) if approved_at else None
        
        payment_history.append((
            p['month_year'], 
            p['amount'], 
            p['status'], 
            payment_date_str, 
            approved_at_str
        ))
    
    return render_template('user_profile.html', user_data=user_data, payment_history=payment_history, nation_flag=nation_flag)

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    # Get recent completed payments (instead of pending, since Razorpay auto-approves)
    completed_payments_data = []
    for payment in monthly_payments_collection.find({'status': 'completed'}).sort('approved_at', -1).limit(50):
        user = users_collection.find_one({'_id': ObjectId(payment['user_id'])})
        if user:
            # Format approved_at
            approved_at = payment.get('approved_at')
            if isinstance(approved_at, datetime):
                approved_at_str = approved_at.strftime('%Y-%m-%d %H:%M:%S')
            else:
                approved_at_str = str(approved_at) if approved_at else None
            
            completed_payments_data.append((
                str(payment['_id']),
                payment['user_id'],
                user['username'],
                user.get('nation'),
                payment['month_year'],
                payment['amount'],
                approved_at_str,
                payment.get('razorpay_payment_id', 'N/A')
            ))
    
    # Get pending reward claims (these still need manual approval for payout)
    pending_rewards_data = []
    for claim in winner_claims_collection.find({'status': 'pending'}).sort('claimed_at', -1):
        user = users_collection.find_one({'_id': ObjectId(claim['user_id'])})
        if user:
            # Format claimed_at
            claimed_at = claim['claimed_at']
            if isinstance(claimed_at, datetime):
                claimed_at_str = claimed_at.strftime('%Y-%m-%d %H:%M:%S')
            else:
                claimed_at_str = str(claimed_at) if claimed_at else None
            
            pending_rewards_data.append((
                str(claim['_id']),
                user['username'],
                claim['winning_nation'],
                claim['reward_amount'],
                claimed_at_str
            ))
    
    # Get all users with their stats
    users_data = []
    for user in users_collection.find({'nation': {'$ne': None}}):
        uid_str = str(user['_id'])
        stats = user_stats_collection.find_one({'user_id': uid_str})

        # Fallback: if stats.total_paid is missing or zero, compute total from completed payments
        payments_pipeline = [
            {'$match': {'user_id': uid_str, 'status': 'completed'}},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}, 'months': {'$sum': 1}}}
        ]
        payments_res = list(monthly_payments_collection.aggregate(payments_pipeline))
        payments_total = float(payments_res[0]['total']) if payments_res and payments_res[0].get('total') is not None else 0.00
        payments_months = int(payments_res[0]['months']) if payments_res and payments_res[0].get('months') is not None else 0

        months_paid = stats.get('months_paid', 0) if stats else payments_months
        total_paid = float(stats.get('total_paid', 0.00)) if stats and stats.get('total_paid', 0.00) else payments_total
        last_payment_month = stats.get('last_payment_month') if stats else None

        users_data.append((
            uid_str,
            user['username'],
            user.get('nation'),
            user.get('is_premium', False),
            months_paid,
            total_paid,
            last_payment_month
        ))
    
    # Get nations for winner selection
    nations_data = [(str(n['_id']), n['name']) for n in nations_collection.find()]
    
    # Get payment statistics
    total_payments = monthly_payments_collection.count_documents({})
    completed_payments = monthly_payments_collection.count_documents({'status': 'completed'})
    pending_payments_count = monthly_payments_collection.count_documents({'status': 'pending'})
    
    pipeline = [
        {'$match': {'status': 'completed'}},
        {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
    ]
    result = list(monthly_payments_collection.aggregate(pipeline))
    total_amount = result[0]['total'] if result else 0
    
    payment_stats = (total_payments, total_amount, completed_payments, pending_payments_count)
    
    return render_template('admin_panel.html', 
                         completed_payments=completed_payments_data,
                         pending_rewards=pending_rewards_data,
                         users=users_data,
                         nations=nations_data,
                         payment_stats=payment_stats,
                         winning_nation=get_winning_nation())

# NOTE: These routes are deprecated - Razorpay now handles payment approval automatically
# Keeping for reference but not used in automated system
"""
@app.route('/admin/approve-payment', methods=['POST'])
def approve_payment():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    payment_id = request.form.get('payment_id')
    
    # Get payment and user details
    payment = monthly_payments_collection.find_one({'_id': ObjectId(payment_id)})
    
    if payment:
        user = users_collection.find_one({'_id': ObjectId(payment['user_id'])})
        
        if user:
            user_id = payment['user_id']
            month_year = payment['month_year']
            amount = payment['amount']
            username = user['username']
            email = user['email']
            
            # Update payment status
            monthly_payments_collection.update_one(
                {'_id': ObjectId(payment_id)},
                {
                    '$set': {
                        'status': 'completed',
                        'approved_at': datetime.now(),
                        'approved_by': session['user_id']
                    }
                }
            )
            
            # Update user stats
            user_stats_collection.update_one(
                {'user_id': user_id},
                {
                    '$inc': {
                        'months_paid': 1,
                        'total_paid': amount
                    },
                    '$set': {
                        'last_payment_month': month_year
                    }
                }
            )
            
            # Check if user should get premium status (after 3 payments)
            user_stats = user_stats_collection.find_one({'user_id': user_id})
            
            if user_stats and user_stats.get('months_paid', 0) >= 3:
                users_collection.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': {'is_premium': True}}
                )
            
            # Send approval email to user
            send_payment_approved(email, username, month_year, amount)
            
            return jsonify({'success': True, 'message': 'Payment approved successfully'})
    
    return jsonify({'error': 'Payment not found'}), 404

@app.route('/admin/reject-payment', methods=['POST'])
def reject_payment():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    payment_id = request.form.get('payment_id')
    
    # Get user details
    payment = monthly_payments_collection.find_one({'_id': ObjectId(payment_id)})
    
    if payment:
        user = users_collection.find_one({'_id': ObjectId(payment['user_id'])})
        
        if user:
            month_year = payment['month_year']
            username = user['username']
            email = user['email']
            
            monthly_payments_collection.update_one(
                {'_id': ObjectId(payment_id)},
                {'$set': {'status': 'rejected'}}
            )
            
            # Send rejection email
            send_payment_rejected(email, username, month_year)
    
    return jsonify({'success': True, 'message': 'Payment rejected'})
"""


@app.route('/admin/set-winner', methods=['POST'])
def set_winner():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Check if winner already set
    winning_nation = get_winning_nation()
    if winning_nation:
        return jsonify({'error': 'Winner already declared! Cannot change the winner.'}), 400
    
    winner_id = request.form.get('winner_id')
    
    winner = nations_collection.find_one({'_id': ObjectId(winner_id)})
    
    if winner:
        winning_nation = winner['name']
        app_settings_collection.update_one(
            {},
            {
                '$set': {
                    'winning_nation': winning_nation,
                    'winner_declared_at': datetime.now(),
                    'declared_by': session['user_id']
                }
            }
        )
        
        # Send emails to all users
        try:
            send_winner_announcement_to_winners(winning_nation)
            send_winner_announcement_to_losers(winning_nation)
            send_admin_notification(
                "Winner Declared",
                f"World Cup winner has been set to <strong>{winning_nation}</strong>. All users have been notified via email."
            )
        except Exception as e:
            print(f"Error sending winner announcement emails: {e}")
        
        return jsonify({'success': True, 'message': f'World Cup Winner set to {winning_nation}! All users have been notified.'})
    
    return jsonify({'error': 'Invalid nation'}), 400

@app.route('/admin/approve-reward', methods=['POST'])
def approve_reward():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    claim_id = request.form.get('claim_id')
    
    # Get claim and user details
    claim = winner_claims_collection.find_one({'_id': ObjectId(claim_id)})
    
    if claim:
        user = users_collection.find_one({'_id': ObjectId(claim['user_id'])})
        
        if user:
            reward_amount = claim['reward_amount']
            username = user['username']
            email = user['email']
            
            winner_claims_collection.update_one(
                {'_id': ObjectId(claim_id)},
                {
                    '$set': {
                        'status': 'completed',
                        'approved_at': datetime.now(),
                        'approved_by': session['user_id']
                    }
                }
            )
            
            # Send approval email
            send_reward_approved(email, username, reward_amount)
    
    return jsonify({'success': True, 'message': 'Reward approved successfully'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# Optimized static file serving with proper caching
@app.route('/static/<path:filename>')
def custom_static(filename):
    """Serve static files with proper cache headers for production"""
    response = send_from_directory('static', filename)
    
    # Set cache headers based on file type
    if filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico')):
        # Images: cache for 1 year
        response.cache_control.max_age = 31536000
        response.cache_control.public = True
    elif filename.endswith(('.mp4', '.webm', '.ogg')):
        # Videos: cache for 1 week, use partial content
        response.cache_control.max_age = 604800
        response.cache_control.public = True
        response.headers['Accept-Ranges'] = 'bytes'
    elif filename.endswith(('.css', '.js')):
        # CSS/JS: cache for 1 day (in case of updates)
        response.cache_control.max_age = 86400
        response.cache_control.public = True
    else:
        # Other files: cache for 1 hour
        response.cache_control.max_age = 3600
        response.cache_control.public = True
    
    return response

# Add after_request handler for additional headers
@app.after_request
def add_security_headers(response):
    """Add security and performance headers to all responses"""
    # Only add caching for static files
    if request.path.startswith('/static/'):
        response.headers['Vary'] = 'Accept-Encoding'
        
    # Security headers for all responses
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response

if __name__ == '__main__':
    init_db()
    # Start monthly reminder scheduler thread
    try:
        import threading
        t = threading.Thread(target=_monthly_scheduler_loop, daemon=True)
        t.start()
    except Exception as e:
        print('Could not start monthly scheduler thread:', e)

    app.run(host='0.0.0.0', port=8000, debug=True)