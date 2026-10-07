from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/")
def health_check():
    return jsonify({"status": "ok", "message": "API is running"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)