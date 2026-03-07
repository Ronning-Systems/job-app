# /resume-review

Analyze a resume against job description(s) using multiple expert perspectives and generate an optimized executive resume.

## Usage
```
/resume-review [job_description_file.md] [options]
/resume-review job-desc.md --resume path/to/resume.pdf --linkedin path/to/profile.html --template path/to/template.docx
```

## Options
- `--resume, -r` : Path to reference resume file (PDF, DOCX, or MD)
- `--linkedin, -l` : Path to LinkedIn profile export (HTML or text)
- `--template, -t` : Path to resume template file for formatting

## Example
```
/resume-review ~/jobs/tech-lead.md
/resume-review job.md --resume current-resume.pdf --linkedin profile.html --template executive-template.docx
/resume-review job1.md job2.md --resume my-resume.pdf
```

---

## What This Does

This skill runs a comprehensive multi-agent resume review workflow:

### Step 1: Information Aggregation
The **Information Extraction Agent** processes:
- Reference resume (if provided)
- LinkedIn profile export (if provided)
- Job description(s)

### Step 2: Resume Generation
The **Resume Generation Agent** creates a professional executive-level resume based on the aggregated information.

### Step 3: Template Formatting
The **Template Formatting Agent** applies the resume template (if provided) to ensure proper formatting and visual layout.

### Step 4: Parallel Expert Panel (Simultaneous)
Three agents analyze the resume against the job description(s):

1. **ATS Expert** - Evaluates:
   - Keyword optimization and matching
   - Parseability and formatting compatibility
   - Search relevance scoring

2. **Technical Hiring Manager** - Evaluates:
   - Technical skills match
   - Experience depth and scope
   - Leadership capability alignment

3. **HR Professional** - Evaluates:
   - Career trajectory and progression
   - Cultural fit indicators
   - Executive presence and presentation

### Step 5: Feedback Integration
The Resume Generation Agent reviews all feedback and:
- Addresses actionable items in the resume
- Notes feedback that cannot be reasonably addressed

### Step 6: Final Template Application
The Template Formatting Agent re-applies the template to the revised resume.

### Step 7: Final Output
Provides:
- **Fit Synopsis** for each job (1-5 scale with rationale)
- **Cover Letter Topics** - honest gaps to address
- **Key Strengths** identified by all reviewers

---

## Required: Job Description File

Create a markdown file containing the job description:

```markdown
# Job Description: [Job Title]

## Company
[Company name or description]

## Role Summary
[Brief overview of the role]

## Requirements
- Must have:
  - [Required skill/experience 1]
  - [Required skill/experience 2]

- Nice to have:
  - [Preferred skill/experience 1]

## Responsibilities
- [Key responsibility 1]
- [Key responsibility 2]

## Keywords
technical skills, tools, platforms that should be emphasized
```

---

## Input Files

### Reference Resume (Optional)
Your current resume in any format (PDF, DOCX, Markdown). Used as a reference for your experience and achievements.

### LinkedIn Profile (Optional)
Exported LinkedIn profile (HTML or text). Provides additional context on your professional history, recommendations, and skills.

### Resume Template (Optional)
A template file (DOCX) to apply formatting conventions to the generated resume.

---

## Output Format

```
## Resume Review Complete

### Fit Analysis: [Job Title]
- Overall Fit: X/5
- Key Matches: [list]
- Gaps: [list]

### Feedback Summary
[Aggregated feedback themes from all three perspectives]

### Cover Letter Recommendations
Topics to address:
1. [Gap/Topic] - [how to address in cover letter]
2. [Gap/Topic] - [how to address in cover letter]

### Key Strengths
[Strengths highlighted by reviewers]

### Generated Files
- [resume.md] - Raw resume content
- [resume-formatted.docx] - Template-applied version (if template provided)
```

---

## Notes

- Provide one or more job description file paths
- Each job description gets a separate fit analysis
- Be honest about gaps - they're flagged for cover letter, not hidden
- The workflow runs feedback agents in parallel for efficiency
- Template file is applied after feedback integration for final output
