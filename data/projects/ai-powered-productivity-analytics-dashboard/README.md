        # AI-powered productivity analytics dashboard

        Provide operations teams with a tool to visualize productivity patterns and suggest actionable improvements based on real-time user data.

        ## Product Brief
        - Lane: Internal Ops Copilot
        - Target user: Operations analysts or managers reviewing KPI trends
        - ICP: Mid-sized to large enterprises with dedicated operations teams focused on performance metrics.
        - Job to be done: Spot trends, inspect a team, and create follow-up actions from the dashboard.
        - Success metric: Reduction in time spent on reporting and an increase in actionable insights generated per week.

        ## Must-Have Flow
        Review KPI cards, inspect a team, then create a follow-up action or export the current view.

        ## Demo Scenario
        An operations manager logs into the dashboard, reviews the latest KPI trends, identifies a drop in team productivity, inspects the relevant metrics, and creates a follow-up action to address the issue.

        ## Acceptance Criteria
        - Dashboard displays real-time KPI data
- Users can filter and inspect team performance
- Follow-up actions can be created directly from insights
- Export functionality is available for reporting

        ## Local Setup

        ### Quick start (Windows)
        Double-click **`run.bat`** in the project folder. It will install dependencies and start the app.  
        Open http://localhost:8000 in your browser when it says the server is running.

        ### Manual setup (all platforms)
        If you prefer not to use the batch file, or you're on macOS/Linux:

        1. **Create and activate a virtual environment** (recommended):
           - Windows: `python -m venv .venv` then `.venv\Scripts\activate`
           - macOS/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
        2. **Install dependencies:** `pip install -r requirements.txt`
        3. **Start the app:** `uvicorn app.main:app --reload`  
           (If `uvicorn` is not on your PATH, use: `python -m uvicorn app.main:app --reload`)
        4. **Run tests:** `pytest -q`

        Then open http://localhost:8000 in your browser.

        ## Notes
        - Demo data is seeded automatically on startup.
        - Validation expects the homepage, demo data, and primary workflow tests to pass.
