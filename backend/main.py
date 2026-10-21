from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/")
def health_check():
    return jsonify({"status": "ok", "message": "API is running"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)



## Creation    
@app.route("/api/create-project", methods=["POST"])
def create_project():
    data = request.get_json()
    # Process the data and generate the create-project response
    response = {
        "message": "Project created successfully",
        "data_received": data
    }
    return jsonify(response), 201





## Reading
@app.route("/api/dashboard", methods=["POST"])
def dashboard():
    data = request.get_json()
    # Process the data and generate the dashboard response
    response = {
        "message": "Dashboard data processed successfully",
        "data_received": data
    }
    return jsonify(response), 200


@app.route("/api/accounts", methods=["POST"])
def accounts():
    data = request.get_json()
    # Process the data and generate the accounts response
    response = {
        "message": "Accounts data processed successfully",
        "data_received": data
    }
    return jsonify(response), 200



@app.route("/api/environments", methods=["  POST"])
def environments():
    data = request.get_json()
    # Process the data and generate the environments response
    response = {
        "message": "Environments data processed successfully",
        "data_received": data
    }
    return jsonify(response), 200