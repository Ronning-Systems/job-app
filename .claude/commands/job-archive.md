# /job-archive

Archive a job description from plain text or URL into a structured markdown file.

## Usage
```
/job-archive "job description text here"
/job-archive https://company.com/jobs/123
/job-archive --text "Job Description: Senior Engineer at Acme Inc..."
/job-archive --url https://company.com/job/123 --output jobs/company-role.md
```

## Options
- `--text, -t` : Plain text job description
- `--url, -u` : URL to job posting
- `--output, -o` : Output file path (default: `job-descriptions/{company}-{title-slug}.md`)

## Examples
```
/job-archive "Software Engineer at Google - $150k - Remote"
/job-archive --url https://linkedin.com/jobs/view/123 --output jobs/google-swe.md
/job-archive --text "Job Title: CTO\nCompany: Startup\nLocation: NYC\nSalary: 200k"
```

---

## What This Does

The Job Description Archiver Agent extracts and structures:

- **Company Name** - From posting, URL, or extracted text
- **Job Title** - Full title with level/track
- **Location** - City, state, remote/hybrid status
- **Max Salary** - Highest compensation mentioned (base + bonus + equity)
- **Job Posting URL** - Original link
- **Required Credentials** - Degrees, certifications, clearances
- **Job Description Text** - Full posting content
- **Requirements** - Parsed must-have and nice-to-have skills
- **Keywords** - Extracted technical skills and keywords

---

## Output Format

```markdown
# Job: [Title] at [Company]

**Posted**: [Date if available]
**Location**: [Location]
**Salary**: $[Max] (base) [+ bonus] [+ equity]
**URL**: [Original posting URL]
**Source**: [Where extracted from]

## Company
[Company description if available]

## Role Summary
[Brief 2-3 sentence overview]

## Requirements

### Must Have
- [Requirement 1]
- [Requirement 2]

### Nice to Have
- [Preferred 1]
- [Preferred 2]

## Responsibilities
- [Key responsibility 1]
- [Key responsibility 2]

## Extracted Keywords
`keyword1`, `keyword2`, `keyword3`

## Original Posting
[Full job description text]

---
*Archived: [Timestamp]*
```

---

## Notes

- URL will be fetched and parsed for content
- Plain text will be parsed for structured fields
- Output file saved to job-descriptions/ directory
- Filename format: `{company}-{title-slug}.md`
