"""
Job Pipeline Module – Phase C Integration
This module now includes real integration for importing a job
by calling the existing batch file:
C:\\ChatGPT\\ai-bots\\Jobs\\scripts\\do.bat
"""

import subprocess

def run_import_job():
    try:
        # Execute the existing batch file that runs the import workflow
        result = subprocess.run(
            [r"C:\\ChatGPT\\ai-bots\\Jobs\\scripts\\do.bat"],
            capture_output=True,
            text=True,
            shell=True
        )

        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def run_scam_check():
    """
    Executes the Scam Check workflow by running the existing batch file:
    C:\ChatGPT\ai-bots\Scams\scripts\IsitScam.bat
    """

    import subprocess

    try:
        result = subprocess.run(
            [r"C:\ChatGPT\ai-bots\Scams\scripts\IsitScam.bat"],
            capture_output=True,
            text=True,
            shell=True
        )

        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def run_verify_company():
    """
    Launches the interactive company verification window by executing:
    C:\ChatGPT\ai-bots\Information\Scripts\Company.py
    """

    import subprocess

    try:
        result = subprocess.run(
            ["python", r"C:\\ChatGPT\\ai-bots\\Information\\Scripts\\Company.py"],
            capture_output=True,
            text=True,
            shell=True
        )

        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
