
https://github.com/user-attachments/assets/86903240-d035-498e-9100-db1bda02207a

# BugLab

Rapid Recursive Bug Hunter.

## Premise

Ponytail + DELI research loops + Gemma on Cerebras = the fastest practical bug hunts possible in a 12-hour build sprint.

BugLab is a one-shot local bug hunting tool. Pick a project folder, run a hunt, and get a fresh report. 

## Run

```powershell
git clone https://github.com/newjordan/buglab-submission.git
cd buglab-submission
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.server
```

Open:

```text
http://127.0.0.1:8765/
```

Set `CEREBRAS_API_KEY` in `.env` for Cerebras/Gemma inference. `.env` is ignored.

## Use

- `Find Bugs`: run a fresh one-shot bug hunt.
- `Describe Issue`: give BugLab context before the hunt.
- `Find + Fix`: run the bug hunt and basic patch loop.

CLI:

```powershell
python -m buglab.cli hunt --repo C:\path\to\repo
python -m buglab.cli tui --repo C:\path\to\repo --mode find
```

Generated reports are written to ignored `.buglab/` folders and look standard with white/professional final output options.

<img width="1920" height="945" alt="buglab_report" src="https://github.com/user-attachments/assets/d75c5344-4a6e-407d-ad8e-11116c5e0af0" />


## Attributions

- Cerebras and Google Gemma: hackathon platform and inference target.
- Apache ECharts: charting and live visualizations.
- Ponytail by Dietrich Gebert: repair/find-loop inspiration.
- DELI / AutoResearch by Victor Chen: research-loop inspiration.
- BugsInPy: benchmark calibration framing.

Project names and trademarks belong to their respective owners. Attribution does not imply endorsement.
