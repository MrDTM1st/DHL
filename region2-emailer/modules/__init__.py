"""Feature modules for the Region 2 emailer home-PC agent.

Pure logic only — no Outlook/COM imports — so everything here runs and tests
on any machine. The thin COM adapters that feed these modules live in
agent.py/supervisor.py; wiring instructions are in ../INTEGRATE_ON_HOMEPC.md.
"""
