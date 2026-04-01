"""Verify all DeepCoke dependencies are installed."""
import sys
print(f"Python: {sys.version}")

checks = []
try:
    import fastapi; checks.append(f"fastapi: {fastapi.__version__}")
except: checks.append("fastapi: MISSING")

try:
    import openai; checks.append(f"openai: {openai.__version__}")
except: checks.append("openai: MISSING")

try:
    import chromadb; checks.append(f"chromadb: {chromadb.__version__}")
except: checks.append("chromadb: MISSING")

try:
    import neo4j; checks.append(f"neo4j: {neo4j.__version__}")
except: checks.append("neo4j: MISSING")

try:
    import fitz; checks.append(f"PyMuPDF: OK")
except: checks.append("PyMuPDF: MISSING")

try:
    import pdfplumber; checks.append(f"pdfplumber: {pdfplumber.__version__}")
except: checks.append("pdfplumber: MISSING")

try:
    import sentence_transformers; checks.append(f"sentence-transformers: {sentence_transformers.__version__}")
except: checks.append("sentence-transformers: MISSING")

try:
    import torch; checks.append(f"torch: {torch.__version__}")
except: checks.append("torch: MISSING")

try:
    import escargot; checks.append("escargot: OK")
except: checks.append("escargot: MISSING")

try:
    import numpy; checks.append(f"numpy: {numpy.__version__}")
except: checks.append("numpy: MISSING")

try:
    import sqlalchemy; checks.append(f"sqlalchemy: {sqlalchemy.__version__}")
except: checks.append("sqlalchemy: MISSING")

try:
    import pymysql; checks.append(f"pymysql: OK")
except: checks.append("pymysql: MISSING")

for c in checks:
    status = "OK" if "MISSING" not in c else "FAIL"
    print(f"  [{status}] {c}")

missing = [c for c in checks if "MISSING" in c]
if missing:
    print(f"\n{len(missing)} packages MISSING!")
    sys.exit(1)
else:
    print(f"\nAll {len(checks)} dependencies OK!")
