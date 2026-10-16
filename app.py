from flask import Flask, request, jsonify
from flask_cors import CORS
from messaging import send_message, get_inbox, mark_as_read

app = Flask(__name__)
CORS(app) # Allows HTML web pages to connect without CORS issues

# Route 1: Send a Message
@app.route('/api/send', methods=['POST'])
def api_send_message():
    data = request.json
    send_message(data['sender_id'], data['receiver_id'], data['content'])
    return jsonify({"status": "success", "message": "Message sent successfully"}), 201

# Route 2: Get Inbox Messages for a User
@app.route('/api/inbox/<int:user_id>', methods=['GET'])
def api_get_inbox(user_id):
    messages = get_inbox(user_id)
    return jsonify({"status": "success", "messages": messages}), 200

# Route 3: Mark a Message as Read
@app.route('/api/read/<int:message_id>', methods=['PUT'])
def api_mark_as_read(message_id):
    mark_as_read(message_id)
    return jsonify({"status": "success", "message": f"Message {message_id} marked as read"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)