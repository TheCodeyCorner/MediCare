import mysql.connector

def connect():
    """Establishes connection to the local MySQL database."""
    return mysql.connector.connect(
        host="localhost",
        user="root",        # Default XAMPP username
        password="",        # Default XAMPP password is empty
        database="hospital_db"
    )