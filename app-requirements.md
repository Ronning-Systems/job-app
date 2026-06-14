# JobSync - Functional Requirements (Actual Implementation)

## Overview
JobSync is a job application tracking system with AI-powered resume generation and job description parsing.

## User Authentication
**Status: NOT IMPLEMENTED**
- Single-user application (no authentication system)
- No user signup/login
- No LinkedIn or Google OAuth integration
- No password reset capability

## Job Management

### Job Description Processing
- Paste plain text job descriptions
- AI automatically parses job details (company, position, location, salary, remote type)
- Extracts requirements (must-have/nice-to-have), responsibilities, keywords, and credentials
- URL support: URL can be stored for reference but is NOT auto-fetched

### Job Tracker Fields
- Company name
- Position/Job title
- Status/Stage (dropdown with 9 options)
- Job URL (stored for reference)
- Location (where job is based)
- Remote capability (Remote/Hybrid/On-site)
- Salary information
- Applied date
- Notes/Comments
- Response received (checkbox)
- Application history timeline

### Job Stages (Implemented)
1. Saved
2. Applied
3. Phone Screen
4. Interview
5. Executive Call
6. Offered
7. Rejected
8. Withdrawn
9. Closed

## Resume Management

### Base Resumes
- Upload example resumes (PDF, DOCX, TXT) - used for AI reference
- Upload resume templates (DOCX only) - used for formatting generated resumes
- View uploaded base resumes
- Delete uploaded base resumes

### Generated Resumes
- AI generates tailored resume for specific job applications
- Uses example resumes for content reference
- Uses template for formatting structure
- View generated resume in editor
- Edit generated resume text
- Export to DOCX format
- Regenerate resume for same job

## AI Agent Capabilities

### Job Parser Agent
- Parses pasted job descriptions using LLM
- Extracts structured data: company, position, location, salary, remote type
- Identifies requirements (must-have/nice-to-have)
- Extracts responsibilities and keywords

### Resume Generator Agent
- Generates customized resume for specific job
- Matches content from example resumes to job requirements
- Applies template formatting
- Returns plain text resume content

### ATS Analysis Agent
- Analyzes resume against job description
- Provides parse score, keyword match, search relevance, overall score
- Identifies critical issues and recommendations
- Shows keywords found and missing

### Technical Fit Analysis Agent
- Evaluates technical fit of resume for job
- Returns skill match, experience relevance, leadership fit scores
- Identifies strengths, gaps, and recommendations

## Dashboard & Statistics
- Live statistics: Total jobs, Active applications, Interviews, Offers
- Filter tabs: All, Active, Interviewing, Offers, Archived
- Two-column layout: Active and Archived applications
- Quick action buttons on job cards

## Technical Architecture
- **Backend**: FastAPI (Python) with SQLAlchemy ORM
- **Database**: SQLite (job_tracker.db)
- **Frontend**: Single-page HTML/CSS/JavaScript (no build step)
- **AI**: Ollama local LLM integration
- **File Storage**: Base64 encoded in database

## Not Implemented (Future Features)
- User authentication and accounts
- LinkedIn/Google OAuth
- Password reset
- True URL scraping from job boards
- Personal instructions for resume generation
- Industry panel feedback/tuning
- Multi-user support
