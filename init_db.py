#!/usr/bin/env python3
"""Initialize database"""
from database.models import Base, engine

if __name__ == '__main__':
    print("🔧 Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully!")
