# Executive Resume Review Skill

This skill orchestrates a multi-agent workflow to generate professional executive resumes and analyze them against job descriptions from multiple perspectives.

## Usage

`/resume-review [job_description_file(s)]`

## Arguments

- `job_description_file(s)`: One or more file paths containing job descriptions (markdown or text files)

## Workflow

1. **Resume Generation Agent**: Creates a professional executive-level resume based on available candidate information

2. **Parallel Feedback Panel** (runs simultaneously):
   - **ATS Expert**: Analyzes resume for Applicant Tracking System compatibility (keywords, formatting, scanability)
   - **Technical Hiring Manager**: Evaluates technical skills, experience alignment, and qualifications fit
   - **HR Professional**: Reviews cultural fit, career progression, and overall presentation

3. **Feedback Integration**: Resume generation agent reviews all feedback and addresses actionable items

4. **Final Output**:
   - Synopsis of overall fit for each job description
   - Honest summary of gaps that should be addressed in cover letter

## Notes

- The skill requires job description content to be provided
- Each job description will receive a separate fit analysis
- Unaddressable feedback is flagged for cover letter customization
