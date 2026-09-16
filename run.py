"""
Application entrypoint for Alibaba Cloud DirectMail Automation Agent.
Launches Uvicorn ASGI server hosting the FastAPI backend and frontend SPA.
"""
import uvicorn
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import API_HOST, API_PORT

def main():
    print("=" * 70)
    print(" ALIBABA CLOUD DIRECTMAIL AUTOMATION AGENT ")
    print(" Multi-Region Email Routing & Scheduling Platform ")
    print("=" * 70)
    print(f" -> Local Dashboard URL: http://{API_HOST}:{API_PORT}")
    print(f" -> API Documentation:  http://{API_HOST}:{API_PORT}/docs")
    print(f" -> Database Location:  {PROJECT_ROOT / 'email_agent.db'}")
    print("=" * 70)
    
    uvicorn.run(
        "backend.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()
