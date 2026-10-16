from messaging_service import (
    fetch_user_inbox, 
    send_direct_message, 
    send_broadcast_message, 
    send_admin_announcement, 
    fetch_announcements
)

print("--- 1. TESTING DIRECT MESSAGE ---")
# Maan lo sender_id = 2 aur receiver_id = 1 (Aapke database ke existing users IDs ke hisaab se)
res = send_direct_message(sender_id=2, receiver_id=1, content="Hello! This is a test direct message.")
print(res)

print("\n--- 2. TESTING FETCH USER INBOX ---")
inbox = fetch_user_inbox(user_id=1)
for msg in inbox:
    print(f"From: {msg['sender_name']} | Message: {msg['content']} | Time: {msg['timestamp']}")

print("\n--- 3. TESTING BROADCAST (@all) ---")
broadcast_res = send_broadcast_message(sender_id=2, content="Attention everyone, system maintenance tonight!")
print(broadcast_res)

print("\n--- 4. TESTING ADMIN ANNOUNCEMENT ---")
# Maan lo admin user id = 2 hai
ann_res = send_admin_announcement(admin_id=2, content="Hospital visiting hours have changed.")
print(ann_res)

print("\n--- 5. FETCHING ALL ANNOUNCEMENTS ---")
announcements = fetch_announcements()
for ann in announcements:
    print(f"Announcement by {ann['admin_name']}: {ann['content']}")