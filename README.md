# JobSync - Job Application Tracker

A comprehensive job application tracking system with resume management and AI-powered job description parsing.

**Live URL:** https://jobsync.ronning.systems

## Features

### Job Tracking
- Track jobs through 9 stages: Saved, Applied, Phone Screen, Interview, Executive Call, Offered, Rejected, Withdrawn, Closed
- Add jobs via URL (auto-fetches job details via MCP server) or plain text (parsed via Job Archival Agent)
- Store job descriptions, requirements, and extracted keywords
- History tracking with automatic stage change logging

### Resume Management
- Create and manage multiple resumes
- ATS optimization via ATS Expert Agent
- Technical fit analysis via Technical Hiring Manager Agent
- Resume generation tailored to specific jobs

### AI Agents
- **Job Description Archiver Agent**: Parses job postings from URLs or text
- **ATS Expert Agent**: Analyzes resumes for ATS compatibility
- **Technical Hiring Manager Agent**: Evaluates technical fit
- **Resume Generator Agent**: Creates tailored resumes

## Architecture

### Frontend
- Pure HTML/CSS/JS (no build step required)
- Responsive design with Font Awesome icons
- Direct API integration with backend

### Backend
- **FastAPI** (Python 3.9+) - REST API
- **SQLAlchemy** - Database ORM
- **SQLite** - Default database (easily swappable to PostgreSQL)

### Services
- **Backend API** (Port 8000): Main application API
- **MCP Server** (Port 8080): Job fetching and parsing service

## Installation

### Prerequisites
- Python 3.9+
- pip

### Quick Setup

```bash
# Clone/navigate to the project
cd /path/to/job-app

# Run the setup script
./setup.sh

# This will:
# - Create Python 3.9 virtual environments
# - Install all dependencies
# - Create startup scripts
```

### Manual Setup

```bash
# Backend
cd backend
python3.9 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# MCP Server (in project root)
cd ..
python3.9 -m venv mcp_server/venv
source mcp_server/venv/bin/activate
pip install -r mcp_server/requirements.txt
```

## Running the Application

### Option 1: Start All Services
```bash
./start_all.sh
```

### Option 2: Start Services Separately

Terminal 1 - MCP Server:
```bash
./start_mcp.sh
```

Terminal 2 - Backend API:
```bash
./start_backend.sh
```

Terminal 3 - Frontend:
```bash
# Serve index.html via any static server
python -m http.server 3000
# Or simply open index.html in browser
```

### Service URLs
- Frontend: http://localhost:3000 (or file://)
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- MCP Server: http://localhost:8080

## API Endpoints

### Jobs
- `POST /api/jobs` - Create a new job (URL or text)
- `GET /api/jobs` - List all jobs
- `GET /api/jobs/{id}` - Get job details
- `PUT /api/jobs/{id}` - Update job
- `DELETE /api/jobs/{id}` - Delete job
- `PATCH /api/jobs/{id}/stage` - Update application stage

### Stats
- `GET /api/stats` - Get dashboard statistics

### Agents
- `POST /api/agents/ats-analysis` - ATS analysis
- `POST /api/agents/technical-fit` - Technical fit analysis
- `POST /api/agents/generate-resume` - Generate resume

## Project Structure

```
job-app/
├── index.html              # Frontend UI
├── app-requirements.md     # Project requirements
├── setup.sh                # Setup script
├── start_all.sh            # Start all services
├── start_backend.sh        # Start backend only
├── start_mcp.sh            # Start MCP server only
├── mcp_server.py           # MCP server (job fetching)
│
├── backend/
│   ├── main.py             # FastAPI main application
│   ├── models.py           # SQLAlchemy models
│   ├── job_parser.py       # Job description parser
│   ├── agents.py           # Agent service integrations
│   └── requirements.txt    # Backend dependencies
│
├── mcp_server/
│   └── requirements.txt    # MCP server dependencies
│
└── agents/                 # Agent prompts
    ├── ats-expert.md
    ├── resume-generator.md
    └── tech-hiring-manager.md
```

## Database Schema

### Job Table
- company, position, location, salary, remote
- job_url, job_description_raw, job_description_parsed
- requirements (JSON), responsibilities (JSON)
- keywords (JSON), required_credentials (JSON)
- source_type, source_url

### JobApplication Table
- job_id (FK)
- stage (9 possible stages)
- applied_date, response_received
- notes, history (JSON)

## Adding a Job

### From URL
1. Click "Add Job to Tracker"
2. Select "From URL" tab
3. Paste the job posting URL
4. The MCP server fetches and parses the page
5. Job details are extracted and stored

### From Text
1. Click "Add Job to Tracker"
2. Select "From Text" tab
3. Paste the job description
4. The Job Archival Agent parses the text
5. Structured data is extracted and stored

### Manual Entry
1. Click "Add Job to Tracker"
2. Select "Manual Entry" tab
3. Fill in company, position, location, etc.
4. Optionally add URL and/or description text

## Development

### Adding New Agent Endpoints

Edit `backend/agents.py`:

```python
def my_new_agent(self, input_data: dict) -> dict:
    """New agent functionality"""
    # Implement agent logic
    return {"result": "..."}
```

Add endpoint in `backend/main.py`:

```python
@app.post("/api/agents/my-agent")
async def my_agent_endpoint(data: MyAgentInput):
    result = agent_service.my_new_agent(data.dict())
    return {"analysis": result}
```

## License

MIT License
