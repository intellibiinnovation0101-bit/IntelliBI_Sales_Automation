"""
Template for credentials/lead_alert_secrets.py  (copy this file, remove '.example').

Holds the ONE shared secret for the Website Lead Alert service: the enrollment
code a counsellor types once when registering their computer. Keep it private and
rotate it if it leaks. This file is git-ignored (credentials/ is never committed).
"""

# A code you hand to counsellors during setup. Anything hard-to-guess works.
ENROLLMENT_CODE = "change-me-to-a-shared-secret"
