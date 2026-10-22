import json
import os
import psycopg2
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from dotenv import load_dotenv
from .decorators import role_required

load_dotenv()

def get_db_connection():
    """Establishes and returns a live connection to the PostgreSQL database."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing")
    return psycopg2.connect(database_url)

# ==========================================
# 1. FETCH MESSAGES FOR CURRENT USER
# ==========================================
@require_GET
def get_user_messages(request):
    """Fetches all incoming messages for the active user, ordered newest first."""
    try:
        user_id = request.session.get("supabase_user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized user session."}, status=401)

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                query = """
                    SELECT m.message_id, m.sender_id, m.recipient_id, m.content, m.created_path, m.is_broadcast
                    FROM "QueueCare".messages m
                    WHERE m.recipient_id = %s OR m.sender_id = %s OR m.is_broadcast = TRUE
                    ORDER BY m.created_at DESC;
                """
                cursor.execute(query, (user_id, user_id))
                rows = cursor.fetchall()
                
                messages_list = []
                for row in rows:
                    messages_list.append({
                        "message_id": row[0],
                        "sender_id": row[1],
                        "recipient_id": row[2],
                        "content": row[3],
                        "created_at": row[4].isoformat() if row[4] else None,
                        "is_broadcast": row[5]
                    })
                return JsonResponse({"success": True, "messages": messages_list})
        finally:
            conn.close()
    except Exception as error:
        print("Fetch messages error:", repr(error))
        return JsonResponse({"error": str(error)}, status=500)

# ==========================================
# 2. SEND MESSAGE TO A SINGLE USER
# ==========================================
@require_POST
def send_direct_message(request):
    """Sends a private message from one user to another."""
    try:
        data = json.loads(request.body)
        sender_id = request.session.get("supabase_user_id")
        if not sender_id:
            return JsonResponse({"error": "Unauthorized user session."}, status=401)

        recipient_id = data.get("recipient_id", "").strip()
        content = data.get("content", "").strip()

        if not recipient_id or not content:
            return JsonResponse({"error": "Recipient and content are required."}, status=400)

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                query = """
                    INSERT INTO "QueueCare".messages (sender_id, recipient_id, content, is_broadcast, created_at)
                    VALUES (%s, %s, %s, FALSE, NOW());
                """
                cursor.execute(query, (sender_id, recipient_id, content))
                conn.commit()
                return JsonResponse({"success": True, "message": "Direct message sent successfully!"})
        except Exception as e:
            conn.rollback()
            return JsonResponse({"error": str(e)}, status=500)
        finally:
            conn.close()
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=500)

# ==========================================
# 3. SEND TO MULTIPLE PEOPLE / BROADCAST (@all)
# ==========================================
@require_POST
def send_broadcast_message(request):
    """
    Sends a message to multiple users or broadcasts using @all.
    """
    try:
        data = json.loads(request.body)
        sender_id = request.session.get("supabase_user_id")
        if not sender_id:
            return JsonResponse({"error": "Unauthorized user session."}, status=401)

        content = data.get("content", "").strip()
        target_role = data.get("target_role") # Optional role filter

        if not content:
            return JsonResponse({"error": "Content is required."}, status=400)

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if target_role:
                    user_query = """
                        SELECT u.user_id FROM "QueueCare".users u
                        JOIN "QueueCare".access_levels a ON u.access_id = a.access_id
                        WHERE a.access_level = %s AND u.user_id != %s
                    """
                    cursor.execute(user_query, (target_role, sender_id))
                else:
                    user_query = 'SELECT user_id FROM "QueueCare".users WHERE user_id != %s'
                    cursor.execute(user_query, (sender_id,))
                    
                recipients = cursor.fetchall()
                if not recipients:
                    return JsonResponse({"error": "No recipients found for broadcast."}, status=404)

                insert_query = """
                    INSERT INTO "QueueCare".messages (sender_id, recipient_id, content, is_broadcast, created_at)
                    VALUES (%s, %s, %s, FALSE, NOW());
                """
                recipient_tuples = [(sender_id, r[0], content) for r in recipients]
                cursor.executemany(insert_query, recipient_tuples)
                conn.commit()
                
                return JsonResponse({
                    "success": True,
                    "message": f"Broadcast sent to {len(recipients)} users successfully!"
                })
        except Exception as e:
            conn.rollback()
            return JsonResponse({"error": str(e)}, status=500)
        finally:
            conn.close()
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=500)

# ==========================================
# 4. ADMIN ANNOUNCEMENTS (Fetch & Send)
# ==========================================
@role_required("Admin")
@require_POST
def send_admin_announcement(request):
    """Allows an admin to broadcast an official system announcement to everyone."""
    try:
        data = json.loads(request.body)
        admin_id = request.session.get("supabase_user_id")
        content = data.get("content", "").strip()
        
        if not content:
            return JsonResponse({"error": "Announcement content is required."}, status=400)

        announcement_content = f"[ANNOUNCEMENT]: {content}"
        
        # We can insert a global broadcast message or insert for everyone using broadcast logic
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO "QueueCare".messages (sender_id, recipient_id, content, is_broadcast, created_at)
                    VALUES (%s, NULL, %s, TRUE, NOW());
                    """,
                    (admin_id, announcement_content)
                )
                conn.commit()
                return JsonResponse({"success": True, "message": "Announcement broadcasted successfully!"})
        except Exception as e:
            conn.rollback()
            return JsonResponse({"error": str(e)}, status=500)
        finally:
            conn.close()
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=500)

@require_GET
def fetch_announcements(request):
    """Fetches all system announcements for user dashboards."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                query = """
                    SELECT m.message_id, m.sender_id, m.content, m.created_at
                    FROM "QueueCare".messages m
                    WHERE m.is_broadcast = TRUE AND m.content LIKE '[ANNOUNCEMENT]%%'
                    ORDER BY m.created_at DESC;
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                
                announcements = []
                for row in rows:
                    announcements.append({
                        "message_id": row[0],
                        "sender_id": row[1],
                        "content": row[2],
                        "created_at": row[3].isoformat() if row[3] else None
                    })
                return JsonResponse({"success": True, "announcements": announcements})
        finally:
            conn.close()
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=500)