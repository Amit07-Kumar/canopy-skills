# n8n credentials — Sarvam Header Auth setup

## Why credentials, not env vars

Our n8n server has `N8N_BLOCK_ENV_ACCESS_IN_NODE` enabled (server-level
hardening). That means workflow nodes cannot reference `$env.SARVAM_API_KEY`
— they get `access to env vars denied` at runtime.

n8n's built-in **Credentials** mechanism is the right replacement: keys
are encrypted at rest, referenced by name from each HTTP Request node,
and rotated in one place.

## Step-by-step setup

### 1. Create the credential

1. Open n8n at `https://imworkflow.intermesh.net/`.
2. Click your avatar (top right) → **Settings** → **Credentials**.
3. Click **+ Create credential** (top right of the page).
4. Search and select **"Header Auth"**.
5. Fill in:
   - **Credential Name** (top of form): `Sarvam API`
   - **Name** (header name): `api-subscription-key`
   - **Value** (the secret): `<sarvam_api_key_here>`
6. Click **Save**.

The credential is now stored encrypted. The secret value is never
visible in the workflow JSON or in node config.

### 2. Wire the credential into each Sarvam node

Six nodes in the `transcribe-speakers` workflow use the Sarvam API:

1. Sarvam: create batch job
2. Sarvam: request upload URL
3. Sarvam: start job
4. Sarvam: poll job status
5. Sarvam: request download URLs
6. Download transcript payload

For each one:

1. Click the node to open it.
2. At the very top, find the **Authentication** dropdown (default "None").
3. Change to **"Generic Credential Type"**.
4. A new "Generic Auth Type" dropdown appears — pick **"Header Auth"**.
5. A "Credential for Header Auth" dropdown appears — pick **"Sarvam API"**.
6. Scroll to **Headers** → **Header Parameters**. Find the row named
   `api-subscription-key` and **delete it** (trash icon at the right).
   Keep other headers (like `Content-Type: application/json`).
7. Click outside the node to auto-save.

### 3. Confirm "Upload audio to signed URL" is untouched

This node uses an Azure SAS URL returned by Sarvam in the previous step.
It does NOT need an `api-subscription-key` header — it has its own
authorization via the signed URL itself. Don't change its Authentication.

### 4. Activate

Top-right of the workflow editor: toggle **Active** OFF, wait 2 seconds,
toggle back ON. This forces n8n to reload the workflow with the new
credential references baked in.

### 5. Verify

```powershell
python D:\10xHackathon\probe_transcribe.py
```

Expected: HTTP 200 in 30-90 seconds, response body has Hindi/English
speaker_map JSON. If you still see `access to env vars denied` or empty
body, check the Executions tab and confirm the credential is selected
on every Sarvam node.

## Rotating the key

When the Sarvam key needs to change:

1. Go to **Credentials** → click on **Sarvam API**.
2. Update the **Value** field.
3. Click **Save**.

All six workflow nodes pick up the new value automatically. No node-by-
node edits required.

## Fallback: hardcoded values per node

If you cannot use the credential approach (e.g., very short demo, or n8n
version doesn't support Header Auth credentials), you can hardcode the
key into each node's Headers row directly. Functional but less elegant.
Just remember to update all six on rotation.
