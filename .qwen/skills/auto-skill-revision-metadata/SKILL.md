---
name: revision-metadata
description: Maintain consistent revision metadata across all endpoints that create or modify versioned content
source: auto-skill
extracted_at: '2026-06-20T16:54:52.527Z'
---

# Maintain Consistent Revision Metadata

When implementing versioned content (e.g., resume revisions, document versions), ensure all endpoints that create or modify revisions save the same metadata schema.

## Problem Pattern

Different endpoints create revisions with different fields:

```python
# Endpoint A (generation) - saves model field
revisions.append({
    "version": next_version,
    "content": resume_content,
    "model": model_override or "default-model",  # ✅ Included
    "feedback": None,
    "timestamp": datetime.utcnow().isoformat(),
})

# Endpoint B (revision) - missing model field
revisions.append({
    "version": next_version,
    "content": resume_content,
    "feedback": feedback,
    "timestamp": datetime.utcnow().isoformat(),
    # ❌ Missing: model field
})
```

**Symptoms:**
- Frontend dropdown shows "Unknown" for some versions
- Cannot trace which model generated which revision
- Inconsistent revision schema causes UI rendering issues

## Solution

### 1. Define Revision Schema Explicitly

Document the expected revision structure:

```json
{
  "version": 3,
  "content": "Full resume text...",
  "model": "kimi-k2.5:cloud",
  "feedback": null,
  "timestamp": "2026-06-20T15:30:00"
}
```

### 2. Use Consistent Model Resolution

All endpoints should resolve the model name the same way:

```python
# Generation endpoint
model_label = model_override or "qwen3.5:cloud"

# Revision endpoint (FIXED)
model_used = os.getenv("MODEL_GENERATION") or os.getenv("MODEL_AGENTS", "kimi-k2.5:cloud")
```

### 3. Apply to All Revision-Creating Endpoints

**Generation endpoint:**
```python
revisions.append({
    "version": next_version,
    "content": resume_content,
    "model": model_override or "qwen3.5:cloud",
    "feedback": None,
    "timestamp": datetime.utcnow().isoformat(),
})
```

**Revision endpoint (with feedback):**
```python
model_used = os.getenv("MODEL_GENERATION") or os.getenv("MODEL_AGENTS", "kimi-k2.5:cloud")
revisions.append({
    "version": next_version,
    "content": resume_content,
    "model": model_used,  # ✅ Now included
    "feedback": feedback,
    "timestamp": datetime.utcnow().isoformat(),
})
```

### 4. Frontend Should Handle Missing Gracefully

```javascript
const modelLabels = {
    'qwen3.5:cloud': 'Qwen 3.5',
    'kimi-k2.5:cloud': 'Kimi K2.5',
    // ...
};
const modelLabel = modelLabels[rev.model] || rev.model || 'Unknown';
let label = `v${rev.version}-${modelLabel}`;
```

## Verification Checklist

Before considering revision history complete:

- [ ] All endpoints save the same fields in revisions
- [ ] Model field is populated for every revision
- [ ] Frontend displays model labels correctly for all versions
- [ ] Revision schema is documented in the model definition
- [ ] Unit tests verify revision structure across endpoints

## Key Insight

Revision metadata consistency is easy to overlook when endpoints are implemented at different times. The generation endpoint was implemented first with full metadata. The revision endpoint was added later and missed the `model` field because:

1. It wasn't in the original schema documentation
2. The focus was on feedback tracking, not model attribution
3. No test verified the revision structure

**Prevention:** Define the revision schema in one place (e.g., model docstring or constants file) and reference it from all endpoints.
