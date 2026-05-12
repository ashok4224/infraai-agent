To build this solution with GitHub Copilot, you need to provide it with a "Mental Model" of the entire architecture. Copilot works best when you define the Data Flow, Schema, and Component Responsibilities upfront.

Copy and paste the following context into a new file (e.g., INSTRUCTIONS.md) or the Copilot Chat window to guide the generation.

1. Project Overview & Tech Stack
Goal: Build an Autonomous SRE AI Agent that consumes Prometheus Alertmanager webhooks, analyzes the infrastructure, sends an email action plan, and logs everything to a UI.

Backend: Node.js (Express) or Python (FastAPI).

AI Orchestration: LangChain or Vercel AI SDK.

Database: MongoDB or PostgreSQL (to store alert history).

Frontend: React with Tailwind CSS (for the dashboard).

Integrations: Prometheus Alertmanager (Webhook), SendGrid/Nodemailer (Email).

2. The Architecture (Context for Copilot)
A. Webhook Ingestion (/webhook/alerts)
The agent must expect the standard Prometheus Alertmanager JSON format.

Task: Create a POST endpoint that parses alerts[], extracting labels (severity, instance, alertname) and annotations (summary, description).

Schema Hint:

JSON
{ "status": "firing", "alerts": [{ "labels": {...}, "annotations": {...} }] }
B. The "Reasoning" Engine
Once an alert is received, the agent enters a "Diagnostic Loop":

Analyze Alert: Identify the failing component (e.g., "High CPU on DB-01").

System Connection: (Simulated/Actual) The agent calls a tool (e.g., check_system_logs or query_prometheus_metrics) to get "Ground Truth."

Generate Action Plan: Create a Markdown-formatted plan with:

Diagnosis: What is actually wrong?

Commands: Specific CLI commands to fix it (e.g., systemctl restart oracle-xe).

Risk Level: Low/Medium/High.

C. The Notification Layer
Email: Use a template to send the Action Plan to the Admin. Include a deep link to the UI History page for that specific alert ID.

D. The Dashboard UI
History View: A table showing Timestamp, Alert Name, Status (Analyzed/Pending), and Severity.

Detail View: Clicking an alert shows the Full Trace: Original Webhook JSON → AI Logs (Tools called) → Final Action Plan.

3. Specific Prompt to give Copilot
Copy and Paste this into Copilot Chat:

"I want to build a full-stack AI SRE Agent.

Create a FastAPI backend with a /webhook POST route that accepts Prometheus Alertmanager payloads.

Use a GPT-4o model via LangChain to act as the agent. Give it a tool called fetch_logs(system_id) that returns mock log data.

After analysis, the agent should save the alert, the logs, and the 'Action Plan' to a PostgreSQL database.

Add a function to send an email via SMTP containing the Action Plan.

Create a React dashboard using Tailwind that fetches the history from the database and displays the AI's reasoning for each alert."

4. Key Logic to Implement (The "Secret Sauce")
When Copilot starts writing the AI logic, ensure you tell it to use Structured Outputs. The AI should always return a JSON object like this:

JSON
{
  "root_cause": "Memory leak in node-exporter",
  "confidence_score": 0.85,
  "action_plan": [
    "ssh into node-01",
    "sudo systemctl restart node-exporter"
  ],
  "prevention_steps": "Update node-exporter to v1.2.0"
}
Next Steps for you:
Initialize the repo: git init and create your requirements.txt or package.json.

Set up the Webhook: Use ngrok to expose your local port so your actual Prometheus server can send a real test alert.

Define your Tools: If you have specific Oracle systems, tell Copilot: "Add a tool for the agent to query Oracle V$SESSION views when a 'High Database Connections' alert triggers."