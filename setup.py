#!/usr/bin/env python3
"""
Quick start script for Riot Account Creator
"""
import subprocess
import sys
import os

def check_python_version():
    if sys.version_info < (3, 11):
        print("❌ Python 3.11 or higher is required")
        sys.exit(1)
    print("✅ Python version OK")

def install_backend():
    print("\n📦 Installing backend dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"])
        print("✅ Backend dependencies installed")
    except subprocess.CalledProcessError:
        print("❌ Failed to install backend dependencies")
        sys.exit(1)

def install_playwright():
    print("\n🎭 Installing Playwright browsers...")
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        if sys.platform.startswith("linux"):
            subprocess.check_call([sys.executable, "-m", "playwright", "install-deps", "chromium"])
        print("✅ Playwright installed")
    except subprocess.CalledProcessError:
        print("❌ Failed to install Playwright")
        sys.exit(1)

def install_frontend():
    print("\n📦 Installing frontend dependencies...")
    try:
        subprocess.check_call(["npm", "install"], cwd="frontend")
        print("✅ Frontend dependencies installed")
    except subprocess.CalledProcessError:
        print("❌ Failed to install frontend dependencies")
        print("Make sure Node.js is installed: https://nodejs.org/")
        sys.exit(1)

def build_frontend():
    print("\n🏗️ Building frontend...")
    try:
        subprocess.check_call(["npm", "run", "build"], cwd="frontend")
        print("✅ Frontend built successfully")
    except subprocess.CalledProcessError:
        print("❌ Failed to build frontend")
        sys.exit(1)

def main():
    print("=" * 60)
    print("🚀 Riot Creator Control v2.4 - Setup")
    print("=" * 60)
    
    check_python_version()
    install_backend()
    install_playwright()
    install_frontend()
    build_frontend()
    
    print("\n" + "=" * 60)
    print("✅ Setup completed successfully!")
    print("=" * 60)
    print("\n📝 To start the application:")
    print("\n   Development mode:")
    print("   1. Terminal 1: cd backend && python -m uvicorn api.main:app --reload")
    print("   2. Terminal 2: cd frontend && npm run dev")
    print("\n   Production mode:")
    print("   cd backend && python -m uvicorn api.main:app --host 0.0.0.0 --port 8000")
    print("\n   Then open: http://localhost:8000")
    print()

if __name__ == "__main__":
    main()
