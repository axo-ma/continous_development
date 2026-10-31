"""Deprecated module import path; canonical commands are Planner controls."""
try:
    from .planner_file_hook import handle, main
except ImportError:
    from planner_file_hook import handle, main
if __name__ == '__main__':
    main()
