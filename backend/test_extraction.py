#!/usr/bin/env python3
"""Test script to validate PDF/DOCX extraction"""

import base64
import sqlite3
from agents import extract_text_from_file

conn = sqlite3.connect("job_tracker.db")
cursor = conn.cursor()
cursor.execute("SELECT name, resume_type, content FROM base_resumes LIMIT 4")

for name, resume_type, content in cursor.fetchall():
    print(f"\n{'=' * 60}")
    print(f"File: {name}")
    print(f"Type: {resume_type}")
    print(f"Content length in DB: {len(content)} chars")

    if content.startswith("data:"):
        text = extract_text_from_file(content, name)
        print(f"\nExtracted text length: {len(text)} chars")
        print(f"\nFirst 200 chars:\n{text[:200]}")
    else:
        print("Content doesn't start with data:")

conn.close()
