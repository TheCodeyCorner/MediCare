import mysql.connector
from datetime import datetime

# Database Configuration (matches your hospital_db setup)
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'hospital_db'
}

def get_db_connection():
    """Establishes and returns a live connection to the MySQL hospital_db."""
    return mysql.connector.connect(**DB_CONFIG)

# ==========================================
# 1. FETCH MESSAGES FOR CURRENT USER
# ==========================================
def fetch_user_inbox(user_id):
    """Fetches all incoming messages for the active user, ordered newest first."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT m.*, u.name as sender_name 
            FROM Messages m
            JOIN Users u ON m.sender_id = u.user_id
            WHERE m.receiver_id = %s 
            ORDER BY m.timestamp DESC
        """
        cursor.execute(query, (user_id,))
        messages = cursor.fetchall()
        return messages
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 2. SEND MESSAGE TO A SINGLE USER
# ==========================================
def send_direct_message(sender_id, receiver_id, content):
    """Sends a private message from one user to another."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            INSERT INTO Messages (sender_id, receiver_id, content, is_read, timestamp) 
            VALUES (%s, %s, %s, 0, NOW())
        """
        cursor.execute(query, (sender_id, receiver_id, content))
        conn.commit()
        return {"status": "success", "message": "Direct message sent successfully!"}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 3. SEND TO MULTIPLE PEOPLE / BROADCAST (@all)
# ==========================================
def send_broadcast_message(sender_id, content, target_role=None):
    """
    Sends a message to multiple users. 
    If target_role is specified (e.g., 'patient', 'doctor'), it goes to all users of that role.
    If target_role is None, it goes to @all users in the system (excluding the sender).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if target_role:
            user_query = "SELECT user_id FROM Users WHERE role = %s AND user_id != %s"
            cursor.execute(user_query, (target_role, sender_id))
        else:
            user_query = "SELECT user_id FROM Users WHERE user_id != %s"
            cursor.execute(user_query, (sender_id,))
            
        recipients = cursor.fetchall()
        
        if not recipients:
            return {"status": "error", "message": "No recipients found for broadcast."}

        insert_query = """
            INSERT INTO Messages (sender_id, receiver_id, content, is_read, timestamp) 
            VALUES (%s, %s, %s, 0, NOW())
        """
        
        # Batch insert for performance
        recipient_tuples = [(sender_id, r['user_id'], content) for r in recipients]
        cursor.executemany(insert_query, recipient_tuples)
        conn.commit()
        
        return {
            "status": "success", 
            "message": f"Broadcast sent to {len(recipients)} users successfully!"
        }
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 4. ADMIN ANNOUNCEMENTS (Fetch & Send)
# ==========================================
def send_admin_announcement(admin_id, content):
    """Allows an admin to broadcast an official system announcement to everyone."""
    # Announcements can use the broadcast logic with an announcement tag prefix
    announcement_content = f"[ANNOUNCEMENT]: {content}"
    return send_broadcast_message(sender_id=admin_id, content=announcement_content, target_role=None)

def fetch_announcements():
    """Fetches all system announcements for user dashboards."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT m.*, u.name as admin_name 
            FROM Messages m
            JOIN Users u ON m.sender_id = u.user_id
            WHERE m.content LIKE '[ANNOUNCEMENT]%'
            ORDER BY m.timestamp DESC
        """
        cursor.execute(query)
        announcements = cursor.fetchall()
        return announcements
    finally:
        cursor.close()
        conn.close()