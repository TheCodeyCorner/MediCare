from db_connection import connect

def send_message(sender_id, receiver_id, content):
    """Inserts a new message with default is_read = False."""
    db = connect()
    cursor = db.cursor()
    
    sql = "INSERT INTO Messages (sender_id, receiver_id, content) VALUES (%s, %s, %s)"
    cursor.execute(sql, (sender_id, receiver_id, content))
    
    db.commit()
    cursor.close()
    db.close()
    return True

def get_inbox(user_id):
    """Retrieves all messages sent to a specific user."""
    db = connect()
    cursor = db.cursor(dictionary=True) # dictionary=True returns data formatted as JSON
    
    sql = "SELECT * FROM Messages WHERE receiver_id = %s ORDER BY timestamp DESC"
    cursor.execute(sql, (user_id,))
    
    messages = cursor.fetchall()
    cursor.close()
    db.close()
    return messages

def mark_as_read(message_id):
    """Updates is_read status to True when viewed."""
    db = connect()
    cursor = db.cursor()
    
    sql = "UPDATE Messages SET is_read = TRUE WHERE message_id = %s"
    cursor.execute(sql, (message_id,))
    
    db.commit()
    cursor.close()
    db.close()
    return True