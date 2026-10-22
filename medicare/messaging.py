from db_connection import connect

def send_message(sender_id, receiver_id, message_content):
    """Inserts a new message with default status."""
    db = connect()
    cursor = db.cursor()
    
    sql = "INSERT INTO QueueCare.messages (sender_id, receiver_id, message_content, status) VALUES (%s, %s, %s, 'sent')"
    cursor.execute(sql, (sender_id, receiver_id, message_content))
    
    db.commit()
    cursor.close()
    db.close()
    return True

def get_inbox(user_id):
    """Retrieves all messages sent to a specific user."""
    db = connect()
    cursor = db.cursor()
    
    sql = "SELECT * FROM QueueCare.messages WHERE receiver_id = %s ORDER BY sent_at DESC"
    cursor.execute(sql, (user_id,))
    
    messages = cursor.fetchall()
    cursor.close()
    db.close()
    return messages

def update_status(m_id, new_status):
    """Updates message status (e.g., read, delivered)."""
    db = connect()
    cursor = db.cursor()
    
    sql = "UPDATE QueueCare.messages SET status = %s WHERE m_id = %s"
    cursor.execute(sql, (new_status, m_id))
    
    db.commit()
    cursor.close()
    db.close()
    return True