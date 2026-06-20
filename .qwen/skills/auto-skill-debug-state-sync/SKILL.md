---
name: debug-state-sync
description: Debug full-stack state synchronization issues where backend is correct but frontend doesn't reflect updates
source: auto-skill
extracted_at: '2026-06-20T16:26:00.183Z'
---

# Debug Full-Stack State Synchronization Issues

When a feature works on the backend (data is correctly saved/updated) but the frontend doesn't reflect the changes, use this systematic approach:

## 1. Trace the Complete Flow

Map the entire request/response cycle:
- **Backend endpoint** → What data is returned?
- **Network call** → What does the frontend receive?
- **State update** → How does the frontend store the data?
- **UI render** → What triggers the UI to refresh?

## 2. Check for Stale References

Common issue: The UI holds a reference to an old object that isn't updated when fresh data arrives.

**Symptoms:**
- API returns correct data (verify with logs/curl)
- Frontend receives the data
- UI still shows old values

**Fix pattern:**
```javascript
// After fetching fresh data, update the local reference
await fetchJobs(); // Refreshes the jobs array
const updatedJob = jobs.find(j => j.id === jobId);
if (updatedJob) {
    // Copy fresh data to the local reference the UI is using
    job.generated_resume = updatedJob.generated_resume;
    job.resume_revisions = updatedJob.resume_revisions || [];
}
```

## 3. Verify UI Refresh Triggers

After state updates, ensure the UI actually re-renders:

- **Modal/dialog already open?** It may need to be refreshed or have its inputs repopulated
- **Dropdown populated once on open?** It won't auto-update when underlying data changes
- **Event listeners attached?** Trigger them manually after updating state

**Fix pattern:**
```javascript
// After updating state, explicitly refresh UI components
populateVersionDropdown(revisions); // Repopulate from fresh data
versionSelect.selectedIndex = 0; // Select latest
versionSelect.dispatchEvent(new Event('change')); // Trigger content load
```

## 4. Add Strategic Logging

Log at each stage to identify where the sync breaks:

```javascript
console.log('[api] Response revisions:', pollResult.revisions?.length);
console.log('[state] After fetchJobs:', updatedJob.resume_revisions?.length);
console.log('[ui] Populating dropdown with:', revisions.length, 'revisions');
```

## 5. Common Patterns

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Backend correct, UI stale | Local reference not updated | Copy fresh data after fetch |
| Dropdown empty after update | Not repopulated on reopen | Call populate function explicitly |
| Content doesn't change | Event not triggered | Dispatch change event manually |
| Modal shows old data | Modal state not refreshed | Re-run initialization logic |

## Key Insight

The backend was correct in this case — it properly created revisions. The bug was purely in the frontend state management: after `fetchJobs()` refreshed the data array, the local `job` reference held by the modal wasn't updated, and the version dropdown wasn't repopulated when the modal reopened.
