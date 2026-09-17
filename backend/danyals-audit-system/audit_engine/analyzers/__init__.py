"""On-page analyzers.

Each module evaluates one or more checks from the YAML master list. Every
analyzer returns a list[Finding] (or yields findings) and must cite evidence.
"""
