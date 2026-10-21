from flask import Flask, jsonify, request
import os

app = Flask(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL")
AI_API_KEY = os.getenv("AI_API_KEY")

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

@app.route("/api/projects/<project_name>", methods=["POST"])
def projects_names(project_name):
    data = request.get_json()
    # Process the data and generate the projects/flows response
    response = {
        "message": "Projects flows data processed successfully",
        "data_received": data,
        "project_name": project_name
    }
    return jsonify(response), 200


@app.route("/api/projects/<project_name>/flows/<flow_id>", methods=["POST"])
def projects_flows(project_name, flow_id):
    data = request.get_json()
    # Process the data and generate the projects/flows response
    response = {
        "message": "Projects flows data processed successfully",
        "data_received": data,
        "project_name": project_name,
        "flow_id": flow_id
    }
    return jsonify(response), 200



@app.route("/api/projects/<project_name>/run-test", methods=["POST"])
def run_test(project_name):
    data = request.get_json()
    # Process the data and generate the run-test response
    response = {
        "project_name": project_name,
        "status": 1,
    }
    
    
    ## VANSHIKA PLZ SEND REQUEST TO API URL HERE.
    
    request_data = {
        
    }
    
    
    
    return jsonify(response), 200   

