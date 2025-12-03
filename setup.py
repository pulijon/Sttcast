"""
Setup configuration for Sttcast package
Allows absolute imports from tools, api, rag, db modules
"""

from setuptools import setup, find_packages

setup(
    name="sttcast",
    version="1.0.0",
    description="Speech-to-text podcast transcription and RAG system",
    author="José Miguel Robles Román",
    author_email="jmr.sttcast@alaveradeviriato.net",
    license="GPLv3",
    packages=find_packages(include=['tools', 'api', 'rag', 'db', 'diarization', 'summaries', 'web']),
    python_requires='>=3.9',
    install_requires=[
        'fastapi>=0.104.1',
        'uvicorn[standard]>=0.24.0',
        'pydantic>=2.5.0',
        'requests>=2.31.0',
        'numpy>=1.26.4',
        'pandas>=2.1.3',
        'python-dotenv>=1.0.0',
        'pyyaml>=6.0.1',
    ],
)
