import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="hospital_db"
    )

def push_message():
    db = get_db_connection()
    cursor = db.cursor()

    sender_id = 1    # Patient
    receiver_id = 2  # Doctor
    message = "hello" # Hardcoded test message

    sql = "INSERT INTO Messages (sender_id, receiver_id, content) VALUES (%s, %s, %s)"
    values = (sender_id, receiver_id, message)

    cursor.execute(sql, values)
    db.commit()

    print(f"SUCCESS: Pushed message '{message}' into SQL database!")
    
    cursor.close()
    db.close()

def read_messages():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    sql = "SELECT * FROM Messages ORDER BY timestamp DESC LIMIT 1"
    cursor.execute(sql)

    latest_message = cursor.fetchone()

    print("\n--- READING LATEST MESSAGE FROM SQL ---")
    print(f"Message ID : {latest_message['message_id']}")
    print(f"Sender ID  : {latest_message['sender_id']}")
    print(f"Receiver ID: {latest_message['receiver_id']}")
    print(f"Content    : {latest_message['content']}")
    print(f"Is Read    : {latest_message['is_read']}")
    print(f"Timestamp  : {latest_message['timestamp']}")
    print("---------------------------------------")

    cursor.close()
    db.close()

if __name__ == "__main__":
    push_message()
    read_messages()
