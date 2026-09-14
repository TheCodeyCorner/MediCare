from medicare.supabase_client import supabase

import os
import psycopg2
from dotenv import load_dotenv


load_dotenv()


def test_patient_signup():
    password = "#Divdeep@test123"
    email = "another.unique.test@example.com"
    contact = "+919958482929"

    # 1. Create the user in Supabase Auth
    response = supabase.auth.sign_up({
        "email": email,
        "password": password,
        "phone": contact
    })

    print("Signup response:")
    print(response)

    if not response.user:
        print("\nNo user returned. QueueCare user was not created.")
        return

    user = response.user

    print("\nAuth user created successfully!")
    print("User ID:", user.id)
    print("Email:", user.email)
    print("Phone:", user.phone)

    # 2. Connect directly to PostgreSQL
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    connection = psycopg2.connect(database_url)

    try:
        cursor = connection.cursor()

        # 3. Get the Patient access level
        cursor.execute("""
            SELECT access_id
            FROM "QueueCare".access_levels
            WHERE access_level = 'Patient'
            LIMIT 1;
        """)

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Patient access level not found in QueueCare.access_levels"
            )

        patient_access_id = row[0]

        # 4. Create QueueCare.users row
        cursor.execute("""
            INSERT INTO "QueueCare".users (
                user_id,
                email,
                access_id,
                status,
                created_at,
                "Contact"
            )
            VALUES (
                %s,
                %s,
                %s,
                'active',
                NOW(),
                %s
            )
            RETURNING
                user_id,
                email,
                access_id,
                status,
                "Contact";
        """, (
            user.id,
            email,
            patient_access_id,
            contact
        ))

        queuecare_user = cursor.fetchone()

        connection.commit()

        print("\nQueueCare user created successfully!")
        print("User ID:", queuecare_user[0])
        print("Email:", queuecare_user[1])
        print("Access ID:", queuecare_user[2])
        print("Status:", queuecare_user[3])
        print("Contact:", queuecare_user[4])

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    test_patient_signup()

# import mysql.connector

# def get_db_connection():
#     return mysql.connector.connect(
#         host="localhost",
#         user="root",
#         password="",
#         database="hospital_db"
#     )

# def push_message():
#     db = get_db_connection()
#     cursor = db.cursor()

#     sender_id = 1    # Patient
#     receiver_id = 2  # Doctor
#     message = "hello" # Hardcoded test message

#     sql = "INSERT INTO Messages (sender_id, receiver_id, content) VALUES (%s, %s, %s)"
#     values = (sender_id, receiver_id, message)

#     cursor.execute(sql, values)
#     db.commit()

#     print(f"SUCCESS: Pushed message '{message}' into SQL database!")
    
#     cursor.close()
#     db.close()

# def read_messages():
#     db = get_db_connection()
#     cursor = db.cursor(dictionary=True)

#     sql = "SELECT * FROM Messages ORDER BY timestamp DESC LIMIT 1"
#     cursor.execute(sql)

#     latest_message = cursor.fetchone()

#     print("\n--- READING LATEST MESSAGE FROM SQL ---")
#     print(f"Message ID : {latest_message['message_id']}")
#     print(f"Sender ID  : {latest_message['sender_id']}")
#     print(f"Receiver ID: {latest_message['receiver_id']}")
#     print(f"Content    : {latest_message['content']}")
#     print(f"Is Read    : {latest_message['is_read']}")
#     print(f"Timestamp  : {latest_message['timestamp']}")
#     print("---------------------------------------")

#     cursor.close()
#     db.close()

# if __name__ == "__main__":
#     push_message()
#     read_messages()
