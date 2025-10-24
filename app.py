from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_mail import Mail, Message
from datetime import datetime, timedelta
import sqlite3
import os
import json
from dotenv import load_dotenv
import hashlib

load_dotenv()

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
app.config['DATABASE'] = 'worldcup.db'

# Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('GMAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('GMAIL_APP_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)

# Password hashing function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Email sending functions
def send_email(subject, recipients, html_body):
    try:
        msg = Message(subject, recipients=recipients)
        msg.html = html_body
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
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

def send_payment_reminder(email, username, month_year):
    subject = f"Payment Reminder - {month_year}"
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px;">
                <h2 style="color: #1173d4;">Monthly Payment Reminder 💰</h2>
                <p>Hi <strong>{username}</strong>,</p>
                <p>This is a friendly reminder that your monthly payment of <strong>₹50</strong> for <strong>{month_year}</strong> is due.</p>
                <p>Login to your dashboard to make the payment and continue supporting your nation!</p>
                <a href="#" style="display: inline-block; background-color: #1173d4; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin-top: 20px;">Make Payment</a>
                <p style="margin-top: 30px;">Best regards,<br><strong>WC 2026 Team</strong></p>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="font-size: 12px; color: #999;">Built by <span style="color: #1173d4; font-weight: bold;">MARK.ORG</span></p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(subject, [email], html)

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
    return send_email(subject, [admin_email], html)

def send_winner_announcement_to_winners(winning_nation):
    """Send email to all users who supported the winning nation"""
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, email FROM users 
            WHERE nation = ?
        ''', (winning_nation,))
        winners = cursor.fetchall()
        
        # Calculate reward info
        cursor.execute('SELECT COALESCE(SUM(amount), 0) FROM monthly_payments WHERE status = "completed"')
        total_pool = cursor.fetchone()[0]
        winner_count = len(winners)
        reward_per_person = round(total_pool / winner_count, 2) if winner_count > 0 else 0
        
        for username, email in winners:
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
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, email, nation FROM users 
            WHERE nation IS NOT NULL AND nation != ?
        ''', (winning_nation,))
        losers = cursor.fetchall()
        
        for username, email, their_nation in losers:
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

def send_monthly_reminder_to_all():
    """Send monthly payment reminder to all users at start of each month"""
    current_month = get_current_month_year()
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Get all users who haven't paid for current month
        cursor.execute('''
            SELECT u.username, u.email 
            FROM users u
            WHERE u.nation IS NOT NULL
            AND u.id NOT IN (
                SELECT user_id FROM monthly_payments 
                WHERE month_year = ? AND status IN ('completed', 'pending')
            )
        ''', (current_month,))
        
        users = cursor.fetchall()
        
        for username, email in users:
            send_payment_reminder(email, username, current_month)

# Database initialization
def init_db():
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                email TEXT,
                nation TEXT,
                avatar_url TEXT DEFAULT 'default_avatar.png',
                theme_color TEXT DEFAULT '#1173d4',
                is_premium BOOLEAN DEFAULT FALSE,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Nations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                flag_url TEXT,
                supporter_count INTEGER DEFAULT 0
            )
        ''')
        
        # Monthly payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monthly_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                month_year TEXT,
                amount REAL DEFAULT 50.00,
                status TEXT DEFAULT 'pending',
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP NULL,
                approved_by INTEGER NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # User stats table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                months_paid INTEGER DEFAULT 0,
                total_paid REAL DEFAULT 0.00,
                last_payment_month TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Winner claims table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS winner_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                winning_nation TEXT,
                reward_amount REAL DEFAULT 100.00,
                status TEXT DEFAULT 'pending',
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP NULL,
                approved_by INTEGER NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # App settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                winning_nation TEXT NULL,
                winner_declared_at TIMESTAMP NULL,
                declared_by INTEGER NULL
            )
        ''')
        
        # Insert default nations (FIFA World Cup 2026 Top Teams)
        nations = [
            ('Spain', 'https://flagcdn.com/w320/es.png'),
            ('France', 'https://flagcdn.com/w320/fr.png'),
            ('England', 'https://flagcdn.com/w320/gb-eng.png'),
            ('Brazil', 'https://flagcdn.com/w320/br.png'),
            ('Argentina', 'https://flagcdn.com/w320/ar.png'),
            ('Germany', 'https://flagcdn.com/w320/de.png'),
            ('Portugal', 'https://flagcdn.com/w320/pt.png'),
            ('Netherlands', 'https://flagcdn.com/w320/nl.png'),
            ('Italy', 'https://flagcdn.com/w320/it.png'),
            ('Uruguay', 'https://flagcdn.com/w320/uy.png'),
            ('Belgium', 'https://flagcdn.com/w320/be.png'),
            ('Colombia', 'https://flagcdn.com/w320/co.png'),
            ('Mexico', 'https://flagcdn.com/w320/mx.png'),
            ('United States', 'https://flagcdn.com/w320/us.png'),
            ('Norway', 'https://flagcdn.com/w320/no.png'),
            ('Croatia', 'https://flagcdn.com/w320/hr.png'),
            ('Denmark', 'https://flagcdn.com/w320/dk.png'),
            ('Japan', 'https://flagcdn.com/w320/jp.png'),
            ('Switzerland', 'https://flagcdn.com/w320/ch.png'),
            ('Morocco', 'https://flagcdn.com/w320/ma.png'),
            ('Canada', 'https://flagcdn.com/w320/ca.png'),
            ('Sweden', 'https://flagcdn.com/w320/se.png'),
            ('Austria', 'https://flagcdn.com/w320/at.png'),
            ('Ecuador', 'https://flagcdn.com/w320/ec.png')
        ]
        
        cursor.executemany('''
            INSERT OR IGNORE INTO nations (name, flag_url) 
            VALUES (?, ?)
        ''', nations)
        
        # Insert admin user with hashed password
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password, email, is_admin) 
            VALUES (?, ?, ?, ?)
        ''', ('admin', hash_password('admin@2025wc!'), 'nithupd@gmail.com', True))
        
        # Insert default app settings
        cursor.execute('INSERT OR IGNORE INTO app_settings (id) VALUES (1)')
        
        conn.commit()

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
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT winning_nation FROM app_settings WHERE id = 1')
        result = cursor.fetchone()
        return result[0] if result else None

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_password = hash_password(password)
        
        with sqlite3.connect(app.config['DATABASE']) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                         (username, hashed_password))
            user = cursor.fetchone()
            
            if user:
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['avatar_url'] = user[5]
                session['theme_color'] = user[6]
                session['is_premium'] = bool(user[7])
                session['is_admin'] = bool(user[8])
                session['nation'] = user[4]
                
                if session['is_admin']:
                    return redirect(url_for('admin_panel'))
                return redirect(url_for('dashboard'))
        
        return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        terms_accepted = request.form.get('terms_accepted')
        
        if not terms_accepted:
            return render_template('signup.html', error='You must accept the terms and conditions')
        
        # Validate password strength
        if len(password) < 8:
            return render_template('signup.html', error='Password must be at least 8 characters long')
        
        hashed_password = hash_password(password)
        
        try:
            with sqlite3.connect(app.config['DATABASE']) as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
                             (username, hashed_password, email))
                user_id = cursor.lastrowid
                
                cursor.execute('INSERT INTO user_stats (user_id) VALUES (?)', (user_id,))
                conn.commit()
                
                session['user_id'] = user_id
                session['username'] = username
                session['avatar_url'] = 'default_avatar.png'
                session['theme_color'] = '#1173d4'
                session['is_premium'] = False
                session['is_admin'] = False
                session['nation'] = None
                
                # Send welcome email
                send_signup_email(email, username)
                
                return redirect(url_for('select_nation'))
        
        except sqlite3.IntegrityError:
            return render_template('signup.html', error='Username already exists')
    
    return render_template('signup.html')

@app.route('/select-nation', methods=['GET', 'POST'])
def select_nation():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Check if user already has a nation in the database
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT nation FROM users WHERE id = ?', (session['user_id'],))
        user_data = cursor.fetchone()
        
        if user_data and user_data[0]:
            session['nation'] = user_data[0]
            return redirect(url_for('dashboard'))
    
    # Get nations for selection
    cursor.execute('SELECT id, name, flag_url FROM nations')
    nations = cursor.fetchall()
    
    if request.method == 'POST':
        nation_id = request.form.get('nation_id')
        
        if nation_id:
            cursor.execute('SELECT name FROM nations WHERE id = ?', (nation_id,))
            nation = cursor.fetchone()
            
            if nation:
                # Update user's nation
                cursor.execute('UPDATE users SET nation = ? WHERE id = ?', 
                             (nation[0], session['user_id']))
                # Update supporter count
                cursor.execute('UPDATE nations SET supporter_count = supporter_count + 1 WHERE id = ?', 
                             (nation_id,))
                conn.commit()
                
                session['nation'] = nation[0]
                return redirect(url_for('dashboard'))
    
    return render_template('select_nation.html', nations=nations)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    world_cup_date = datetime(2026, 7, 19)
    now = datetime.now()
    time_left = world_cup_date - now
    winning_nation = get_winning_nation()
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Get user stats
        cursor.execute('''
            SELECT months_paid, total_paid, last_payment_month 
            FROM user_stats WHERE user_id = ?
        ''', (session['user_id'],))
        user_stats_data = cursor.fetchone() or (0, 0.00, None)
        # Convert to proper types
        user_stats = (
            int(user_stats_data[0]) if user_stats_data[0] else 0,
            float(user_stats_data[1]) if user_stats_data[1] else 0.00,
            user_stats_data[2]
        )
        
        # Get payment history
        cursor.execute('''
            SELECT month_year, amount, status, payment_date, approved_at
            FROM monthly_payments 
            WHERE user_id = ? 
            ORDER BY payment_date DESC
        ''', (session['user_id'],))
        payment_history = cursor.fetchall()
        
        # Get current month payment status
        current_month = get_current_month_year()
        cursor.execute('''
            SELECT status FROM monthly_payments 
            WHERE user_id = ? AND month_year = ?
        ''', (session['user_id'], current_month))
        current_payment = cursor.fetchone()
        
        # Check if user has pending winner claim
        cursor.execute('''
            SELECT status FROM winner_claims 
            WHERE user_id = ? AND status = 'pending'
        ''', (session['user_id'],))
        pending_claim = cursor.fetchone()
        
        # Check if user can claim reward
        can_claim_reward = False
        if winning_nation and session.get('nation') == winning_nation:
            cursor.execute('''
                SELECT id FROM winner_claims 
                WHERE user_id = ? AND winning_nation = ?
            ''', (session['user_id'], winning_nation))
            existing_claim = cursor.fetchone()
            can_claim_reward = not existing_claim
        
        # Get top nations
        cursor.execute('SELECT name, flag_url, supporter_count FROM nations ORDER BY supporter_count DESC LIMIT 7')
        top_nations = cursor.fetchall()
        
        # Get leaderboard - convert numeric values to proper types
        cursor.execute('''
            SELECT u.username, u.nation, u.avatar_url, us.months_paid, us.total_paid
            FROM users u 
            LEFT JOIN user_stats us ON u.id = us.user_id
            WHERE u.nation IS NOT NULL 
            ORDER BY us.months_paid DESC, us.total_paid DESC
            LIMIT 10
        ''')
        leaderboard_data = cursor.fetchall()
        # Convert leaderboard data to proper types
        leaderboard = []
        for user in leaderboard_data:
            leaderboard.append((
                user[0],  # username
                user[1],  # nation
                user[2],  # avatar_url
                int(user[3]) if user[3] else 0,  # months_paid as int
                float(user[4]) if user[4] else 0.00  # total_paid as float
            ))
        
        # Calculate missed payments and payment status for all months
        months_until_wc = get_months_until_world_cup()
        current_month_index = months_until_wc.index(current_month) if current_month in months_until_wc else 0
        
        # Get all paid/pending months for this user
        cursor.execute('''
            SELECT month_year, status FROM monthly_payments 
            WHERE user_id = ?
        ''', (session['user_id'],))
        user_payments = {month: status for month, status in cursor.fetchall()}
        
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
            cursor.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],))
            user_email = cursor.fetchone()
            if user_email:
                send_missed_payment_warning(user_email[0], session['username'], missed_months)
                session['missed_payment_warning_sent'] = True
    
    months_until_wc = get_months_until_world_cup()
    
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
                         payment_calendar=payment_calendar)
@app.route('/pay-monthly')
def pay_monthly():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get month from query parameter, default to current month
    selected_month = request.args.get('month', get_current_month_year())
    
    # Validate that the month is in the valid range
    months_until_wc = get_months_until_world_cup()
    if selected_month not in months_until_wc:
        return redirect(url_for('dashboard'))
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Check if payment already exists for this month
        cursor.execute('''
            SELECT id FROM monthly_payments 
            WHERE user_id = ? AND month_year = ?
        ''', (session['user_id'], selected_month))
        
        existing_payment = cursor.fetchone()
        
        if not existing_payment:
            # Create new payment request
            cursor.execute('''
                INSERT INTO monthly_payments (user_id, month_year, amount, status)
                VALUES (?, ?, 50.00, 'pending')
            ''', (session['user_id'], selected_month))
            conn.commit()
            
            # Send notification to admin
            send_admin_notification(
                "New Payment Request",
                f"User <strong>{session['username']}</strong> has submitted a payment request for <strong>{selected_month}</strong> (₹50). Please review in admin panel."
            )
    
    return redirect(url_for('payment_processing', month=selected_month))

@app.route('/payment-processing')
def payment_processing():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get month from query parameter, default to current month
    selected_month = request.args.get('month', get_current_month_year())
    return render_template('payment_processing.html', current_month=selected_month)

@app.route('/claim-reward')
def claim_reward():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    winning_nation = get_winning_nation()
    
    if not winning_nation or session.get('nation') != winning_nation:
        return redirect(url_for('dashboard'))
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Check if already claimed
        cursor.execute('''
            SELECT id FROM winner_claims 
            WHERE user_id = ? AND winning_nation = ?
        ''', (session['user_id'], winning_nation))
        
        if not cursor.fetchone():
            # Calculate total pool from completed payments
            cursor.execute('''
                SELECT COALESCE(SUM(amount), 0) FROM monthly_payments 
                WHERE status = 'completed'
            ''')
            total_pool = cursor.fetchone()[0]
            
            # Count how many users supported the winning nation
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE nation = ?
            ''', (winning_nation,))
            winner_count = cursor.fetchone()[0]
            
            # Calculate reward per winner
            reward_amount = round(total_pool / winner_count, 2) if winner_count > 0 else 0
            
            cursor.execute('''
                INSERT INTO winner_claims (user_id, winning_nation, reward_amount, status)
                VALUES (?, ?, ?, 'pending')
            ''', (session['user_id'], winning_nation, reward_amount))
            conn.commit()
            
            # Notify admin about reward claim
            send_admin_notification(
                "New Reward Claim",
                f"User <strong>{session['username']}</strong> has claimed a reward of <strong>₹{reward_amount}</strong> for supporting <strong>{winning_nation}</strong>. Please review in admin panel."
            )
    
    return redirect(url_for('reward_processing'))

@app.route('/reward-processing')
def reward_processing():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    winning_nation = get_winning_nation()
    return render_template('reward_processing.html', winning_nation=winning_nation)

@app.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    
    avatar_url = request.form.get('avatar_url')
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET avatar_url = ? WHERE id = ?',
                     (avatar_url, session['user_id']))
        conn.commit()
    
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
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.username, u.email, u.nation, u.is_premium, u.created_at,
                   us.months_paid, us.total_paid, us.last_payment_month
            FROM users u
            LEFT JOIN user_stats us ON u.id = us.user_id
            WHERE u.id = ?
        ''', (session['user_id'],))
        user_data = cursor.fetchone()
        
        # Get nation flag
        nation_flag = None
        if user_data and user_data[2]:  # if user has a nation
            cursor.execute('SELECT flag_url FROM nations WHERE name = ?', (user_data[2],))
            flag_result = cursor.fetchone()
            if flag_result:
                nation_flag = flag_result[0]
        
        # Get payment history
        cursor.execute('''
            SELECT month_year, amount, status, payment_date, approved_at
            FROM monthly_payments 
            WHERE user_id = ? 
            ORDER BY payment_date DESC
        ''', (session['user_id'],))
        payment_history = cursor.fetchall()
    
    return render_template('user_profile.html', user_data=user_data, payment_history=payment_history, nation_flag=nation_flag)

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Get pending payments with user info
        cursor.execute('''
            SELECT mp.id, mp.user_id, u.username, u.nation, mp.month_year, mp.amount, mp.payment_date
            FROM monthly_payments mp
            JOIN users u ON mp.user_id = u.id
            WHERE mp.status = 'pending'
            ORDER BY mp.payment_date DESC
        ''')
        pending_payments = cursor.fetchall()
        
        # Get pending reward claims
        cursor.execute('''
            SELECT wc.id, u.username, wc.winning_nation, wc.reward_amount, wc.claimed_at
            FROM winner_claims wc
            JOIN users u ON wc.user_id = u.id
            WHERE wc.status = 'pending'
            ORDER BY wc.claimed_at DESC
        ''')
        pending_rewards = cursor.fetchall()
        
        # Get all users with their stats
        cursor.execute('''
            SELECT u.id, u.username, u.nation, u.is_premium, 
                   us.months_paid, us.total_paid, us.last_payment_month
            FROM users u 
            LEFT JOIN user_stats us ON u.id = us.user_id
            WHERE u.nation IS NOT NULL
        ''')
        users = cursor.fetchall()
        
        # Get nations for winner selection
        cursor.execute('SELECT id, name FROM nations')
        nations = cursor.fetchall()
        
        # Get payment statistics
        cursor.execute('''
            SELECT 
                COUNT(*) as total_payments,
                SUM(amount) as total_amount,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_payments,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_payments
            FROM monthly_payments
        ''')
        payment_stats = cursor.fetchone()
    
    return render_template('admin_panel.html', 
                         pending_payments=pending_payments,
                         pending_rewards=pending_rewards,
                         users=users,
                         nations=nations,
                         payment_stats=payment_stats,
                         winning_nation=get_winning_nation())

@app.route('/admin/approve-payment', methods=['POST'])
def approve_payment():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    payment_id = request.form.get('payment_id')
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Get payment and user details
        cursor.execute('''
            SELECT mp.user_id, mp.month_year, mp.amount, u.username, u.email 
            FROM monthly_payments mp
            JOIN users u ON mp.user_id = u.id
            WHERE mp.id = ?
        ''', (payment_id,))
        payment = cursor.fetchone()
        
        if payment:
            user_id, month_year, amount, username, email = payment
            
            # Update payment status
            cursor.execute('''
                UPDATE monthly_payments 
                SET status = 'completed', approved_at = CURRENT_TIMESTAMP, approved_by = ?
                WHERE id = ?
            ''', (session['user_id'], payment_id))
            
            # Update user stats
            cursor.execute('''
                UPDATE user_stats 
                SET months_paid = months_paid + 1,
                    total_paid = total_paid + ?,
                    last_payment_month = ?
                WHERE user_id = ?
            ''', (amount, month_year, user_id))
            
            # Check if user should get premium status (after 3 payments)
            cursor.execute('SELECT months_paid FROM user_stats WHERE user_id = ?', (user_id,))
            user_stats = cursor.fetchone()
            
            if user_stats and user_stats[0] >= 3:
                cursor.execute('UPDATE users SET is_premium = TRUE WHERE id = ?', (user_id,))
            
            conn.commit()
            
            # Send approval email to user
            send_payment_approved(email, username, month_year, amount)
            
            return jsonify({'success': True, 'message': 'Payment approved successfully'})
    
    return jsonify({'error': 'Payment not found'}), 404

@app.route('/admin/reject-payment', methods=['POST'])
def reject_payment():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    payment_id = request.form.get('payment_id')
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Get user details
        cursor.execute('''
            SELECT mp.month_year, u.username, u.email 
            FROM monthly_payments mp
            JOIN users u ON mp.user_id = u.id
            WHERE mp.id = ?
        ''', (payment_id,))
        payment = cursor.fetchone()
        
        if payment:
            month_year, username, email = payment
            cursor.execute('UPDATE monthly_payments SET status = "rejected" WHERE id = ?', (payment_id,))
            conn.commit()
            
            # Send rejection email
            send_payment_rejected(email, username, month_year)
    
    return jsonify({'success': True, 'message': 'Payment rejected'})

@app.route('/admin/set-winner', methods=['POST'])
def set_winner():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Check if winner already set
    winning_nation = get_winning_nation()
    if winning_nation:
        return jsonify({'error': 'Winner already declared! Cannot change the winner.'}), 400
    
    winner_id = request.form.get('winner_id')
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM nations WHERE id = ?', (winner_id,))
        winner = cursor.fetchone()
        
        if winner:
            winning_nation = winner[0]
            cursor.execute('''
                UPDATE app_settings 
                SET winning_nation = ?, winner_declared_at = CURRENT_TIMESTAMP, declared_by = ?
                WHERE id = 1
            ''', (winning_nation, session['user_id']))
            conn.commit()
            
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
    
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        
        # Get claim and user details
        cursor.execute('''
            SELECT wc.reward_amount, u.username, u.email
            FROM winner_claims wc
            JOIN users u ON wc.user_id = u.id
            WHERE wc.id = ?
        ''', (claim_id,))
        claim = cursor.fetchone()
        
        if claim:
            reward_amount, username, email = claim
            
            cursor.execute('''
                UPDATE winner_claims 
                SET status = 'completed', approved_at = CURRENT_TIMESTAMP, approved_by = ?
                WHERE id = ?
            ''', (session['user_id'], claim_id))
            conn.commit()
            
            # Send approval email
            send_reward_approved(email, username, reward_amount)
    
    return jsonify({'success': True, 'message': 'Reward approved successfully'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)